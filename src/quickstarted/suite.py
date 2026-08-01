"""Running many tasks many times, and reporting rates rather than verdicts.

A single agent run is one sample. The same docs and the same
model can pass at 10:00 and fail at 10:05, so a benchmark that publishes one
run per project is publishing noise with a confident face on it.

Two rules follow, and both are enforced here rather than left to the reader:

* A pass *rate* is computed over evidential runs only. Runs that died on a
  429, exhausted their budget, or hit a harness bug are excluded from the
  numerator and the denominator alike, and reported separately, because they
  are not evidence about the documentation either way.
* Nothing is aggregated across models. Pass rates for different models are
  different measurements that happen to share a task.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from .agents.base import Agent
from .exec import resolve_backend
from .pricing import PriceBook
from .run import EVIDENTIAL, PASSED, RunResult, run_task
from .task import Task


@dataclass
class TaskStats:
    task: str
    agent: str
    runs: list[RunResult] = field(default_factory=list)

    @property
    def attempts(self) -> int:
        return len(self.runs)

    @property
    def evidential(self) -> list[RunResult]:
        return [r for r in self.runs if r.classification in EVIDENTIAL]

    @property
    def passes(self) -> int:
        return len([r for r in self.runs if r.classification == PASSED])

    @property
    def pass_rate(self) -> float | None:
        """None when no run produced evidence: an honest 'we do not know'."""
        usable = self.evidential
        if not usable:
            return None
        return self.passes / len(usable)

    @property
    def discarded(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for run in self.runs:
            if run.classification not in EVIDENTIAL:
                counts[run.classification] = counts.get(run.classification, 0) + 1
        return counts

    @property
    def models_seen(self) -> list[str]:
        return sorted({r.model_reported for r in self.runs if r.model_reported})

    def tokens(self) -> dict[str, int]:
        totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        for run in self.runs:
            totals["input"] += run.outcome.input_tokens
            totals["output"] += run.outcome.output_tokens
            totals["cache_write"] += run.outcome.cache_write_tokens
            totals["cache_read"] += run.outcome.cache_read_tokens
        return totals

    def cost(self, prices: PriceBook) -> float | None:
        if not prices:
            return None
        total = 0.0
        seen = False
        for run in self.runs:
            model = run.model_reported or run.agent_name
            estimate = prices.estimate(model, run.outcome)
            if estimate is not None:
                total += estimate
                seen = True
        return total if seen else None

    @property
    def suspect_pages(self) -> dict[str, int]:
        """Which docs page failing runs were last on, most common first."""
        counts: dict[str, int] = {}
        for run in self.runs:
            if run.classification == PASSED:
                continue
            page = run.suspect_page
            if page:
                counts[page] = counts.get(page, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


@dataclass
class SuiteResult:
    stats: list[TaskStats] = field(default_factory=list)
    duration: float = 0.0
    repeat: int = 1
    backend: str = ""

    @property
    def runs(self) -> list[RunResult]:
        return [r for s in self.stats for r in s.runs]

    @property
    def all_passed(self) -> bool:
        """CI gate: every task passed every attempt that produced evidence."""
        for stat in self.stats:
            if stat.pass_rate is None or stat.pass_rate < 1.0:
                return False
        return bool(self.stats)

    def tokens(self) -> dict[str, int]:
        totals = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
        for stat in self.stats:
            for key, value in stat.tokens().items():
                totals[key] += value
        return totals

    def cost(self, prices: PriceBook) -> float | None:
        if not prices:
            return None
        estimates = [s.cost(prices) for s in self.stats]
        real = [e for e in estimates if e is not None]
        return sum(real) if real else None


def run_suite(
    tasks: Sequence[Task],
    agent_factory: Callable[[], Agent],
    repeat: int = 1,
    workers: int = 1,
    backend: str = "auto",
    keep_sandbox: bool = False,
    http_get=None,
    image: str | None = None,
    docs=None,
    probe_affordances: bool = False,
    on_result: Callable[[RunResult], None] | None = None,
    on_event: Callable[[str, int, object], None] | None = None,
) -> SuiteResult:
    start = time.monotonic()
    jobs = [
        (task, attempt)
        for task in tasks
        for attempt in range(1, repeat + 1)
    ]

    def execute(job) -> RunResult:
        task, attempt = job
        return run_task(
            task,
            agent_factory(),
            keep_sandbox=keep_sandbox,
            http_get=http_get,
            backend=backend,
            image=image,
            attempt=attempt,
            docs=docs,
            probe_affordances=probe_affordances and attempt == 1,
            on_event=(
                (lambda event: on_event(task.name, attempt, event))
                if on_event
                else None
            ),
        )

    results: list[RunResult] = []
    if workers > 1 and len(jobs) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for result in pool.map(execute, jobs):
                results.append(result)
                if on_result:
                    on_result(result)
    else:
        for job in jobs:
            result = execute(job)
            results.append(result)
            if on_result:
                on_result(result)

    by_task: dict[str, TaskStats] = {}
    order: list[str] = []
    for result in results:
        key = f"{result.task.name} {result.agent_name}"
        if key not in by_task:
            by_task[key] = TaskStats(result.task.name, result.agent_name)
            order.append(key)
        by_task[key].runs.append(result)

    return SuiteResult(
        stats=[by_task[k] for k in order],
        duration=time.monotonic() - start,
        repeat=repeat,
        # The resolved backend. "auto" in a published result
        # tells a reader nothing about what was enforced.
        backend=resolve_backend(backend),
    )
