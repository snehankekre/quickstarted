"""Statistics, classification, and the machine-readable contract."""

import json
import textwrap
from xml.etree import ElementTree as ET

import pytest

from quickstarted.agents.base import AgentOutcome
from quickstarted.journey import load_journey
from quickstarted.pricing import ModelPrice, PriceBook
from quickstarted.results import SCHEMA_VERSION, junit_xml, suite_document
from quickstarted.run import (
    BUDGET_EXHAUSTED,
    DOCS_GAP,
    HARNESS_ERROR,
    INFRA_ERROR,
    PASSED,
    RunResult,
    ScoreResult,
    classify,
)
from quickstarted.suite import JourneyStats, SuiteResult, run_suite
from quickstarted.trace import Trace

JOURNEY = textwrap.dedent(
    """
    name: demo
    goal: create done.txt
    docs:
      entrypoint: https://example.com/docs/
    success:
      script: test -f done.txt
    budgets:
      max_seconds: 60
    replay:
      - echo x > done.txt
    """
)


@pytest.fixture
def journey(tmp_path):
    path = tmp_path / "j.yaml"
    path.write_text(JOURNEY)
    return load_journey(path)


def _result(journey, classification, attempt=1, passed=None, tokens=(0, 0, 0, 0)):
    if passed is None:
        passed = classification == PASSED
    outcome = AgentOutcome("completed", 3, "", *tokens)
    return RunResult(
        journey=journey,
        agent_name="claude:test",
        outcome=outcome,
        score=ScoreResult(passed, 0 if passed else 1, "out"),
        trace=Trace(),
        duration=1.0,
        sandbox_path="/tmp/x",
        backend="seatbelt",
        enforced=True,
        classification=classification,
        attempt=attempt,
        model_reported="claude-test-1",
    )


# -- classification ----------------------------------------------------


def test_passing_run_is_passed():
    assert classify(AgentOutcome("completed", 1), ScoreResult(True, 0, ""), Trace()) == PASSED


def test_failed_check_after_a_finished_agent_is_a_docs_gap():
    got = classify(AgentOutcome("completed", 4), ScoreResult(False, 1, ""), Trace())
    assert got == DOCS_GAP


def test_rate_limit_is_infrastructure_not_a_docs_failure():
    outcome = AgentOutcome("error", 2, "API error 429: rate limit")
    assert classify(outcome, None, Trace()) == INFRA_ERROR


def test_overloaded_upstream_is_infrastructure():
    outcome = AgentOutcome("error", 1, "API error 529: overloaded")
    assert classify(outcome, None, Trace()) == INFRA_ERROR


def test_exhausted_budget_is_not_a_docs_failure():
    for reason in ("max_turns", "timeout", "token_budget"):
        outcome = AgentOutcome(reason, 20)
        assert classify(outcome, ScoreResult(False, 1, ""), Trace()) == BUDGET_EXHAUSTED


def test_missing_credentials_is_a_harness_error():
    outcome = AgentOutcome("error", 0, "no Anthropic credentials: set X")
    assert classify(outcome, None, Trace()) == HARNESS_ERROR


def test_blocked_registry_is_infrastructure():
    trace = Trace()
    trace.add("egress_error", host="pypi.org", error="timed out")
    outcome = AgentOutcome("completed", 5)
    assert classify(outcome, ScoreResult(False, 1, ""), trace) == INFRA_ERROR


# -- statistics --------------------------------------------------------


def test_pass_rate_excludes_inconclusive_runs(journey):
    stat = JourneyStats("demo", "claude:test")
    stat.runs = [
        _result(journey, PASSED),
        _result(journey, DOCS_GAP),
        _result(journey, INFRA_ERROR),  # must not count either way
    ]
    assert stat.attempts == 3
    assert len(stat.evidential) == 2
    assert stat.pass_rate == 0.5
    assert stat.discarded == {INFRA_ERROR: 1}


def test_pass_rate_is_unknown_when_nothing_was_evidence(journey):
    stat = JourneyStats("demo", "claude:test")
    stat.runs = [_result(journey, INFRA_ERROR), _result(journey, BUDGET_EXHAUSTED)]
    assert stat.pass_rate is None, "no evidence must not read as 0% pass"


def test_ci_gate_fails_when_evidence_is_absent(journey):
    stat = JourneyStats("demo", "claude:test")
    stat.runs = [_result(journey, INFRA_ERROR)]
    assert SuiteResult(stats=[stat]).all_passed is False


