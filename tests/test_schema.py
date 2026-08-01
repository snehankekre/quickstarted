"""The published schema has to match the code, and describe the real tasks."""

import json
import pathlib

import pytest
import yaml

from quickstarted.schema import SCHEMA_LINE, TASK_SCHEMA

ROOT = pathlib.Path(__file__).parent.parent
PUBLISHED = ROOT / "docs" / "task-schema.json"


def test_published_schema_matches_the_code():
    """Editors fetch the published copy, so drift would mislead silently."""
    assert json.loads(PUBLISHED.read_text()) == TASK_SCHEMA, (
        "docs/task-schema.json is stale; regenerate with `quickstarted schema`"
    )


def test_budget_defaults_come_from_the_dataclass():
    """The schema advertised max_seconds: 900 for a release after the code had
    moved to 480, and the published-copy test passed because both were wrong."""
    from quickstarted.task import Budgets

    advertised = TASK_SCHEMA["properties"]["budgets"]["properties"]
    real = Budgets()
    for field, spec in advertised.items():
        assert spec["default"] == getattr(real, field), field


def test_a_success_block_needs_exactly_one_of_script_and_file():
    """The loader rejects both and neither; an editor should say so first."""
    forms = TASK_SCHEMA["properties"]["success"]["anyOf"]
    assert {"script", "file"} == {branch["required"][0] for branch in forms}


def test_schema_line_points_at_the_published_file():
    assert TASK_SCHEMA["$id"] in SCHEMA_LINE


@pytest.mark.parametrize(
    "path", sorted((ROOT / "tasks").glob("*.yaml")), ids=lambda p: p.name
)
def test_repo_tasks_use_only_documented_keys(path):
    """A schema that rejects the repo's own tasks would reject everyone's."""
    spec = yaml.safe_load(path.read_text())
    top = set(TASK_SCHEMA["properties"])
    assert set(spec) <= top, f"{path.name}: undocumented top-level keys"
    for section in ("docs", "network", "success", "budgets"):
        if isinstance(spec.get(section), dict):
            allowed = set(TASK_SCHEMA["properties"][section]["properties"])
            assert set(spec[section]) <= allowed, f"{path.name}: {section}"
