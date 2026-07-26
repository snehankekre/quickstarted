import pytest

from quickstarted.journey import JourneyError, load_journey

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
    j = load_journey(write(tmp_path, VALID))
    assert j.name == "demo"
    assert j.docs_entrypoint == "https://example.com/docs/"
    # entrypoint host auto-added to the allowlist, ahead of listed hosts
    assert j.docs_allow == ("example.com", "pypi.org")
    assert j.budgets.max_turns == 3
    assert j.budgets.max_seconds == 900  # default preserved
    assert j.replay == ("echo hi",)


def test_host_allowed(tmp_path):
    j = load_journey(write(tmp_path, VALID))
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
    with pytest.raises(JourneyError):
        load_journey(write(tmp_path, broken))


def test_unknown_budget_key(tmp_path):
    broken = VALID.replace("max_turns: 3", "max_bananas: 3")
    with pytest.raises(JourneyError, match="max_bananas"):
        load_journey(write(tmp_path, broken))


def test_missing_file(tmp_path):
    with pytest.raises(JourneyError, match="no such file"):
        load_journey(tmp_path / "nope.yaml")


def test_repo_journeys_are_valid():
    import pathlib

    journeys_dir = pathlib.Path(__file__).parent.parent / "journeys"
    files = sorted(journeys_dir.glob("*.yaml"))
    assert files, "no journeys shipped in repo"
    for f in files:
        j = load_journey(f)
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
    journey = load_journey(path)
    assert "pypi.org" in journey.network_conflicts
    assert journey.attribution_gaps == ()


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
    journey = load_journey(path)
    assert journey.network_conflicts == ()
    assert "pypi.org" in journey.attribution_gaps
