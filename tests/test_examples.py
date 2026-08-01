"""Packaged examples must stay identical to the tasks CI actually runs."""

import pathlib

import pytest

from quickstarted import examples
from quickstarted.task import load_task

TASKS = pathlib.Path(__file__).parent.parent / "tasks"


def test_there_are_examples():
    assert examples.names() == ["httpx", "streamlit", "vite"]


@pytest.mark.parametrize("name", examples.names())
def test_example_matches_the_task_it_came_from(name):
    """An example that drifts is one that quietly stops passing."""
    shipped = examples.path_for(name).read_text()
    source = (TASKS / f"{name}-quickstart.yaml").read_text()
    assert shipped == source, f"{name}.yaml has drifted from tasks/{name}-quickstart.yaml"


@pytest.mark.parametrize("name", examples.names())
def test_example_loads_and_supports_replay(name):
    task = load_task(examples.path_for(name))
    assert task.replay, "an example should be runnable without an API key"


def test_unknown_example_names_the_alternatives():
    with pytest.raises(FileNotFoundError, match="available: httpx, streamlit, vite"):
        examples.path_for("nope")
