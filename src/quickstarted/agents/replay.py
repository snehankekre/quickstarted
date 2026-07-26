"""Replay agent: runs the task's documented commands literally, no LLM.

This is the free CI mode. If the commands your docs tell users to type do not
work verbatim, no agent (and no human) stands a chance; replay catches that on
every docs change without spending a token. It stops at the first failing
command, which is exactly the "docs break at step N" signal.
"""

from __future__ import annotations

import time

from ..task import Task
from .base import AgentOutcome, Toolbelt


class ReplayAgent:
    name = "replay"

    def run(self, task: Task, toolbelt: Toolbelt, deadline: float) -> AgentOutcome:
        if not task.replay:
            return AgentOutcome(
                stop_reason="error",
                turns=0,
                detail="task has no 'replay' commands; replay mode needs them",
            )
        toolbelt.fetch(task.docs_entrypoint)
        for i, command in enumerate(task.replay, start=1):
            if time.monotonic() > deadline:
                return AgentOutcome(stop_reason="timeout", turns=i - 1)
            result = toolbelt.bash(command)
            first_line = result.splitlines()[0] if result else ""
            if not first_line.startswith("exit code: 0"):
                return AgentOutcome(
                    stop_reason="command_failed",
                    turns=i,
                    detail=f"replay step {i} failed: {command}",
                )
        return AgentOutcome(stop_reason="completed", turns=len(task.replay))
