"""Run orchestration: setup, agent, deterministic scoring, classification.

Pass/fail is decided by the journey's success script exit code, run by the
harness after the agent stops. The agent's own opinion of whether it finished
is recorded but never trusted for scoring.

A verdict alone is not enough to publish, though. "FAIL" has to distinguish a
documentation gap from a network flake, an exhausted budget, or a bug in this
harness, because a benchmark that reports infrastructure noise as a docs
failure is worse than no benchmark. That is what `Classification` is for.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .agents.base import Agent, AgentOutcome, Toolbelt
from .docs import DocsClient, affordance_summary
from .exec import ExecutorError, make_executor, needs_host_proxy, resolve_backend
from .journey import Journey
from .net.proxy import EgressProxy
from .trace import Trace

#: Only PASS and DOCS_GAP are statements about the documentation. Everything
#: else says the run did not produce evidence, and belongs outside the
#: numerator and the denominator of a pass rate.
PASSED = "passed"
DOCS_GAP = "docs_gap"
BUDGET_EXHAUSTED = "budget_exhausted"
INFRA_ERROR = "infra_error"
HARNESS_ERROR = "harness_error"
AGENT_REFUSAL = "agent_refusal"

EVIDENTIAL = (PASSED, DOCS_GAP)

_INFRA_MARKERS = (
    "connection error",
    "api error 429",
    "api error 500",
    "api error 502",
    "api error 503",
    "api error 529",
    "overloaded",
    "rate limit",
)


@dataclass(frozen=True)
class ScoreResult:
    passed: bool
    exit_code: int
    output: str


@dataclass
class RunResult:
    journey: Journey
    agent_name: str
    outcome: AgentOutcome
    score: ScoreResult | None
    trace: Trace
    duration: float
    sandbox_path: str
    backend: str = "local"
    enforced: bool = False
    classification: str = HARNESS_ERROR
    attempt: int = 1
    model_reported: str = ""
    affordance_policy: str = "all"

    @property
    def passed(self) -> bool:
        return bool(self.score and self.score.passed)

    @property
    def evidential(self) -> bool:
        """True when this run says something about the documentation."""
        return self.classification in EVIDENTIAL

    @property
    def suspect_page(self) -> str | None:
        if self.passed:
            return None
        return self.trace.last_fetch_before_failure()

    @property
    def bypass_attempts(self) -> int:
        return len(
            [
                e
                for e in self.trace.of_type("egress_blocked")
                if e.data.get("reason") == "docs_host_requires_read_docs"
            ]
        )


def classify(outcome: AgentOutcome, score: ScoreResult | None, trace: Trace) -> str:
    if score and score.passed:
        return PASSED
    reason = outcome.stop_reason
    detail = (outcome.detail or "").lower()
    if reason == "refusal":
        return AGENT_REFUSAL
    if reason == "error":
        if any(marker in detail for marker in _INFRA_MARKERS):
            return INFRA_ERROR
        return HARNESS_ERROR
    if reason in ("max_turns", "timeout", "token_budget"):
        return BUDGET_EXHAUSTED
    # A run whose shell could not reach a package registry has not tested the
    # documentation; it has tested the network.
    if trace.of_type("egress_error"):
        return INFRA_ERROR
    blocked = trace.of_type("egress_blocked")
    # Documented commands that died because our own policy refused their
    # traffic say the journey's network allowlist is wrong, not the docs.
    if blocked and reason == "command_failed":
        return HARNESS_ERROR
    if any(e.data.get("reason") == "not_allowlisted" for e in blocked):
        return HARNESS_ERROR
    return DOCS_GAP


def run_journey(
    journey: Journey,
    agent: Agent,
    keep_sandbox: bool = False,
    http_get=None,
    backend: str = "auto",
    image: str | None = None,
    attempt: int = 1,
    docs: DocsClient | None = None,
    probe_affordances: bool = False,
) -> RunResult:
    backend = resolve_backend(backend)
    docs = docs or DocsClient()
    trace = Trace()
    proxy: EgressProxy | None = None
    start = time.monotonic()

    if needs_host_proxy(backend):
        proxy = EgressProxy(
            network_allow=journey.network_allow,
            docs_hosts=journey.docs_allow,
            explicit_allow=journey.network_explicit,
            trace=trace,
        )
        proxy.start()

    try:
        executor = make_executor(
            backend,
            keep=keep_sandbox,
            proxy_url=proxy.url if proxy else None,
            network_allow=journey.network_allow,
            docs_hosts=journey.docs_allow,
            image=image,
            trace=trace,
        )
    except ExecutorError as exc:
        if proxy:
            proxy.stop()
        trace.add("run_end", stop_reason="error", passed=False)
        return RunResult(
            journey, agent.name, AgentOutcome("error", 0, str(exc)), None, trace,
            time.monotonic() - start, "", backend, False, HARNESS_ERROR, attempt,
        )

    trace.add(
        "run_start",
        journey=journey.name,
        agent=agent.name,
        backend=backend,
        enforced=executor.enforced,
        attempt=attempt,
        affordance_policy=docs.affordances,
    )

    if probe_affordances:
        # Recorded as context for whoever reads a failure, and as the variable
        # for an ablation. Never part of the score.
        trace.add(
            "affordances", entrypoint=journey.docs_entrypoint,
            found=affordance_summary(docs.probe(journey.docs_entrypoint)),
        )

    def finish(outcome: AgentOutcome, score: ScoreResult | None) -> RunResult:
        classification = classify(outcome, score, trace)
        trace.add(
            "run_end",
            stop_reason=outcome.stop_reason,
            passed=bool(score and score.passed),
            classification=classification,
        )
        return RunResult(
            journey, agent.name, outcome, score, trace, time.monotonic() - start,
            str(executor.root), backend, executor.enforced, classification, attempt,
            getattr(agent, "model_reported", ""), docs.affordances,
        )

    try:
        for command in journey.setup:
            result = executor.run(
                command,
                timeout=journey.budgets.max_command_seconds,
                max_output_chars=journey.budgets.max_output_chars,
            )
            trace.add(
                "setup", command=command, exit_code=result.exit_code,
                output=result.output,
            )
            if result.exit_code != 0:
                return finish(
                    AgentOutcome("error", 0, f"setup command failed: {command}"), None
                )

        toolbelt = Toolbelt(journey, executor, trace, docs=docs, http_get=http_get)
        deadline = time.monotonic() + journey.budgets.max_seconds
        outcome = agent.run(journey, toolbelt, deadline)

        check = executor.run(
            journey.success_script,
            timeout=journey.budgets.max_command_seconds,
            max_output_chars=journey.budgets.max_output_chars,
        )
        score = ScoreResult(
            passed=check.exit_code == 0,
            exit_code=check.exit_code,
            output=check.output,
        )
        trace.add(
            "success_check", exit_code=check.exit_code, passed=score.passed,
            output=check.output,
        )
        return finish(outcome, score)
    finally:
        executor.cleanup()
        if proxy:
            proxy.stop()
