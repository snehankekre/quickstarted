"""Gemini adapter, via the google-genai SDK.

As with the OpenAI adapter there is no default model, and credentials are read
from QUICKSTARTED_GEMINI_API_KEY before GOOGLE_API_KEY.
"""

from __future__ import annotations

import os
import time

from ..journey import Journey
from .base import AgentOutcome, Toolbelt
from .prompt import BASH_DESCRIPTION, READ_DOCS_DESCRIPTION, SYSTEM, kickoff

KEY_ENV = "QUICKSTARTED_GEMINI_API_KEY"
FALLBACK_KEY_ENV = "GOOGLE_API_KEY"

FUNCTIONS = [
    {
        "name": "bash",
        "description": BASH_DESCRIPTION,
        "parameters": {
            "type": "OBJECT",
            "properties": {"command": {"type": "STRING"}},
            "required": ["command"],
        },
    },
    {
        "name": "read_docs",
        "description": READ_DOCS_DESCRIPTION,
        "parameters": {
            "type": "OBJECT",
            "properties": {"url": {"type": "STRING"}},
            "required": ["url"],
        },
    },
]


def resolve_api_key():
    return os.environ.get(KEY_ENV) or os.environ.get(FALLBACK_KEY_ENV) or None


class GeminiAgent:
    def __init__(self, model: str = ""):
        self.model = model
        self.name = f"gemini:{model}" if model else "gemini"
        self.model_reported = ""

    def run(self, journey: Journey, toolbelt: Toolbelt, deadline: float) -> AgentOutcome:
        if not self.model:
            return AgentOutcome(
                "error", 0, "gemini adapter requires --model (no default is assumed)"
            )
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            return AgentOutcome(
                "error", 0,
                'google-genai not installed; pip install "quickstarted[gemini]"',
            )
        api_key = resolve_api_key()
        if not api_key:
            return AgentOutcome("error", 0, f"no Gemini credentials: set {KEY_ENV}")

        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM,
            tools=[
                types.Tool(function_declarations=FUNCTIONS)  # type: ignore[arg-type]
            ],
        )
        contents = [
            types.Content(role="user", parts=[types.Part(text=kickoff(journey))])
        ]
        input_tokens = output_tokens = cached = 0

        def outcome(reason: str, turns: int, detail: str = "") -> AgentOutcome:
            return AgentOutcome(
                reason, turns, detail, input_tokens, output_tokens, 0, cached
            )

        for turn in range(1, journey.budgets.max_turns + 1):
            if time.monotonic() > deadline:
                return outcome("timeout", turn - 1)
            try:
                response = client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except Exception as exc:
                return outcome("error", turn - 1, f"API error: {exc}")

            usage = getattr(response, "usage_metadata", None)
            if usage:
                prompt = getattr(usage, "prompt_token_count", 0) or 0
                hit = getattr(usage, "cached_content_token_count", 0) or 0
                # As with OpenAI, the prompt count includes cached tokens.
                input_tokens += max(prompt - hit, 0)
                cached += hit
                output_tokens += getattr(usage, "candidates_token_count", 0) or 0
            self.model_reported = getattr(response, "model_version", "") or self.model
            toolbelt.trace.add("agent_turn", turn=turn, model=self.model_reported)

            candidates = response.candidates or []
            candidate = candidates[0] if candidates else None
            if candidate is None or not candidate.content:
                return outcome("error", turn, "empty response from model")
            contents.append(candidate.content)

            calls = [
                p.function_call
                for p in (candidate.content.parts or [])
                if p.function_call
            ]
            if not calls:
                final = (getattr(response, "text", "") or "").strip()
                toolbelt.trace.add("agent_final", text=final[:2000])
                return outcome("completed", turn, final[:500])

            replies = []
            for call in calls:
                arguments = dict(call.args or {})
                if call.name == "bash":
                    result = toolbelt.bash(arguments.get("command", ""))
                elif call.name == "read_docs":
                    result = toolbelt.fetch(arguments.get("url", ""))
                else:
                    result = f"Unknown tool: {call.name}"
                replies.append(
                    types.Part.from_function_response(
                        name=call.name or "unknown", response={"result": result}
                    )
                )
            contents.append(types.Content(role="user", parts=replies))

        return outcome("max_turns", journey.budgets.max_turns)
