"""Backwards-compatible aliases for the pre-executor API.

`Sandbox` was the only execution backend in v0. It is now `LocalExecutor`, one
of three, and the least safe: see `quickstarted.exec`.
"""

from __future__ import annotations

from .exec.base import CommandResult, truncate
from .exec.local import LocalExecutor

#: Deprecated alias. Prefer `quickstarted.exec.make_executor`.
Sandbox = LocalExecutor

__all__ = ["CommandResult", "LocalExecutor", "Sandbox", "truncate"]
