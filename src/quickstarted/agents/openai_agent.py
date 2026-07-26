"""OpenAI adapter: the same tool loop, the same harness-owned tools.

There is deliberately no default model. A benchmark that silently picks a
model for you produces numbers nobody can reproduce, and vendor model names
change faster than a pinned default would survive. Pass `--model`.

Credentials come from QUICKSTARTED_OPENAI_API_KEY first, falling back to
OPENAI_API_KEY, so a key can live in a shell without other tooling spending
it.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from ..task import Task
from .base import AgentOutcome, Toolbelt
from .prompt import BASH_DESCRIPTION, READ_DOCS_DESCRIPTION, SYSTEM, kickoff

KEY_ENV = "QUICKSTARTED_OPENAI_API_KEY"
FALLBACK_KEY_ENV = "OPENAI_API_KEY"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": BASH_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_docs",
            "description": READ_DOCS_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
]


def resolve_api_key():
    return os.environ.get(KEY_ENV) or os.environ.get(FALLBACK_KEY_ENV) or None


class OpenAIAgent:
    def __init__(self, model: str = "", max_tokens: int = 16000):
        self.model = model
        self.max_tokens = max_tokens
        self.name = f"openai:{model}" if model else "openai"
        self.model_reported = ""

    def run(self, task: Task, toolbelt: Toolbelt, deadline: float) -> AgentOutcome:
        if not self.model:
            return AgentOutcome(
                "error", 0, "openai adapter requires --model (no default is assumed)"
            )
        try:
            import openai
        except ImportError:
            return AgentOutcome(
                "error", 0,
                'openai package not installed; pip install "quickstarted[openai]"',
            )
        api_key = resolve_api_key()
        if not api_key:
            return AgentOutcome("error", 0, f"no OpenAI credentials: set {KEY_ENV}")
        client = openai.OpenAI(api_key=api_key, max_retries=0)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": kickoff(task)},
        ]
        input_tokens = output_tokens = cached = 0

        def outcome(reason: str, turns: int, detail: str = "") -> AgentOutcome:
            return AgentOutcome(
                reason, turns, detail, input_tokens, output_tokens, 0, cached
            )

        for turn in range(1, task.budgets.max_turns + 1):
            if time.monotonic() > deadline:
                return outcome("timeout", turn - 1)
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    # The SDK types these as TypedDicts; ours are built at
                    # runtime and shared across adapters. Behaviour is covered
                    # by live runs rather than these annotations.
                    messages=messages,  # type: ignore[arg-type]
                    tools=TOOLS,  # type: ignore[arg-type]
                    max_completion_tokens=self.max_tokens,
                )
            except Exception as exc:
                return outcome("error", turn - 1, f"API error: {exc}")

            usage = getattr(response, "usage", None)
            if usage:
                prompt = getattr(usage, "prompt_tokens", 0) or 0
                details = getattr(usage, "prompt_tokens_details", None)
                hit = (getattr(details, "cached_tokens", 0) or 0) if details else 0
                # prompt_tokens includes the cached ones here, unlike Anthropic.
                # Subtract so the counters do not double count the same tokens.
                input_tokens += max(prompt - hit, 0)
                cached += hit
                output_tokens += getattr(usage, "completion_tokens", 0) or 0
            self.model_reported = getattr(response, "model", "") or self.model

            choice = response.choices[0]
            message = choice.message
            toolbelt.trace.add(
                "agent_turn", turn=turn, stop_reason=choice.finish_reason,
                model=self.model_reported,
            )
            calls = list(getattr(message, "tool_calls", None) or [])
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.function.name,
                                "arguments": call.function.arguments,
                            },
                        }
                        for call in calls
                    ],
                }
                if calls
                else {"role": "assistant", "content": message.content or ""}
            )
            if not calls:
                final = (message.content or "").strip()
                toolbelt.trace.add("agent_final", text=final[:2000])
                return outcome("completed", turn, final[:500])

            for call in calls:
                try:
                    arguments = json.loads(call.function.arguments or "{}")
                except ValueError:
                    arguments = {}
                if call.function.name == "bash":
                    result = toolbelt.bash(arguments.get("command", ""))
                elif call.function.name == "read_docs":
                    result = toolbelt.fetch(arguments.get("url", ""))
                else:
                    result = f"Unknown tool: {call.function.name}"
                messages.append(
                    {"role": "tool", "tool_call_id": call.id, "content": result}
                )

        return outcome("max_turns", task.budgets.max_turns)
