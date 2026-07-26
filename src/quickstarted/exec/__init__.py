"""Execution backends and the policy for choosing one.

`auto` prefers enforcement: Docker when a daemon is reachable, Seatbelt on
macOS, and local only as a last resort. Choosing an unenforced backend is
allowed but never silent.
"""

from __future__ import annotations

import platform

from . import docker as _docker
from . import seatbelt as _seatbelt
from .base import CommandResult, Executor, ExecutorError, ProcessExecutor, truncate
from .docker import DockerExecutor
from .local import LocalExecutor
from .seatbelt import SeatbeltExecutor

BACKENDS = ("auto", "docker", "seatbelt", "local")


def available_backends() -> list[str]:
    found = []
    if _docker.available():
        found.append("docker")
    if _seatbelt.available():
        found.append("seatbelt")
    found.append("local")
    return found


def resolve_backend(requested: str = "auto") -> str:
    if requested not in BACKENDS:
        raise ExecutorError(
            f"unknown backend {requested!r}; choose from {', '.join(BACKENDS)}"
        )
    if requested != "auto":
        return requested
    for candidate in ("docker", "seatbelt"):
        if candidate in available_backends():
            return candidate
    return "local"


def make_executor(
    backend: str,
    keep: bool = False,
    proxy_url: str | None = None,
    network_allow=(),
    docs_hosts=(),
    image: str | None = None,
    trace=None,
) -> Executor:
    if backend == "docker":
        return DockerExecutor(
            keep=keep,
            network_allow=network_allow,
            docs_hosts=docs_hosts,
            image=image or _docker.DEFAULT_IMAGE,
            trace=trace,
        )
    if backend == "seatbelt":
        return SeatbeltExecutor(keep=keep, proxy_url=proxy_url)
    if backend == "local":
        return LocalExecutor(keep=keep, proxy_url=proxy_url)
    raise ExecutorError(f"unknown backend {backend!r}")


def needs_host_proxy(backend: str) -> bool:
    """Docker runs its own proxy sidecar; process backends need one on the host."""
    return backend in ("seatbelt", "local")


__all__ = [
    "BACKENDS",
    "CommandResult",
    "DockerExecutor",
    "Executor",
    "ExecutorError",
    "LocalExecutor",
    "ProcessExecutor",
    "SeatbeltExecutor",
    "available_backends",
    "make_executor",
    "needs_host_proxy",
    "platform",
    "resolve_backend",
    "truncate",
]
