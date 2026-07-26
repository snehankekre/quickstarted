import pytest

from quickstarted.task import TaskError, load_task

VALID = """
name: demo
goal: Do the thing.
docs:
  entrypoint: https://example.com/docs/
  allow:
    - pypi.org
setup:
  - "true"
success:
  script: "true"
budgets:
  max_turns: 3
replay:
  - echo hi
"""


def write(tmp_path, text, name="j.yaml"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_load_valid(tmp_path):
    j = load_task(write(tmp_path, VALID))
    assert j.name == "demo"
    assert j.docs_entrypoint == "https://example.com/docs/"
    # entrypoint host auto-added to the allowlist, ahead of listed hosts
    assert j.docs_allow == ("example.com", "pypi.org")
    assert j.budgets.max_turns == 3
    assert j.budgets.max_seconds == 900  # default preserved
    assert j.replay == ("echo hi",)


def test_host_allowed(tmp_path):
    j = load_task(write(tmp_path, VALID))
    assert j.host_allowed("https://example.com/page")
    assert j.host_allowed("https://docs.example.com/page")  # subdomain
    assert j.host_allowed("https://pypi.org/project/x/")
    assert not j.host_allowed("https://evil.com/")
    assert not j.host_allowed("https://notexample.com/")  # no suffix trickery
    assert not j.host_allowed("not a url")


@pytest.mark.parametrize(
    "mutation",
    [
        ("name: demo", ""),  # missing name
        ("goal: Do the thing.", ""),  # missing goal
        ("  entrypoint: https://example.com/docs/", "  entrypoint: ftp://x/"),
        ("  script: \"true\"", ""),  # missing success script
    ],
)
def test_missing_or_bad_fields(tmp_path, mutation):
    old, new = mutation
    broken = VALID.replace(old, new)
    with pytest.raises(TaskError):
        load_task(write(tmp_path, broken))


def test_unknown_budget_key(tmp_path):
    broken = VALID.replace("max_turns: 3", "max_bananas: 3")
    with pytest.raises(TaskError, match="max_bananas"):
        load_task(write(tmp_path, broken))


def test_missing_file(tmp_path):
    with pytest.raises(TaskError, match="no such file"):
        load_task(tmp_path / "nope.yaml")


def test_repo_tasks_are_valid():
    import pathlib

    tasks_dir = pathlib.Path(__file__).parent.parent / "tasks"
    files = sorted(tasks_dir.glob("*.yaml"))
    assert files, "no tasks shipped in repo"
    for f in files:
        j = load_task(f)
        assert j.replay, f"{f.name} should support replay mode"


def test_registry_declared_as_docs_host_is_flagged(tmp_path):
    """The mistake that silently breaks `pip install` must be visible."""
    path = tmp_path / "j.yaml"
    path.write_text(
        "name: conflict\n"
        "goal: install something\n"
        "docs:\n"
        "  entrypoint: https://docs.example.com/\n"
        "  allow:\n"
        "    - pypi.org\n"
        "success:\n"
        "  script: 'true'\n"
    )
    task = load_task(path)
    assert "pypi.org" in task.network_conflicts
    assert task.attribution_gaps == ()


def test_explicit_network_allow_clears_the_conflict(tmp_path):
    path = tmp_path / "j.yaml"
    path.write_text(
        "name: resolved\n"
        "goal: install something\n"
        "docs:\n"
        "  entrypoint: https://docs.example.com/\n"
        "  allow:\n"
        "    - pypi.org\n"
        "network:\n"
        "  allow:\n"
        "    - pypi.org\n"
        "success:\n"
        "  script: 'true'\n"
    )
    task = load_task(path)
    assert task.network_conflicts == ()
    assert "pypi.org" in task.attribution_gaps


def test_image_defaults_to_empty(tmp_path):
    assert load_task(write(tmp_path, VALID)).image == ""


def test_image_is_read_from_the_task(tmp_path):
    task = load_task(write(tmp_path, VALID + "image: node:22-slim\n"))
    assert task.image == "node:22-slim"


@pytest.mark.parametrize(
    "script, expected",
    [
        ("npm run build", True),
        ("set -e\ntest -f dist/index.html\nnpx tsc --noEmit", True),
        ("pnpm install && node app.js", True),
        (".venv/bin/python -c 'import httpx'", False),
        # 'node' inside a longer word is not the Node binary.
        ("test -f nodes.txt && grep -q node_count out.txt", False),
    ],
)
def test_needs_node_detection(tmp_path, script, expected):
    body = (
        "name: n\n"
        "goal: g\n"
        "docs:\n"
        "  entrypoint: https://example.com/\n"
        "success:\n"
        "  script: |\n" + "".join(f"    {line}\n" for line in script.splitlines())
    )
    assert load_task(write(tmp_path, body)).needs_node is expected