def test_repeat_produces_a_rate_not_a_verdict(journey, monkeypatch):
    import quickstarted.transport as transport

    monkeypatch.setattr(
        transport,
        "http_get",
        lambda url, timeout=30, method="GET": transport.HttpResponse(
            200, "text/plain", "docs"
        ),
    )
    from quickstarted.agents.replay import ReplayAgent

    suite = run_suite([journey], lambda: ReplayAgent(), repeat=3, backend="local")
    assert suite.stats[0].attempts == 3
    assert suite.stats[0].pass_rate == 1.0
    assert [r.attempt for r in suite.stats[0].runs] == [1, 2, 3]


def test_parallel_workers_produce_the_same_totals(journey, monkeypatch):
    import quickstarted.transport as transport

    monkeypatch.setattr(
        transport,
        "http_get",
        lambda url, timeout=30, method="GET": transport.HttpResponse(
            200, "text/plain", "docs"
        ),
    )
    from quickstarted.agents.replay import ReplayAgent

    suite = run_suite(
        [journey], lambda: ReplayAgent(), repeat=4, workers=4, backend="local"
    )
    assert suite.stats[0].attempts == 4
    assert suite.stats[0].pass_rate == 1.0


# -- pricing -----------------------------------------------------------


def test_no_price_book_means_no_invented_dollars(journey):
    stat = JourneyStats("demo", "claude:test")
    stat.runs = [_result(journey, PASSED, tokens=(100, 200, 0, 0))]
    assert stat.cost(PriceBook()) is None


def test_cost_uses_supplied_rates(journey):
    prices = PriceBook({"claude-test-1": ModelPrice(input=1.0, output=2.0, cache_read=0.1)})
    stat = JourneyStats("demo", "claude:test")
    stat.runs = [_result(journey, PASSED, tokens=(1_000_000, 1_000_000, 0, 1_000_000))]
    assert stat.cost(prices) == pytest.approx(3.1)


def test_price_book_from_file(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text(json.dumps({"m": {"input": 3.0, "output": 15.0}}))
    book = PriceBook.load(str(path))
    assert book.for_model("m").output == 15.0
    assert book.for_model("vendor:m").input == 3.0


# -- machine-readable output -------------------------------------------


def test_results_document_is_versioned_and_complete(journey):
    stat = JourneyStats("demo", "claude:test")
    stat.runs = [_result(journey, PASSED), _result(journey, DOCS_GAP, attempt=2)]
    doc = suite_document(SuiteResult(stats=[stat], repeat=2, backend="seatbelt"))
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["journeys"][0]["pass_rate"] == 0.5
    assert doc["journeys"][0]["models_reported"] == ["claude-test-1"]
    assert len(doc["journeys"][0]["runs"]) == 2
    assert doc["journeys"][0]["runs"][0]["enforced"] is True
    json.dumps(doc)  # must be serializable


def test_junit_separates_failures_from_errors(journey):
    stat = JourneyStats("demo", "claude:test")
    stat.runs = [
        _result(journey, DOCS_GAP),
        _result(journey, INFRA_ERROR, attempt=2),
    ]
    root = ET.fromstring(junit_xml(SuiteResult(stats=[stat], repeat=2)))
    # A docs gap is a test failure; a rate limit is an error, not a verdict.
    assert root.get("failures") == "1"
    assert root.get("errors") == "1"


def test_policy_blocked_install_is_our_bug_not_a_docs_gap():
    """The proxy refusing a documented command means the journey is misdeclared."""
    trace = Trace()
    trace.add("egress_blocked", host="pypi.org", reason="docs_host_requires_read_docs")
    outcome = AgentOutcome("command_failed", 1, "replay step 1 failed: pip install x")
    assert classify(outcome, ScoreResult(False, 1, ""), trace) == HARNESS_ERROR


def test_unlisted_host_block_on_failure_is_a_harness_error():
    trace = Trace()
    trace.add("egress_blocked", host="cdn.example", reason="not_allowlisted")
    outcome = AgentOutcome("completed", 6)
    assert classify(outcome, ScoreResult(False, 1, ""), trace) == HARNESS_ERROR


def test_suite_records_the_resolved_backend(journey, monkeypatch):
    """'auto' in a published result says nothing about what was enforced."""
    import quickstarted.transport as transport

    monkeypatch.setattr(
        transport,
        "http_get",
        lambda url, timeout=30, method="GET": transport.HttpResponse(
            200, "text/plain", "docs"
        ),
    )
    from quickstarted.agents.replay import ReplayAgent
    from quickstarted.exec import resolve_backend

    suite = run_suite([journey], lambda: ReplayAgent(), backend="auto")
    assert suite.backend == resolve_backend("auto")
    assert suite.backend != "auto"
