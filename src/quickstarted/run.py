"""Run orchestration: setup, agent, deterministic scoring, classification.

Pass/fail is decided by the task's success script exit code, run by the
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
from .net.proxy import EgressProxy
from .task import Task
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
    task: Task
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
    #: Container image actually used, empty for backends that have none. A pass
    #: rate is not comparable across base images, so it goes in the record.
    image: str = ""

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
    # Documented commands that died because our own policy refused their traffic
    # say the task's network allowlist is wrong. The docs are not implicated.
    if blocked and reason == "command_failed":
        return HARNESS_ERROR
    if any(e.data.get("reason") == "not_allowlisted" for e in blocked):
        return HARNESS_ERROR
    return DOCS_GAP


def run_task(
    task: Task,
    agent: Agent,
    keep_sandbox: bool = False,
    http_get=None,
    backend: str = "auto",
    image: str | None = None,
    attempt: int = 1,
    docs: DocsClient | None = None,
    probe_affordances: bool = False,
    on_event=None,
) -> RunResult:
    backend = resolve_backend(backend)
    docs = docs or DocsClient()
    trace = Trace(listener=on_event)
    proxy: EgressProxy | None = None
    start = time.monotonic()

    if needs_host_proxy(backend):
        proxy = EgressProxy(
            network_allow=task.network_allow,
            docs_hosts=task.docs_allow,
            explicit_allow=task.network_explicit,
            trace=trace,
        )
        proxy.start()

    try:
        executor = make_executor(
            backend,
            keep=keep_sandbox,
            proxy_url=proxy.url if proxy else None,
            network_allow=task.network_allow,
            docs_hosts=task.docs_allow,
            # The task wins: one suite mixes a Python quickstart and a Node one,
            # so a single --image cannot serve both.
            image=task.image or image,
            trace=trace,
        )
    except ExecutorError as exc:
        if proxy:
            proxy.stop()
        trace.add("run_end", stop_reason="error", passed=False)
        return RunResult(
            task, agent.name, AgentOutcome("error", 0, str(exc)), None, trace,
            time.monotonic() - start, "", backend, False, HARNESS_ERROR, attempt,
        )

    trace.add(
        "run_start",
        task=task.name,
        agent=agent.name,
        backend=backend,
        enforced=executor.enforced,
        image=getattr(executor, "image", ""),
        attempt=attempt,
        affordance_policy=docs.affordances,
    )

    if probe_affordances:
        # Recorded as context for whoever reads a failure, and as the variable
        # for an ablation. Never part of the score.
        trace.add(
            "affordances", entrypoint=task.docs_entrypoint,
            found=affordance_summary(docs.probe(task.docs_entrypoint)),
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
            task, agent.name, outcome, score, trace, time.monotonic() - start,
            str(executor.root), backend, executor.enforced, classification, attempt,
            getattr(agent, "model_reported", ""), docs.affordances,
            getattr(executor, "image", ""),
        )

    try:
        for command in task.setup:
            result = executor.run(
                command,
                timeout=task.budgets.max_command_seconds,
                max_output_chars=task.budgets.max_output_chars,
            )
            trace.add(
                "setup", command=command, exit_code=result.exit_code,
                output=result.output,
            )
            if result.exit_code != 0:
                return finish(
                    AgentOutcome("error", 0, f"setup command failed: {command}"), None
                )

        toolbelt = Toolbelt(task, executor, trace, docs=docs, http_get=http_get)
        deadline = time.monotonic() + task.budgets.max_seconds
        outcome = agent.run(task, toolbelt, deadline)

        check = executor.run(
            task.check_script,
            timeout=task.budgets.max_command_seconds,
            max_output_chars=task.budgets.max_output_chars,
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
