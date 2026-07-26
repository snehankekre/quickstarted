"""Execution backends for agent-issued commands.

An executor owns the workspace a task runs in and decides what a command
can reach. Backends differ in one respect that matters: whether the task's
network policy is *enforced* by the operating system or merely *requested*.

`enforced = False` means an agent that ignores the proxy environment can talk
to any host it likes, and every docs page it reads that way is invisible to
the trace. Since attribution of a failure to a documentation page is the whole
product, unenforced backends are for developing tasks against code you
trust, never for benchmarking third-party projects.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

_TRUNCATION_NOTE = "\n[... output truncated by quickstarted ...]\n"


@dataclass(frozen=True)
class CommandResult:
    exit_code: int
    output: str
    duration: float
    timed_out: bool = False


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    tail = text[-(limit // 2) :]
    return head + _TRUNCATION_NOTE + tail


class ExecutorError(RuntimeError):
    """Raised when a backend cannot be started on this machine."""


class Executor(Protocol):
    name: str
    enforced: bool
    root: Path

    def run(
        self, command: str, timeout: int, max_output_chars: int = 20_000
    ) -> CommandResult:
        ...

    def cleanup(self) -> None:
        ...


class ProcessExecutor:
    """Shared plumbing for backends that run commands as local processes."""

    name = "process"
    enforced = False

    def __init__(self, keep: bool = False, proxy_url: str | None = None):
        self.root = Path(tempfile.mkdtemp(prefix="quickstarted-"))
        (self.root / "tmp").mkdir()
        self.keep = keep
        self.proxy_url = proxy_url

    def env(self) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(self.root),
            "TMPDIR": str(self.root / "tmp"),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", os.environ.get("LANG", "en_US.UTF-8")),
            "TERM": "dumb",
            "NO_COLOR": "1",
        }
        if self.proxy_url:
            # Both cases: tools are inconsistent about which they read.
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
                env[key] = self.proxy_url
                env[key.lower()] = self.proxy_url
            # Loopback must not go through the proxy. Tasks routinely start a
            # server and then ask it a question, and without this the request is
            # sent to the proxy, which refuses it as an unlisted host.
            for key in ("NO_PROXY", "no_proxy"):
                env[key] = "localhost,127.0.0.1,::1"
        return env

    def argv(self, command: str) -> list[str]:
        return ["bash", "-c", command]

    def run(
        self, command: str, timeout: int, max_output_chars: int = 20_000
    ) -> CommandResult:
        start = time.monotonic()
        try:
            proc = subprocess.run(
                self.argv(command),
                cwd=self.root,
                env=self.env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
                errors="replace",
            )
            output, exit_code, timed_out = proc.stdout or "", proc.returncode, False
        except subprocess.TimeoutExpired as exc:
            raw = exc.output or b""
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            output = raw + f"\n[command timed out after {timeout}s]"
            exit_code, timed_out = 124, True
        duration = time.monotonic() - start
        return CommandResult(
            exit_code=exit_code,
            output=truncate(output, max_output_chars),
            duration=duration,
            timed_out=timed_out,
        )

    def cleanup(self) -> None:
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)
