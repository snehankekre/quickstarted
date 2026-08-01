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


SUCCESS_FILE = VALID.replace('  script: "true"', "  file: checks/demo.sh")


def test_success_file_is_inlined(tmp_path):
    """A check kept in a real file, so it can be shellchecked and hand-run."""
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "demo.sh").write_text("set -e\ntest -f app.py\n")
    task = load_task(write(tmp_path, SUCCESS_FILE))
    assert task.success_script == "set -e\ntest -f app.py\n"


def test_success_file_and_script_together_is_an_error(tmp_path):
    both = VALID.replace('  script: "true"', '  script: "true"\n  file: checks/demo.sh')
    with pytest.raises(TaskError, match="both"):
        load_task(write(tmp_path, both))


def test_success_file_must_exist(tmp_path):
    with pytest.raises(TaskError, match="does not exist"):
        load_task(write(tmp_path, SUCCESS_FILE))


def test_success_file_must_not_be_empty(tmp_path):
    checks = tmp_path / "checks"
    checks.mkdir()
    (checks / "demo.sh").write_text("\n\n")
    with pytest.raises(TaskError, match="is empty"):
        load_task(write(tmp_path, SUCCESS_FILE))


def test_success_file_must_be_relative(tmp_path):
    absolute = VALID.replace('  script: "true"', "  file: /etc/passwd")
    with pytest.raises(TaskError, match="relative"):
        load_task(write(tmp_path, absolute))


def test_unknown_success_key(tmp_path):
    broken = VALID.replace('  script: "true"', '  scrpit: "true"')
    with pytest.raises(TaskError, match="scrpit"):
        load_task(write(tmp_path, broken))


DECLARATIVE = """
name: served
goal: serve something
docs:
  entrypoint: https://example.com/docs/
success:
  serve: .venv/bin/fastapi run app.py --port $QS_PORT
  wait_http:
    path: /items/42
    json:
      item_id: 42
    timeout: 30
  script: test -f app.py
"""


def test_declarative_form_generates_helper_calls(tmp_path):
    task = load_task(write(tmp_path, DECLARATIVE))
    script = task.success_script
    assert "qs_serve .venv/bin/fastapi run app.py --port $QS_PORT" in script
    assert "qs_wait_http '/items/42'" in script
    assert "--json 'item_id=42'" in script
    assert "--timeout '30'" in script
    # The author's own assertion still runs, and still decides.
    assert script.rstrip().endswith("test -f app.py")


SERVE_ONLY = """
name: served
goal: serve something
docs:
  entrypoint: https://example.com/docs/
success:
  serve: .venv/bin/fastapi run app.py --port $QS_PORT
"""


def test_serve_without_an_assertion_is_rejected(tmp_path):
    """A server that boots and answers every request with a 500 is not a pass."""
    with pytest.raises(TaskError, match="nothing checks it"):
        load_task(write(tmp_path, SERVE_ONLY))


def test_inline_script_is_passed_through_untouched(tmp_path):
    """No injected `set -e`: the author's script is the author's script."""
    task = load_task(write(tmp_path, VALID))
    assert task.success_script == "true"


def test_check_script_carries_the_prelude(tmp_path):
    task = load_task(write(tmp_path, VALID))
    assert "qs_wait_http()" in task.check_script
    assert task.check_script.endswith("true")


def test_wait_http_needs_a_target(tmp_path):
    text = DECLARATIVE.replace("    path: /items/42\n", "")
    with pytest.raises(TaskError, match="path' or 'url'"):
        load_task(write(tmp_path, text))


def _task_with(tmp_path, success, setup="", replay=""):
    text = (
        "name: t\ngoal: g\ndocs:\n  entrypoint: https://example.com/\n"
        f"{setup}{replay}success:\n  script: |\n"
        + "".join(f"    {line}\n" for line in success.splitlines())
    )
    return load_task(write(tmp_path, text))


def test_env_path_no_setup_creates_is_flagged(tmp_path):
    """The mistake that records a working run as a documentation failure."""
    task = _task_with(tmp_path, "test -f app.py\n.venv/bin/python -c 'import x'")
    assert task.unprepared_env_paths == (".venv",)


def test_env_path_created_by_setup_is_fine(tmp_path):
    task = _task_with(
        tmp_path,
        ".venv/bin/python -c 'import x'",
        setup="setup:\n  - python3 -m venv .venv\n",
    )
    assert task.unprepared_env_paths == ()


def test_env_path_the_documented_commands_create_is_fine(tmp_path):
    """If replay builds it, the documentation promises it."""
    task = _task_with(
        tmp_path,
        ".venv/bin/python -c 'import x'",
        replay="replay:\n  - uv sync\n  - .venv/bin/python -V\n",
    )
    assert task.unprepared_env_paths == ()


def test_shell_variable_prefix_does_not_leak_into_the_name(tmp_path):
    task = _task_with(
        tmp_path,
        'WS="$PWD"\n"$WS/.venv/bin/python" manage.py check',
        setup="setup:\n  - python3 -m venv .venv\n",
    )
    assert task.unprepared_env_paths == ()


def test_multiple_bare_assertions_can_fail_silently(tmp_path):
    task = _task_with(tmp_path, "set -e\ntest -f a.py\ntest -d polls")
    assert task.can_fail_silently


def test_a_check_that_reports_is_not_flagged(tmp_path):
    task = _task_with(
        tmp_path, 'set -e\ntest -f a.py || qs_fail "no a.py"\ntest -d polls'
    )
    assert not task.can_fail_silently


def test_a_single_obvious_assertion_is_not_flagged(tmp_path):
    """`test -f app.py` says what it saw by saying what it looked for."""
    assert not _task_with(tmp_path, "test -f app.py").can_fail_silently


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
