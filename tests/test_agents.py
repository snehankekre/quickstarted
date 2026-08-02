"""Adapter contracts that hold without any vendor credentials."""

import time

import pytest

from quickstarted.agents import prompt
from quickstarted.agents.base import Toolbelt
from quickstarted.agents.gemini_agent import GeminiAgent
from quickstarted.agents.openai_agent import OpenAIAgent
from quickstarted.agents.registry import AGENTS, build_agent
from quickstarted.task import load_task
from quickstarted.trace import Trace

TASK = (
    "name: adapters\n"
    "goal: do a thing\n"
    "docs:\n"
    "  entrypoint: https://docs.example.com/start\n"
    "setup:\n"
    "  - python3 -m venv .venv\n"
    "success:\n"
    "  script: 'true'\n"
)


@pytest.fixture
def task(tmp_path):
    path = tmp_path / "j.yaml"
    path.write_text(TASK)
    return load_task(path)


def _run(agent, task):
    return agent.run(task, Toolbelt(task, None, Trace()), time.monotonic() + 30)


def test_registry_builds_every_advertised_agent():
    for name in AGENTS:
        assert build_agent(name, model="x") is not None


def test_unknown_agent_is_rejected():
    with pytest.raises(SystemExit):
        build_agent("telepathy")


@pytest.mark.parametrize("factory", [OpenAIAgent, GeminiAgent])
def test_vendor_adapters_refuse_to_guess_a_model(factory, task):
    """A silently chosen model makes results irreproducible."""
    outcome = _run(factory(), task)
    assert outcome.stop_reason == "error"
    assert "--model" in outcome.detail


@pytest.mark.parametrize(
    ("factory", "key_env"),
    [
        (OpenAIAgent, "QUICKSTARTED_OPENAI_API_KEY"),
        (GeminiAgent, "QUICKSTARTED_GEMINI_API_KEY"),
    ],
)
def test_vendor_adapters_name_their_key_variable(factory, key_env, task, monkeypatch):
    for name in (key_env, "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    pytest.importorskip(
        "openai" if factory is OpenAIAgent else "google.genai",
        reason="adapter reports the missing SDK before it reports the missing key",
    )
    outcome = _run(factory(model="some-model"), task)
    assert outcome.stop_reason == "error"
    assert key_env in outcome.detail


def test_every_adapter_shares_one_prompt(task):
    """Otherwise a cross-model comparison measures the prompts."""
    text = prompt.kickoff(task)
    assert task.goal in text
    assert task.docs_entrypoint in text
    # The agent must know what setup already did, or it rebuilds it.
    assert "python3 -m venv .venv" in text
    assert "read documentation with read_docs" in prompt.SYSTEM.lower()


def test_claude_adapter_uses_the_shared_prompt():
    from quickstarted.agents import claude

    assert claude.SYSTEM is prompt.SYSTEM


def test_openai_usage_does_not_double_count_cached_tokens(task, monkeypatch):
    """OpenAI's prompt_tokens includes cached tokens; Anthropic's does not.

    Adapters must normalise, or a cross-vendor cost comparison bills the same
    token twice on one side and not the other.
    """
    from types import SimpleNamespace

    import quickstarted.agents.openai_agent as mod

    calls = {"n": 0}

    class FakeCompletions:
        def create(self, **kwargs):
            calls["n"] += 1
            return SimpleNamespace(
                model="gpt-test",
                usage=SimpleNamespace(
                    prompt_tokens=1000,
                    completion_tokens=50,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=800),
                ),
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(content="done", tool_calls=None),
                    )
                ],
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(mod, "openai", SimpleNamespace(OpenAI=FakeClient), raising=False)
    monkeypatch.setitem(__import__("sys").modules, "openai", SimpleNamespace(OpenAI=FakeClient))
    monkeypatch.setenv("QUICKSTARTED_OPENAI_API_KEY", "k")

    outcome = _run(mod.OpenAIAgent(model="gpt-test"), task)
    assert calls["n"] == 1
    assert outcome.cache_read_tokens == 800
    assert outcome.input_tokens == 200, "cached tokens must not be counted twice"
    assert outcome.total_tokens == 1050


@pytest.mark.parametrize(
    "status, message, sent, expected",
    [
        (400, "adaptive thinking is not supported on this model", True, True),
        # The decision must key on what this request sent. A worker whose sibling
        # already recorded the model still sent thinking on this attempt, and
        # still has to recover; keying on the shared set made two of three
        # concurrent Haiku runs report a harness error instead.
        (400, "adaptive thinking is not supported on this model", False, False),
        # Other 400s are real errors and must not be retried into a loop.
        (400, "max_tokens must be positive", True, False),
        (429, "rate limited", True, False),
    ],
)
def test_is_thinking_refusal(status, message, sent, expected):
    from quickstarted.agents.claude import is_thinking_refusal

    assert is_thinking_refusal(status, message, sent) is expected


def test_prompt_names_every_page_on_the_documented_path(tmp_path):
    """The route is the measurement, so the agent has to be given all of it.

    FastAPI's install line is on /tutorial/ and its first application is on
    /tutorial/first-steps/. Handing over only the second is how three benchmark
    runs failed, with the harness blaming a page that was missing nothing.
    """
    from quickstarted.task import load_task

    path = tmp_path / "t.yaml"
    path.write_text(
        "name: t\ngoal: g\ndocs:\n  path:\n"
        "    - https://fastapi.tiangolo.com/tutorial/\n"
        "    - https://fastapi.tiangolo.com/tutorial/first-steps/\n"
        "success:\n  script: 'true'\n"
    )
    text = prompt.kickoff(load_task(path))
    assert "https://fastapi.tiangolo.com/tutorial/" in text
    assert "https://fastapi.tiangolo.com/tutorial/first-steps/" in text
    # Numbered, because the order is the documentation's own.
    assert text.index("1. https://fastapi.tiangolo.com/tutorial/") < text.index(
        "2. https://fastapi.tiangolo.com/tutorial/first-steps/"
    )


def test_replay_reads_the_whole_documented_path(tmp_path):
    """Replay is the record of what the docs say to type, so the trace has to
    name every page those commands came from."""
    from quickstarted.agents.replay import ReplayAgent
    from quickstarted.task import load_task

    path = tmp_path / "t.yaml"
    path.write_text(
        "name: t\ngoal: g\ndocs:\n  path:\n"
        "    - https://a.example.com/one\n"
        "    - https://a.example.com/two\n"
        "success:\n  script: 'true'\nreplay:\n  - 'true'\n"
    )
    task = load_task(path)
    read: list[str] = []

    class FakeBelt:
        def read_docs(self, url):
            read.append(url)
            return "page"

        def bash(self, command):
            return "exit code: 0\n"

    ReplayAgent().run(task, FakeBelt(), deadline=float("inf"))
    assert read == ["https://a.example.com/one", "https://a.example.com/two"]
