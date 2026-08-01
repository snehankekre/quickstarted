"""Enforced local execution on macOS via sandbox-exec (Seatbelt).

This is the backend that makes the harness's central claim true rather than
merely intended. What stops a command from reaching a documentation host
directly is the kernel. All outbound network is denied except the loopback port
the harness proxy listens on, so every page the agent reads is either a
`read_docs` call or a recorded proxy request.

It also confines the blast radius of running commands that came out of a
stranger's quickstart: reads of the real home directory are denied and writes
are confined to the workspace.

Seatbelt is deprecated by Apple but present and functional; Docker is the
portable path, and CI should use it.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path

from .base import ExecutorError, ProcessExecutor

SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def available() -> bool:
    return platform.system() == "Darwin" and Path(SANDBOX_EXEC).is_file()


def build_profile(sandbox: Path, proxy_port: int | None, real_home: Path) -> str:
    """Seatbelt profile source. Later rules win, so the order of these lines
    changes what the policy permits.

    `sandbox` is the parent of both the workspace and the agent's HOME, so one
    subpath rule covers everything the run may write.
    """
    lines = [
        "(version 1)",
        "(deny default)",
        # Running programs at all.
        "(allow process-exec)",
        "(allow process-fork)",
        "(allow sysctl-read)",
        "(allow mach-lookup)",
        "(allow ipc-posix-shm)",
        "(allow signal (target same-sandbox))",
        # Interpreters and compilers read all over the system prefix.
        "(allow file-read*)",
        # ... but not the user's own files. This is the point.
        f'(deny file-read* (subpath "{real_home}"))',
        f'(allow file-read* (subpath "{sandbox}"))',
        # Writes stay inside the sandbox, plus the device files tools expect.
        f'(allow file-write* (subpath "{sandbox}"))',
        '(allow file-write* (regex #"^/dev/"))',
        "(allow file-ioctl)",
    ]
    if proxy_port:
        # The only route off the machine is the harness proxy.
        lines.append(f'(allow network-outbound (remote ip "localhost:{proxy_port}"))')
        # Loopback DNS and similar helpers travel over unix sockets; the proxy
        # resolves real hostnames on the agent's behalf.
        lines.append("(allow network-outbound (remote unix-socket))")
        # Loopback, so a task can start the server its quickstart documents and
        # then ask it a question. Three rules, and all three are needed:
        # `network-bind` does not match a `localhost:*` filter (it silently
        # refuses the bind, which is why every serve-and-poll task failed under
        # this backend), `accept` is inbound, and polling is outbound.
        #
        # This is wider than Docker, where the sandbox has its own network
        # namespace and loopback reaches nothing but the task. Here a command
        # can also reach services the developer happens to be running on their
        # own machine. Remote egress stays denied, so the guarantee that matters
        # (documentation hosts are unreachable from the shell, and every page
        # read is recorded) is untouched.
        lines.append('(allow network-bind (local ip "*:*"))')
        lines.append('(allow network-inbound (local ip "localhost:*"))')
        lines.append('(allow network-outbound (remote ip "localhost:*"))')
    return "\n".join(lines) + "\n"


class SeatbeltExecutor(ProcessExecutor):
    name = "seatbelt"
    enforced = True

    def __init__(
        self,
        keep: bool = False,
        proxy_url: str | None = None,
        workspace: Path | None = None,
    ):
        if not available():
            raise ExecutorError(
                "seatbelt backend requires macOS with /usr/bin/sandbox-exec"
            )
        super().__init__(keep=keep, proxy_url=proxy_url, workspace=workspace)
        port = None
        if proxy_url:
            port = int(proxy_url.rsplit(":", 1)[-1].strip("/"))
        real_home = Path(os.path.expanduser("~")).resolve()
        self.profile = build_profile(self.base.resolve(), port, real_home)
        self._profile_path = self.support / "tmp" / ".quickstarted-sandbox.sb"
        self._profile_path.write_text(self.profile, encoding="utf-8")

    def argv(self, command: str) -> list[str]:
        return [SANDBOX_EXEC, "-f", str(self._profile_path), "bash", "-c", command]
