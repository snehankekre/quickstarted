"""Repo defaults, and the precedence rule that the more specific one wins."""

import pytest

from quickstarted.config import ConfigError, find_config, load_config, merge_defaults
from quickstarted.task import load_task

CONFIG = """
run:
  backend: local
  cache_dir: .qs-cache
tasks:
  budgets:
    max_seconds: 120
  setup:
    - python3 -m venv .venv
"""

TASK = """
name: t
goal: g
docs:
  entrypoint: https://example.com/
success:
  script: "true"
"""


def write(tmp_path, config=CONFIG, task=TASK):
    (tmp_path / "quickstarted.yaml").write_text(config)
    path = tmp_path / "t.yaml"
    path.write_text(task)
    return path


def test_task_inherits_config_defaults(tmp_path):
    path = write(tmp_path)
    task = load_task(path, load_config(tmp_path / "quickstarted.yaml").tasks)
    assert task.budgets.max_seconds == 120
    assert task.setup == ("python3 -m venv .venv",)


def test_the_task_file_wins(tmp_path):
    path = write(tmp_path, task=TASK + "budgets:\n  max_seconds: 30\n")
    task = load_task(path, load_config(tmp_path / "quickstarted.yaml").tasks)
    assert task.budgets.max_seconds == 30


def test_lists_replace_rather_than_concatenate(tmp_path):
    """Concatenating would run both, in an order nobody chose."""
    path = write(tmp_path, task=TASK + "setup:\n  - npm init -y\n")
    task = load_task(path, load_config(tmp_path / "quickstarted.yaml").tasks)
    assert task.setup == ("npm init -y",)


def test_config_is_found_from_a_subdirectory(tmp_path):
    write(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_config(nested) == tmp_path / "quickstarted.yaml"


def test_no_config_is_not_an_error(tmp_path):
    assert not load_config(None) or True
    assert find_config(tmp_path) is None


def test_settings_that_change_a_result_are_refused(tmp_path):
    """A config that silently swapped the model would make runs incomparable."""
    path = tmp_path / "quickstarted.yaml"
    path.write_text("run:\n  agent: claude\n  model: gpt-5.2\n")
    with pytest.raises(ConfigError, match="agent"):
        load_config(path)


def test_unknown_top_level_key_is_refused(tmp_path):
    path = tmp_path / "quickstarted.yaml"
    path.write_text("runs:\n  backend: local\n")
    with pytest.raises(ConfigError, match="unknown keys"):
        load_config(path)


def test_merge_is_recursive_for_mappings():
    merged = merge_defaults(
        {"budgets": {"max_turns": 20, "max_seconds": 900}}, {"budgets": {"max_turns": 5}}
    )
    assert merged == {"budgets": {"max_turns": 5, "max_seconds": 900}}
