"""quickstarted: test whether an AI agent can complete your quickstart.

Tasks (YAML) state a goal, a docs entrypoint, and a machine-checkable
success assertion. The harness runs an agent in a sandbox whose only docs
access is a recorded, allowlisted fetch tool, then scores the run with the
assertion script. See README.md.
"""

from ._version import __version__
from .run import RunResult, ScoreResult, run_task
from .task import Budgets, Task, TaskError, load_task
from .trace import Trace

__all__ = [
    "Budgets",
    "RunResult",
    "ScoreResult",
    "Task",
    "TaskError",
    "Trace",
    "__version__",
    "load_task",
    "run_task",
]
