"""Claude agent adapter: a manual tool-use loop on the plain anthropic SDK.

The loop is deliberately hand-rolled rather than delegated to a heavyweight
agent framework: the harness must own the tools (sandboxed bash + allowlisted
docs fetch) so that every action and every page read lands in the trace.

Requires the `anthropic` package (pip install "quickstarted[claude]") and an API
key. The key is read from QUICKSTARTED_ANTHROPIC_API_KEY first so it can live in
your environment without other Anthropic tooling (Claude Code, for one) picking
it up and billing against it; ANTHROPIC_API_KEY is honoured as a fallback for
CI, where that name is the convention.
"""

from __future__ import annotations

import os
import random
import time
from typing import Any

from ..task import Task
from .base import AgentOutcome, Toolbelt
from .prompt import READ_DOCS_DESCRIPTION, SYSTEM
from .prompt import kickoff as build_kickoff

DEFAULT_MODEL = "claude-opus-5"

#: Transient upstream conditions. A benchmark sweep that dies on one 529 is
#: not a benchmark, and a run that reports these as a documentation failure is
#: worse than one that dies.
RETRYABLE_STATUS = (408, 409, 429, 500, 502, 503, 529)
MAX_ATTEMPTS = 5
#: Models that rejected adaptive thinking, learned at runtime from the API's own
#: 400 rather than kept as a list here. Module-level so one refusal teaches the
#: whole suite instead of every run paying for the same round trip.
_NO_ADAPTIVE_THINKING: set[str] = set()


def is_thinking_refusal(status_code: int, message: str, sent_thinking: bool) -> bool:
    """Did the API reject this request only because it asked for thinking?

    Keyed on what the request sent, never on the shared set above: under
    `--workers N` every worker hits the same 400 at once, and a check against the
    set would let the first worker recover while the rest read the model as
    already-known, skip the retry, and report a harness error for a run that
    would have worked.
    """
    return (
        status_code == 400
        and sent_thinking
        and "thinking" in (message or "").lower()
    )

KEY_ENV = "QUICKSTARTED_ANTHROPIC_API_KEY"
FALLBACK_KEY_ENV = "ANTHROPIC_API_KEY"


class _Usage:
    """Running token totals for one task.

    The API reports cached prompt tokens outside `input_tokens`, so a run with
    prompt caching on looks nearly free if you only add up that field. All four
    counters are kept so the reported cost is the real one.
    """

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_write_tokens = 0
        self.cache_read_tokens = 0

    @property
    def total(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_write_tokens
            + self.cache_read_tokens
        )

    def add(self, usage) -> dict:
        turn = {
            "input_tokens": usage.input_tokens or 0,
            "output_tokens": usage.output_tokens or 0,
            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        }
        for field, value in turn.items():
            setattr(self, field, getattr(self, field) + value)
        return turn


def resolve_api_key():
    """The quickstarted-specific name wins, so the key can live in a shell
    without other Anthropic tooling on the machine spending it."""
    return os.environ.get(KEY_ENV) or os.environ.get(FALLBACK_KEY_ENV) or None

_READ_DOCS_TOOL = {
    "name": "read_docs",
    "description": READ_DOCS_DESCRIPTION,
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Absolute http(s) URL of the docs page"}
        },
        "required": ["url"],
    },
}


