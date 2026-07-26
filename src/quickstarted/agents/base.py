"""Agent adapter interface and the harness-owned toolbelt.

Every agent, whatever the model or vendor, acts on the sandbox only through
the Toolbelt. That is a deliberate design choice: because docs access flows
through `fetch`, the harness records every page the agent reads (failure
attribution) and enforces the task's host allowlist. Adapters never talk
to the filesystem or network directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ..docs import DocsClient
from ..exec.base import Executor, truncate
from ..task import Task
from ..trace import Trace
from ..transport import html_to_text

_FETCH_LIMIT = 60_000


class Toolbelt:
    def __init__(
        self,
        task: Task,
        executor: Executor,
        trace: Trace,
        docs: DocsClient | None = None,
        http_get: Callable[[str], tuple[str, str]] | None = None,
    ):
        self.task = task
        self.executor = executor
        self.trace = trace
        self.docs = docs or DocsClient()
        self._http_get = http_get

    def bash(self, command: str) -> str:
        budgets = self.task.budgets
        self.trace.add("tool_call", tool="bash", command=command)
        result = self.executor.run(
            command,
            timeout=budgets.max_command_seconds,
            max_output_chars=budgets.max_output_chars,
        )
        self.trace.add(
            "tool_result",
            tool="bash",
            exit_code=result.exit_code,
            duration=round(result.duration, 3),
            timed_out=result.timed_out,
            output=result.output,
        )
        return f"exit code: {result.exit_code}\n{result.output}"

    def fetch(self, url: str) -> str:
        self.trace.add("tool_call", tool="fetch", url=url)
        if not self.task.host_allowed(url):
            allowed = ", ".join(self.task.docs_allow)
            message = (
                f"BLOCKED: {url} is outside this task's documentation allowlist "
                f"({allowed}). Only the target project's docs may be read."
            )
            self.trace.add("fetch_blocked", url=url)
            return message

        if self._http_get is not None:  # legacy injection point, used by tests
            try:
                content_type, body = self._http_get(url)
            except Exception as exc:
                self.trace.add("fetch_error", url=url, error=str(exc))
                return f"FETCH ERROR for {url}: {exc}"
            if "html" in content_type.lower():
                body = html_to_text(body)
            body = truncate(body, _FETCH_LIMIT)
            self.trace.add("docs_fetch", url=url, chars=len(body))
            return body

        try:
            result = self.docs.get(url)
        except Exception as exc:
            self.trace.add("fetch_error", url=url, error=str(exc))
            return f"FETCH ERROR for {url}: {exc}"

        if result.blocked_reason == "affordance_withheld":
            # Ablation condition: the file exists, the agent may not have it.
            self.trace.add("affordance_withheld", url=url)
            return (
                f"NOT AVAILABLE: {url} could not be retrieved. Use the regular "
                "documentation pages."
            )
        if result.blocked_reason:
            self.trace.add("fetch_blocked", url=url, reason=result.blocked_reason)
            return f"BLOCKED: {url} ({result.blocked_reason})"

        body = result.text
        original = len(body)
        body = truncate(body, _FETCH_LIMIT)
        # A page too large to read is itself an agent-experience defect, so
        # record it rather than silently trimming.
        self.trace.add(
            "docs_fetch",
            url=url,
            chars=len(body),
            original_chars=original,
            truncated=original > _FETCH_LIMIT,
            from_cache=result.from_cache,
            content_hash=result.content_hash,
        )
        if result.changed:
            self.trace.add("docs_changed", url=url, content_hash=result.content_hash)
        return body


@dataclass(frozen=True)
class AgentOutcome:
    stop_reason: str  # completed | command_failed | max_turns | timeout | refusal | error
    turns: int
    detail: str = ""
    #: Uncached prompt tokens. Vendors disagree here: Anthropic reports
    #: `input_tokens` already excluding cache traffic, while OpenAI and Google
    #: report a prompt total that *includes* it. Adapters normalise to the
    #: Anthropic meaning, so that the four counters sum to the run's real cost
    #: and no token is billed twice in a cross-vendor comparison.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_write_tokens
            + self.cache_read_tokens
        )


class Agent(Protocol):
    name: str

    def run(self, task: Task, toolbelt: Toolbelt, deadline: float) -> AgentOutcome:
        ...
