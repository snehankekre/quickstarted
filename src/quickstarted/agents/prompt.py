"""The prompt every adapter shares.

Kept in one place deliberately. If each vendor adapter phrased the task its
own way, a cross-model pass-rate comparison would be measuring the prompts as
much as the documentation, and the benchmark would mean nothing.
"""

from __future__ import annotations

from ..task import Task

SYSTEM = """You are a developer trying out an unfamiliar software project by \
following its documentation, inside a fresh throwaway workspace (your current \
directory). Your goal is stated in the first user message.

Rules of the exercise:
- Your ONLY source of information about the project is its documentation, \
read via the read_docs tool. Do not rely on prior knowledge of this specific \
project; the point is to test whether the docs alone get a newcomer to the \
goal. General programming knowledge is fine.
- Start by reading the documentation entrypoint, then follow links from it \
with read_docs when you need more.
- Use the bash tool to run commands in the workspace. Each command runs in a \
fresh shell in the workspace directory; state persists only on disk (use \
files, virtualenvs, etc.).
- The shell cannot reach documentation websites. That is deliberate: read \
documentation with read_docs, which records what you read.
- When you believe the goal is achieved, verify it yourself with a command, \
then stop and summarize what you did in one short paragraph. Do not keep \
polishing after the goal is met.
- If you are genuinely stuck because the documentation is missing or wrong, \
stop and say exactly where the docs failed you: which page, which step.
"""

READ_DOCS_DESCRIPTION = (
    "Read a documentation page. Call this whenever you need information about "
    "the target project: before your first command, and again whenever the "
    "docs you have already read do not answer the question at hand. Only "
    "documentation hosts on this task's allowlist are reachable; other "
    "URLs return BLOCKED."
)

BASH_DESCRIPTION = (
    "Run a shell command in the workspace. Each call runs in a fresh shell "
    "whose working directory is the workspace; state persists only on disk."
)


def kickoff(task: Task) -> str:
    text = (
        f"Goal: {task.goal}\n\n"
        f"Documentation entrypoint: {task.docs_entrypoint}\n"
        f"Allowed documentation hosts: {', '.join(task.docs_allow)}"
    )
    if task.setup:
        # Without this the agent cannot tell a prepared workspace from an empty
        # one, and may rebuild state that setup already created.
        text += "\n\nThe workspace was already prepared by running:\n" + "\n".join(
            f"  $ {cmd}" for cmd in task.setup
        )
    return text
