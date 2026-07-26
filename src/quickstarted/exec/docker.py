"""Enforced execution in containers: the portable backend, and what CI uses.

Topology, which is the whole reason this is enforced rather than requested:

    [sandbox container]  --internal network-->  [proxy sidecar] --bridge--> internet

The sandbox container is attached *only* to a Docker network created with
`--internal`, which has no route off the host. The single reachable address is
the sidecar, which is attached to both that network and a normal bridge. So a
command cannot leave the machine except through the harness's policy, whether
or not it honours the proxy environment variables.

The sidecar writes its events to stdout; they are collected at teardown and
merged into the run trace.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from ..net.proxy import DEFAULT_NETWORK_ALLOW
from .base import CommandResult, ExecutorError, truncate

DEFAULT_IMAGE = "python:3.12-slim"
PROXY_IMAGE = "python:3.12-alpine"
PROXY_PORT = 8080
_NET_DIR = Path(__file__).resolve().parent.parent / "net"


def available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError):
        return False


def _docker(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        timeout=timeout,
    )


class DockerExecutor:
    name = "docker"
    enforced = True

    def __init__(
        self,
        keep: bool = False,
        network_allow=DEFAULT_NETWORK_ALLOW,
        docs_hosts=(),
        image: str = DEFAULT_IMAGE,
        trace=None,
    ):
        if not available():
            raise ExecutorError(
                "docker backend requires a running Docker daemon "
                "(`docker info` must succeed)"
            )
        self.keep = keep
        self.image = image
        self.trace = trace
        self.root = Path(tempfile.mkdtemp(prefix="quickstarted-"))
        (self.root / "tmp").mkdir()
        # mkdtemp gives 0700 owned by the invoking user. Where the daemon remaps
        # container root to another uid (rootless Docker, userns-remap, some CI
        # runners), that uid cannot write the bind mount and every task dies
        # in setup. Widen the throwaway workspace instead of forcing the
        # container to a non-root user, because a quickstart is allowed to say
        # `apt-get install`.
        os.chmod(self.root, 0o777)
        os.chmod(self.root / "tmp", 0o777)
        token = uuid.uuid4().hex[:10]
        self.network = f"quickstarted-net-{token}"
        self.proxy_name = f"quickstarted-proxy-{token}"
        self.container = f"quickstarted-sbx-{token}"
        self._started = False
        self._start(tuple(network_allow), tuple(docs_hosts))

    # -- lifecycle ------------------------------------------------------
    def _start(self, network_allow, docs_hosts) -> None:
        created = _docker(["network", "create", "--internal", self.network])
        if created.returncode != 0:
            raise ExecutorError(f"could not create docker network: {created.stdout}")
        self._started = True

        proxy = _docker(
            [
                "run", "-d", "--name", self.proxy_name,
                "--network", self.network,
                "-v", f"{_NET_DIR}:/opt/quickstarted:ro",
                "-e", f"QUICKSTARTED_PROXY_PORT={PROXY_PORT}",
                "-e", "QUICKSTARTED_NETWORK_ALLOW=" + ",".join(network_allow),
                "-e", "QUICKSTARTED_DOCS_HOSTS=" + ",".join(docs_hosts),
                PROXY_IMAGE,
                "python", "/opt/quickstarted/proxy_main.py",
            ]
        )
        if proxy.returncode != 0:
            self.cleanup()
            raise ExecutorError(f"could not start proxy sidecar: {proxy.stdout}")

        # Give the sidecar, and only the sidecar, a route to the internet.
        bridged = _docker(["network", "connect", "bridge", self.proxy_name])
        if bridged.returncode != 0:
            self.cleanup()
            raise ExecutorError(f"could not bridge proxy sidecar: {bridged.stdout}")

        proxy_url = f"http://{self.proxy_name}:{PROXY_PORT}"
        env_args: list[str] = []
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
            env_args += ["-e", f"{key}={proxy_url}", "-e", f"{key.lower()}={proxy_url}"]
        # Loopback stays off the proxy; see ProcessExecutor.env for why.
        for key in ("NO_PROXY", "no_proxy"):
            env_args += ["-e", f"{key}=localhost,127.0.0.1,::1"]

        sandbox = _docker(
            [
                "run", "-d", "--name", self.container,
                "--network", self.network,
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--pids-limit", "512",
                "-v", f"{self.root}:/workspace",
                "-w", "/workspace",
                "-e", "HOME=/workspace",
                "-e", "TMPDIR=/workspace/tmp",
                "-e", "NO_COLOR=1",
                "-e", "TERM=dumb",
                *env_args,
                self.image, "sleep", "infinity",
            ]
        )
        if sandbox.returncode != 0:
            self.cleanup()
            raise ExecutorError(f"could not start sandbox container: {sandbox.stdout}")

    def run(
        self, command: str, timeout: int, max_output_chars: int = 20_000
    ) -> CommandResult:
        start = time.monotonic()
        try:
            proc = _docker(
                ["exec", "-w", "/workspace", self.container, "bash", "-c", command],
                timeout=timeout,
            )
            output, exit_code, timed_out = proc.stdout or "", proc.returncode, False
        except subprocess.TimeoutExpired as exc:
            raw = exc.output or ""
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            # The exec is detached from our process; stop it inside the container.
            _docker(["exec", self.container, "pkill", "-9", "-f", "bash -c"], timeout=30)
            output = raw + f"\n[command timed out after {timeout}s]"
            exit_code, timed_out = 124, True
        return CommandResult(
            exit_code=exit_code,
            output=truncate(output, max_output_chars),
            duration=time.monotonic() - start,
            timed_out=timed_out,
        )

    def collect_proxy_events(self) -> int:
        """Merge sidecar events into the trace. Returns how many were merged."""
        if self.trace is None or not self._started:
            return 0
        logs = _docker(["logs", self.proxy_name], timeout=60)
        if logs.returncode != 0:
            return 0
        merged = 0
        for line in logs.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.pop("type", "egress")
            event.pop("ts", None)
            self.trace.add(kind, **event)
            merged += 1
        return merged

    def cleanup(self) -> None:
        if not self._started:
            return
        self.collect_proxy_events()
        for name in (self.container, self.proxy_name):
            _docker(["rm", "-f", name], timeout=60)
        _docker(["network", "rm", self.network], timeout=60)
        self._started = False
        if not self.keep:
            shutil.rmtree(self.root, ignore_errors=True)
