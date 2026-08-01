"""Comparing two runs, and the honesty about sample size that makes it useful."""

import json

import pytest

from quickstarted.diff import (
    ALPHA,
    DiffError,
    compare,
    fisher_exact_two_sided,
    format_diff,
    load_results,
    smallest_reachable_p,
)


@pytest.mark.parametrize(
    "table, expected",
    [
        ((3, 1, 1, 3), 0.4857),
        ((1, 9, 11, 3), 0.0027),
        ((5, 0, 0, 5), 0.0079),
        ((2, 3, 3, 2), 1.0),
        ((10, 0, 0, 10), 1.083e-5),
    ],
)
def test_fisher_matches_published_values(table, expected):
    """Checked against R's fisher.test; a wrong p-value here is a wrong claim."""
    assert fisher_exact_two_sided(*table) == pytest.approx(expected, rel=0.01, abs=1e-4)


def test_a_symmetric_table_is_exactly_one():
    """Float tolerance in the tail sum: the mirrored table must not drop out."""
    assert fisher_exact_two_sided(2, 3, 3, 2) == 1.0


def test_an_empty_margin_is_not_a_signal():
    assert fisher_exact_two_sided(0, 0, 3, 2) == 1.0


@pytest.mark.parametrize(
    "n, powered",
    [(1, False), (2, False), (3, False), (4, True), (5, True), (10, True)],
)
def test_three_runs_a_side_can_never_reach_significance(n, powered):
    """The useful half: some experiments cannot answer the question at all."""
    assert (smallest_reachable_p(n, n) < ALPHA) is powered


def _doc(task="t", passes=3, evidential=5, **extra):
    entry = {
        "task": task,
        "agent": "claude",
        "passes": passes,
        "evidential_runs": evidential,
        "pass_rate": passes / evidential if evidential else None,
        "discarded": {},
        "models_reported": [],
        "suspect_pages": {},
    }
    entry.update(extra)
    return {"schema_version": "2.0", "tasks": [entry], "totals": {}}


def test_a_one_run_improvement_is_reported_as_noise():
    delta = compare(_doc(passes=3), _doc(passes=4))
    task = delta.tasks[0]
    assert task.direction == "improved"
    assert not task.significant
    assert "inside the noise" in task.verdict


def test_a_clear_regression_is_reported_as_one():
    delta = compare(_doc(passes=10, evidential=10), _doc(passes=0, evidential=10))
    assert delta.regressions
    assert delta.tasks[0].verdict.startswith("regressed")


def test_an_underpowered_comparison_says_so():
    delta = compare(_doc(passes=1, evidential=3), _doc(passes=3, evidential=3))
    verdict = delta.tasks[0].verdict
    assert "could have cleared" in verdict
    assert delta.tasks[0].underpowered


def test_two_models_are_not_compared():
    """Pass rates for different models are different measurements."""
    before = _doc(passes=5, evidential=5, models_reported=["claude-opus-5"])
    after = _doc(passes=1, evidential=5, models_reported=["gpt-5.2"])
    task = compare(before, after).tasks[0]
    assert not task.comparable
    assert not task.significant
    assert "different model" in task.verdict


def test_suspect_pages_that_appeared_and_cleared():
    before = _doc(passes=2, suspect_pages={"https://a/": 3})
    after = _doc(passes=2, suspect_pages={"https://b/": 3})
    task = compare(before, after).tasks[0]
    assert task.pages_cleared == ("https://a/",)
    assert task.pages_appeared == ("https://b/",)
    assert "no longer failing after: https://a/" in format_diff(compare(before, after))


def test_tasks_added_and_removed_are_named():
    delta = compare(_doc(task="old"), _doc(task="new"))
    assert delta.added == ("new",)
    assert delta.removed == ("old",)
    assert not delta.tasks


def test_a_foreign_schema_is_refused(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"schema_version": "1.0", "tasks": []}))
    with pytest.raises(DiffError, match="cannot be compared"):
        load_results(path)


def test_a_file_that_is_not_results_is_refused(tmp_path):
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"hello": "world"}))
    with pytest.raises(DiffError, match="not a quickstarted results document"):
        load_results(path)
