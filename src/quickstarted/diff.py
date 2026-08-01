"""Comparing two result documents, and saying when the difference means nothing.

The question a docs maintainer actually has is "I edited the page, did it help?"
A pass rate that moved from 3/5 to 4/5 answers that question with a number and
no honesty: at five attempts, almost every movement is noise, and a tool that
prints `+20 points` without saying so is inviting somebody to publish it.

So every comparison here carries a two-sided Fisher exact test on the 2x2 table
of passes and failures. Fisher rather than a normal approximation because the
samples are tiny, and exact rather than approximate because it costs nothing:
the arithmetic is `math.comb` and there is no new dependency.

The more useful half is the second one. When no possible outcome at these
sample sizes could have reached significance, the report says that instead of
reporting a result, because the honest answer is that the run was too small to
answer the question rather than that the docs did not change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from math import comb
from pathlib import Path

#: Conventional, and stated in the output rather than assumed.
ALPHA = 0.05


class DiffError(ValueError):
    """Raised when a results document cannot be compared."""


def _table_probability(a: int, b: int, c: int, d: int) -> float:
    """Hypergeometric probability of one 2x2 table with these margins."""
    return comb(a + b, a) * comb(c + d, c) / comb(a + b + c + d, a + c)


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """p-value for the table [[a, b], [c, d]] = [[pass, fail] before, after].

    Sums the probability of every table with the same margins that is at least
    as extreme as the one observed.
    """
    if min(a, b, c, d) < 0:
        raise ValueError("counts must not be negative")
    if (a + b) == 0 or (c + d) == 0 or (a + c) == 0 or (b + d) == 0:
        # A margin of zero leaves only one possible table, so nothing is
        # distinguishable from anything.
        return 1.0
    observed = _table_probability(a, b, c, d)
    row1, row2, col1 = a + b, c + d, a + c
    total = 0.0
    for x in range(max(0, col1 - row2), min(row1, col1) + 1):
        probability = _table_probability(x, row1 - x, col1 - x, row2 - (col1 - x))
        # The float tolerance matters: the mirrored table of a symmetric
        # comparison differs from the observed one only by rounding, and
        # dropping it would halve a p-value that should be 1.0.
        if probability <= observed * (1 + 1e-9):
            total += probability
    # When every table qualifies the true value is exactly 1: the probabilities
    # sum to one by construction, and summing them in floating point does not.
    return 1.0 if total > 1 - 1e-9 else total


def smallest_reachable_p(n_before: int, n_after: int) -> float:
    """The best p-value these sample sizes could ever produce.

    Maximal separation is the most extreme table available, so if that cannot
    clear the threshold then no outcome of this experiment could have, and the
    experiment was too small before it ran.
    """
    if n_before <= 0 or n_after <= 0:
        return 1.0
    return min(
        fisher_exact_two_sided(0, n_before, n_after, 0),
        fisher_exact_two_sided(n_before, 0, 0, n_after),
    )


@dataclass(frozen=True)
class TaskDelta:
    task: str
    passes_before: int
    evidential_before: int
    passes_after: int
    evidential_after: int
    p_value: float
    smallest_reachable: float
    models_before: tuple[str, ...] = ()
    models_after: tuple[str, ...] = ()
    pages_appeared: tuple[str, ...] = ()
    pages_cleared: tuple[str, ...] = ()
    discarded_before: dict = field(default_factory=dict)
    discarded_after: dict = field(default_factory=dict)

    @property
    def rate_before(self) -> float | None:
        if not self.evidential_before:
            return None
        return self.passes_before / self.evidential_before

    @property
    def rate_after(self) -> float | None:
        if not self.evidential_after:
            return None
        return self.passes_after / self.evidential_after

    @property
    def comparable(self) -> bool:
        """Two models are two measurements that happen to share a task."""
        return not (
            self.models_before and self.models_after
            and set(self.models_before) != set(self.models_after)
        )

    @property
    def significant(self) -> bool:
        return self.comparable and self.p_value < ALPHA

    @property
    def underpowered(self) -> bool:
        """No outcome at these sample sizes could have cleared the bar."""
        return self.smallest_reachable >= ALPHA

    @property
    def direction(self) -> str:
        before, after = self.rate_before, self.rate_after
        if before is None or after is None:
            return "unknown"
        if after > before:
            return "improved"
        if after < before:
            return "regressed"
        return "unchanged"

    @property
    def verdict(self) -> str:
        if not self.comparable:
            return "not comparable: a different model served these runs"
        if self.rate_before is None or self.rate_after is None:
            return "no evidence on one side"
        if self.significant:
            return f"{self.direction}, p={self.p_value:.3f}"
        if self.underpowered:
            return (
                f"inside the noise, and no result at {self.evidential_before} vs "
                f"{self.evidential_after} runs could have cleared p<{ALPHA} "
                f"(best possible p={self.smallest_reachable:.3f})"
            )
        return f"inside the noise, p={self.p_value:.3f}"


@dataclass(frozen=True)
class SuiteDelta:
    tasks: tuple[TaskDelta, ...] = ()
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    cost_before: float | None = None
    cost_after: float | None = None

    @property
    def regressions(self) -> tuple[TaskDelta, ...]:
        return tuple(d for d in self.tasks if d.significant and d.direction == "regressed")

    @property
    def improvements(self) -> tuple[TaskDelta, ...]:
        return tuple(d for d in self.tasks if d.significant and d.direction == "improved")


def load_results(path: str | Path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise DiffError(f"{path}: no such file")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DiffError(f"{path}: not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or "tasks" not in data:
        raise DiffError(f"{path}: not a quickstarted results document")
    version = str(data.get("schema_version", "")).split(".")[0]
    if version and version != "2":
        raise DiffError(
            f"{path}: results schema {data.get('schema_version')} cannot be "
            f"compared by this version, which reads 2.x"
        )
    return data


def _by_task(document: dict) -> dict[str, dict]:
    return {entry["task"]: entry for entry in document.get("tasks", [])}


def compare(before: dict, after: dict) -> SuiteDelta:
    old, new = _by_task(before), _by_task(after)
    deltas = []
    for name in [n for n in new if n in old]:
        a, b = old[name], new[name]
        passes_before = int(a.get("passes", 0))
        n_before = int(a.get("evidential_runs", 0))
        passes_after = int(b.get("passes", 0))
        n_after = int(b.get("evidential_runs", 0))
        p_value = fisher_exact_two_sided(
            passes_before, n_before - passes_before,
            passes_after, n_after - passes_after,
        )
        pages_before = set(a.get("suspect_pages") or {})
        pages_after = set(b.get("suspect_pages") or {})
        deltas.append(
            TaskDelta(
                task=name,
                passes_before=passes_before,
                evidential_before=n_before,
                passes_after=passes_after,
                evidential_after=n_after,
                p_value=p_value,
                smallest_reachable=smallest_reachable_p(n_before, n_after),
                models_before=tuple(a.get("models_reported") or ()),
                models_after=tuple(b.get("models_reported") or ()),
                pages_appeared=tuple(sorted(pages_after - pages_before)),
                pages_cleared=tuple(sorted(pages_before - pages_after)),
                discarded_before=a.get("discarded") or {},
                discarded_after=b.get("discarded") or {},
            )
        )
    return SuiteDelta(
        tasks=tuple(deltas),
        added=tuple(sorted(set(new) - set(old))),
        removed=tuple(sorted(set(old) - set(new))),
        cost_before=(before.get("totals") or {}).get("estimated_cost_usd"),
        cost_after=(after.get("totals") or {}).get("estimated_cost_usd"),
    )


def _rate(passes: int, total: int) -> str:
    if not total:
        return "no evidence"
    return f"{passes}/{total} ({passes / total:.0%})"


def format_diff(delta: SuiteDelta) -> str:
    lines = ["", "=" * 68, "quickstarted diff", "=" * 68]
    if not delta.tasks:
        lines.append("  no task appears in both documents")
    for task in delta.tasks:
        lines.append(f"  {task.task}")
        lines.append(
            f"      {_rate(task.passes_before, task.evidential_before)}"
            f"  ->  {_rate(task.passes_after, task.evidential_after)}"
        )
        lines.append(f"      {task.verdict}")
        if not task.comparable:
            lines.append(
                f"      before: {', '.join(task.models_before)}; "
                f"after: {', '.join(task.models_after)}"
            )
        for page in task.pages_cleared:
            lines.append(f"      no longer failing after: {page}")
        for page in task.pages_appeared:
            lines.append(f"      newly failing after: {page}")
        if task.discarded_before != task.discarded_after:
            lines.append(
                f"      discarded: {task.discarded_before or 'none'} -> "
                f"{task.discarded_after or 'none'}"
            )
    for name in delta.added:
        lines.append(f"  {name}: new, no earlier run to compare")
    for name in delta.removed:
        lines.append(f"  {name}: gone, present only in the earlier run")
    if delta.cost_before is not None and delta.cost_after is not None:
        lines.append(f"  cost: ${delta.cost_before:.4f} -> ${delta.cost_after:.4f}")
    lines.append("=" * 68)
    return "\n".join(lines)