class ClaudeAgent:
    name = "claude"

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 16000):
        self.model = model
        self.max_tokens = max_tokens
        self.name = f"claude:{model}"
        #: The exact model the API served, which is what a benchmark must cite:
        #: an alias like "claude-opus-5" can resolve to different builds over
        #: time, and a pass-rate trend across a silent change is meaningless.
        self.model_reported = ""

    def run(self, task: Task, toolbelt: Toolbelt, deadline: float) -> AgentOutcome:
        try:
            import anthropic
        except ImportError:
            return AgentOutcome(
                stop_reason="error",
                turns=0,
                detail='anthropic package not installed; pip install "quickstarted[claude]"',
            )

        api_key = resolve_api_key()
        try:
            # max_retries=0: the harness owns retry policy so that every wait
            # and every transient failure lands in the trace instead of being
            # silently absorbed by the SDK.
            client = (
                anthropic.Anthropic(api_key=api_key, max_retries=0)
                if api_key
                else anthropic.Anthropic(max_retries=0)
            )
        except TypeError as exc:
            return AgentOutcome(
                stop_reason="error",
                turns=0,
                detail=f"no Anthropic credentials: set {KEY_ENV} ({exc})",
            )
        tools = [
            {"type": "bash_20250124", "name": "bash"},
            _READ_DOCS_TOOL,
        ]
        kickoff = build_kickoff(task)
        messages: list[dict[str, Any]] = [{"role": "user", "content": kickoff}]
        used = _Usage()

        def outcome(stop_reason: str, turns: int, detail: str = "") -> AgentOutcome:
            return AgentOutcome(
                stop_reason,
                turns,
                detail,
                used.input_tokens,
                used.output_tokens,
                used.cache_write_tokens,
                used.cache_read_tokens,
            )

        def call_with_retries(turn: int):
            """Returns (response, error_detail). Retries transient upstream faults."""
            last = ""
            for attempt in range(1, MAX_ATTEMPTS + 1):
                # What *this* request sent. The shared set below can change
                # under a sibling worker between the call and the failure.
                # Under --workers N every worker hits the same 400 at once; if
                # the recovery below keys off the set, the first worker records
                # the model and the rest read it as already-known, skip the
                # retry, and report a harness error for a run that would have
                # worked.
                sent_thinking = self.model not in _NO_ADAPTIVE_THINKING
                try:
                    return (
                        # The SDK's overloads require literal-typed tool
                        # params; ours are built at runtime. Behaviour is
                        # covered by the live runs rather than these types.
                        client.messages.create(  # type: ignore[call-overload]
                            model=self.model,
                            max_tokens=self.max_tokens,
                            cache_control={"type": "ephemeral"},
                            system=SYSTEM,
                            tools=tools,
                            messages=messages,
                            **(
                                {"thinking": {"type": "adaptive"}}
                                if sent_thinking
                                else {}
                            ),
                        ),
                        "",
                    )
                except TypeError as exc:
                    # The SDK resolves credentials lazily, at request time.
                    return None, f"no Anthropic credentials: set {KEY_ENV} ({exc})"
                except anthropic.APIConnectionError as exc:
                    last = f"connection error: {exc}"
                except anthropic.APIStatusError as exc:
                    last = f"API error {exc.status_code}: {exc.message}"
                    if is_thinking_refusal(
                        exc.status_code, exc.message or "", sent_thinking
                    ):
                        # Not every model accepts adaptive thinking, and which
                        # ones do changes faster than a hardcoded list would
                        # survive. Learn it from the refusal and retry without
                        # it: Haiku 4.5 otherwise fails every run of a suite in
                        # under seven seconds with nothing to show for it.
                        _NO_ADAPTIVE_THINKING.add(self.model)
                        toolbelt.trace.add(
                            "adaptive_thinking_unsupported",
                            turn=turn, model=self.model,
                        )
                        continue
                    if exc.status_code not in RETRYABLE_STATUS:
                        return None, last
                if attempt == MAX_ATTEMPTS:
                    break
                # Exponential backoff with jitter, never past the deadline.
                delay = min(2.0 ** (attempt - 1), 30.0) * (0.5 + random.random())
                if time.monotonic() + delay > deadline:
                    return None, last
                toolbelt.trace.add(
                    "api_retry", turn=turn, attempt=attempt,
                    sleep=round(delay, 2), error=last,
                )
                time.sleep(delay)
            return None, last

        for turn in range(1, task.budgets.max_turns + 1):
            if time.monotonic() > deadline:
                return outcome("timeout", turn - 1)
            cap = task.budgets.max_tokens
            if cap and used.total >= cap:
                return outcome("token_budget", turn - 1, f"token budget {cap} exhausted")

            response, error = call_with_retries(turn)
            if response is None:
                return outcome("error", turn - 1, error)

            self.model_reported = getattr(response, "model", "") or self.model
            turn_usage = used.add(response.usage)
            toolbelt.trace.add(
                "agent_turn", turn=turn, stop_reason=response.stop_reason,
                model=self.model_reported, **turn_usage
            )

            if response.stop_reason == "refusal":
                return outcome("refusal", turn, "model refused")

            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "pause_turn":
                continue

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                final_text = " ".join(
                    b.text for b in response.content if b.type == "text"
                ).strip()
                toolbelt.trace.add("agent_final", text=final_text[:2000])
                return outcome("completed", turn, final_text[:500])

            results = []
            for tu in tool_uses:
                if tu.name == "bash":
                    if tu.input.get("restart"):
                        out = (
                            "Shell session reset. (Each command already runs "
                            "in a fresh shell.)"
                        )
                    else:
                        out = toolbelt.bash(tu.input.get("command", ""))
                elif tu.name == "read_docs":
                    out = toolbelt.fetch(tu.input.get("url", ""))
                else:
                    out = f"Unknown tool: {tu.name}"
                results.append(
                    {"type": "tool_result", "tool_use_id": tu.id, "content": out}
                )
            messages.append({"role": "user", "content": results})

        return outcome("max_turns", task.budgets.max_turns)
