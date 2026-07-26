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
import sys
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


def _sandbox_root() -> Path:
    """A workspace directory the daemon can really bind-mount from the host.

    On macOS the daemon runs inside a VM and only some host paths are shared
    with it. `tempfile.mkdtemp()` returns a path under `/var/folders`, which is
    not one of them, so `docker run -v` silently creates the directory *inside
    the VM* instead: the container writes there, the host sees an empty
    directory, and cleanup frees nothing. That leak is invisible until the VM
    disk fills, at which point every run fails with "no space left on device".

    The user's home is shared by default on both Docker Desktop and Colima, so
    put the workspace under it there. Linux has no VM and no such problem.
    """
    override = os.environ.get("QUICKSTARTED_SANDBOX_DIR")
    if override:
        base = Path(override).expanduser()
    elif sys.platform == "darwin":
        base = Path.home() / ".quickstarted" / "sandboxes"
    else:
        return Path(tempfile.mkdtemp(prefix="quickstarted-"))
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="quickstarted-", dir=base))


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
        # Nothing but the task's own files goes in here: HOME and TMPDIR point
        # at the container's filesystem, so a scaffolder that demands an empty
        # directory gets one.
        self.root = _sandbox_root()
        # mkdtemp gives 0700 owned by the invoking user. Where the daemon remaps
        # container root to another uid (rootless Docker, userns-remap, some CI
        # runners), that uid cannot write the bind mount and every task dies
        # in setup. Widen the throwaway workspace instead of forcing the
        # container to a non-root user, because a quickstart is allowed to say
        # `apt-get install`.
        os.chmod(self.root, 0o777)
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

        # Verify the mount and recreate the container if it is wrong. Recreating
        # is the only available remedy: once a container is running against a
        # VM-local directory, nothing the host does will redirect it. Retrying
        # covers the case where the daemon had not yet observed a just-created
        # host directory; a genuinely unshared path fails all three times and
        # reports which direction broke.
        last = ""
        for attempt in range(3):
            sandbox = _docker(
                [
                    "run", "-d", "--name", self.container,
                    "--network", self.network,
                    "--cap-drop", "ALL",
                    "--security-opt", "no-new-privileges",
                    "--pids-limit", "512",
                    "-v", f"{self.root}:/workspace",
                    "-w", "/workspace",
                    # HOME and TMPDIR stay off the bind mount. A HOME inside the
                    # workspace fills it with dotfiles, and every scaffolding
                    # tool (`npm create`, `django-admin startproject .`) refuses
                    # to run in a directory that is not empty. Both live on the
                    # container's own filesystem, which goes away with it.
                    "-e", "HOME=/root",
                    "-e", "TMPDIR=/tmp",
                    "-e", "NO_COLOR=1",
                    "-e", "TERM=dumb",
                    *env_args,
                    self.image, "sleep", "infinity",
                ]
            )
            if sandbox.returncode != 0:
                self.cleanup()
                raise ExecutorError(
                    f"could not start sandbox container: {sandbox.stdout}"
                )
            ok, last = self._check_bind_mount()
            if ok:
                return
            self._discard_sandbox_container()
            time.sleep(1 + attempt)

        self.cleanup()
        raise ExecutorError(
            f"the sandbox workspace at {self.root} is not shared with the Docker "
            f"daemon after 3 attempts ({last}). Files the container writes would "
            f"stay inside the VM, invisible to the host and never cleaned up. Add "
            f"the directory to the daemon's file-sharing list, or set "
            f"QUICKSTARTED_SANDBOX_DIR to a path that is already shared."
        )

    def _discard_sandbox_container(self) -> None:
        """Remove a sandbox container whose bind mount turned out to be wrong.

        Anything it wrote sits on the far side of that mount where host cleanup
        cannot reach it, so empty it from inside first.
        """
        _docker(
            ["exec", self.container, "sh", "-c",
             "rm -rf /workspace/* /workspace/.[!.]* 2>/dev/null || true"],
            timeout=60,
        )
        _docker(["rm", "-f", self.container], timeout=60)

    def _check_bind_mount(self) -> tuple[bool, str]:
        """Is /workspace really the host directory, in both directions?

        If the host path is not shared with the daemon, `-v` creates a directory
        of the same name inside the VM and mounts that. Everything appears to
        work: commands run, files are written, the run passes. But the host sees
        an empty workspace, `--keep-sandbox` hands back nothing, and cleanup
        frees no bytes, so the VM disk fills one run at a time until every run
        dies on "no space left on device".

        Leaves the workspace empty either way, since a scaffolder that demands
        an empty directory would otherwise trip over the probe file.
        """
        token = uuid.uuid4().hex[:12]
        out_probe = self.root / ".quickstarted-probe-out"
        in_probe = self.root / ".quickstarted-probe-in"
        try:
            out_probe.write_text(token, encoding="utf-8")
        except OSError as exc:
            return False, f"cannot write to the workspace: {exc}"

        seen = _docker(
            ["exec", self.container, "cat", "/workspace/.quickstarted-probe-out"],
            timeout=60,
        )
        host_to_container = seen.returncode == 0 and token in (seen.stdout or "")

        # And the other direction, since a read-only or one-way share also
        # breaks the run in ways that look like a task bug. The container writes
        # its own file rather than overwriting ours: where the daemon remaps
        # container root to a subordinate uid (rootless, userns-remap, some CI
        # runners), that uid cannot overwrite a file owned by the invoking user,
        # but it can create one in a workspace we already made world-writable.
        reverse = uuid.uuid4().hex[:12]
        wrote = _docker(
            [
                "exec", self.container, "sh", "-c",
                f"printf %s {reverse} > /workspace/.quickstarted-probe-in",
            ],
            timeout=60,
        )
        container_to_host = wrote.returncode == 0 and in_probe.exists() and (
            in_probe.read_text(encoding="utf-8").strip() == reverse
        )
        out_probe.unlink(missing_ok=True)
        # Written by another uid where the daemon remaps, so removing it may need
        # the container's help.
        try:
            in_probe.unlink(missing_ok=True)
        except OSError:
            _docker(
                ["exec", self.container, "rm", "-f", "/workspace/.quickstarted-probe-in"],
                timeout=60,
            )
        return (
            host_to_container and container_to_host,
            f"host->container: {host_to_container}, "
            f"container->host: {container_to_host}",
        )

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
