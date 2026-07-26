"""Agent adapter registry.

Adapters exist for more than one vendor for a reason that is not marketing:
a benchmark run against a single model measures that model's habits as much
as the documentation. "Agents cannot follow your quickstart" is only a
defensible sentence when several of them could not.
"""

from __future__ import annotations

AGENTS = ("replay", "claude", "openai", "gemini")


def build_agent(name: str, model: str = ""):
    if name == "replay":
        from .replay import ReplayAgent

        return ReplayAgent()
    if name == "claude":
        from .claude import DEFAULT_MODEL, ClaudeAgent

        return ClaudeAgent(model=model or DEFAULT_MODEL)
    if name == "openai":
        from .openai_agent import OpenAIAgent

        return OpenAIAgent(model=model)
    if name == "gemini":
        from .gemini_agent import GeminiAgent

        return GeminiAgent(model=model)
    raise SystemExit(f"unknown agent {name!r} (choose from: {', '.join(AGENTS)})")
