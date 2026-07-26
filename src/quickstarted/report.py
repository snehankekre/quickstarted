"""Human-readable reporting: console summaries and markdown.

Reports name the classification alongside PASS/FAIL, because "we could not
reach PyPI" and "your quickstart is missing a step" require different people
to do different things.
"""

from __future__ import annotations

from .pricing import PriceBook
from .run import DOCS_GAP, PASSED, RunResult
from .suite import SuiteResult, TaskStats

_LABELS = {
    PASSED: "PASS",
    DOCS_GAP: "FAIL",
    "budget_exhausted": "INCONCLUSIVE",
    "infra_error": "INCONCLUSIVE",
    "harness_error": "INCONCLUSIVE",
    "agent_refusal": "INCONCLUSIVE",
}


def label(run: RunResult) -> str:
    return _LABELS.get(run.classification, "INCONCLUSIVE")


def _token_line(outcome) -> str:
    """Tokens for one run, cache traffic included so the number reflects cost."""
    parts = []
    if outcome.input_tokens or outcome.output_tokens:
        parts.append(f"{outcome.input_tokens} in / {outcome.output_tokens} out")
    if outcome.cache_write_tokens or outcome.cache_read_tokens:
        parts.append(
            f"cache {outcome.cache_write_tokens} written / "
            f"{outcome.cache_read_tokens} read"
        )
    return ", ".join(parts)


def console_summary(result: RunResult) -> str:
    lines = [
        f"[{label(result)}] {result.task.name} ({result.agent_name})",
        f"  classification: {result.classification}",
        f"  stop reason: {result.outcome.stop_reason}"
        + (f" ({result.outcome.detail})" if result.outcome.detail else ""),
        f"  turns: {result.outcome.turns}, duration: {result.duration:.1f}s",
        f"  backend: {result.backend}"
        + (f" ({result.image})" if result.image else "")
        + ("" if result.enforced else "  [UNENFORCED: policy is advisory here]"),
    ]
    tokens = _token_line(result.outcome)
    if tokens:
        lines.append(f"  tokens: {tokens}")
    fetched = result.trace.fetched_urls()
    if fetched:
        lines.append(f"  docs pages read: {len(fetched)}")
    if result.bypass_attempts:
        lines.append(
            f"  docs fetched outside read_docs: {result.bypass_attempts} blocked attempt(s)"
        )
    if not result.passed:
        if result.score is not None:
            check_line = (result.score.output or "").strip().splitlines()
            lines.append(
                f"  success check exit code: {result.score.exit_code}"
                + (f" ({check_line[-1]})" if check_line else "")
            )
        if result.classification == DOCS_GAP and result.suspect_page:
            lines.append(f"  last docs page read before failure: {result.suspect_page}")
    return "\n".join(lines)


def suite_summary(suite: SuiteResult, prices: PriceBook | None = None) -> str:
    prices = prices or PriceBook()
    lines = ["", "=" * 62, f"Suite: {len(suite.stats)} task(s), repeat={suite.repeat}"]
    for stat in suite.stats:
        rate = stat.pass_rate
        shown = "no evidence" if rate is None else f"{rate:.0%}"
        lines.append(
            f"  {stat.task} ({stat.agent}): pass rate {shown} "
            f"[{stat.passes}/{len(stat.evidential)} evidential of {stat.attempts} run(s)]"
        )
        if stat.discarded:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(stat.discarded.items()))
            lines.append(f"      discarded: {detail}")
        if len(stat.models_seen) > 1:
            lines.append(
                f"      WARNING: more than one model served this task "
                f"({', '.join(stat.models_seen)}); do not compare these runs"
            )
        for page, count in list(stat.suspect_pages.items())[:3]:
            lines.append(f"      failed after: {page} ({count}x)")
    totals = suite.tokens()
    lines.append(
        f"  tokens: {totals['input']} in / {totals['output']} out, "
        f"cache {totals['cache_write']} written / {totals['cache_read']} read"
    )
    cost = suite.cost(prices)
    if cost is not None:
        lines.append(f"  estimated cost: ${cost:.4f}")
    lines.append(f"  wall clock: {suite.duration:.1f}s")
    lines.append("=" * 62)
    return "\n".join(lines)


def markdown_report(result: RunResult) -> str:
    out = [
        f"# quickstarted: {result.task.name}",
        "",
        f"**Result: {label(result)}** (`{result.classification}`, agent: "
        f"`{result.agent_name}`)",
        "",
        f"- Goal: {result.task.goal}",
        f"- Stop reason: {result.outcome.stop_reason}"
        + (f" ({result.outcome.detail})" if result.outcome.detail else ""),
        f"- Turns: {result.outcome.turns}",
        f"- Duration: {result.duration:.1f}s",
        f"- Backend: `{result.backend}` "
        + ("(enforced)" if result.enforced else "(**unenforced**)"),
    ]
    if result.model_reported:
        out.append(f"- Model served: `{result.model_reported}`")
    tokens = _token_line(result.outcome)
    if tokens:
        out.append(f"- Tokens: {tokens}")
    out.append("")
    if not result.evidential:
        out += [
            "## This run is not evidence about the documentation",
            "",
            f"It was classified `{result.classification}`, which means the run "
            "failed for a reason unrelated to whether the docs are usable. It "
            "is excluded from pass rates rather than counted as a failure.",
            "",
        ]
    fetched = result.trace.fetched_urls()
    if fetched:
        out += ["## Docs pages the agent read", ""]
        out += [f"1. {url}" for url in fetched]
        out.append("")
    if result.bypass_attempts:
        out += [
            "## Blocked shell access to documentation",
            "",
            f"The agent tried {result.bypass_attempts} time(s) to fetch docs "
            "through the shell instead of the recorded tool. The proxy refused, "
            "so the page list above is complete.",
            "",
        ]
    if result.score is not None:
        out += [
            "## Success check",
            "",
            f"Exit code: {result.score.exit_code}",
            "",
            "```",
            (result.score.output or "").strip(),
            "```",
            "",
        ]
    if result.classification == DOCS_GAP and result.suspect_page:
        out += [
            "## Where to look first",
            "",
            f"The last documentation page the agent read before failing was "
            f"<{result.suspect_page}>. That page (or a gap right after it) is "
            f"the first suspect.",
            "",
        ]
    return "\n".join(out)


def markdown_suite_report(suite: SuiteResult, prices: PriceBook | None = None) -> str:
    prices = prices or PriceBook()
    out = [
        "# quickstarted suite",
        "",
        f"- Tasks: {len(suite.stats)}",
        f"- Attempts per task: {suite.repeat}",
        f"- Backend: `{suite.backend}`",
        f"- Duration: {suite.duration:.1f}s",
        "",
        "| Task | Agent | Pass rate | Evidential | Discarded |",
        "| --- | --- | --- | --- | --- |",
    ]
    for stat in suite.stats:
        rate = stat.pass_rate
        shown = "n/a" if rate is None else f"{rate:.0%}"
        discarded = (
            ", ".join(f"{k}={v}" for k, v in sorted(stat.discarded.items())) or "none"
        )
        out.append(
            f"| {stat.task} | `{stat.agent}` | {shown} | "
            f"{stat.passes}/{len(stat.evidential)} | {discarded} |"
        )
    out.append("")
    cost = suite.cost(prices)
    if cost is not None:
        out.append(f"Estimated cost: ${cost:.4f}")
        out.append("")
    return "\n".join(out)


def stats_line(stat: TaskStats) -> str:
    rate = stat.pass_rate
    return f"{stat.task}: {'n/a' if rate is None else f'{rate:.0%}'}"
