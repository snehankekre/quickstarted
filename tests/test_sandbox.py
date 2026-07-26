import os
from pathlib import Path

from quickstarted.sandbox import Sandbox, truncate


def test_run_and_cwd():
    sb = Sandbox()
    try:
        result = sb.run("pwd && echo done", timeout=10)
        assert result.exit_code == 0
        assert str(sb.root.name) in result.output
        assert "done" in result.output
    finally:
        sb.cleanup()
    assert not Path(sb.root).exists()


def test_env_is_scrubbed():
    os.environ["QUICKSTARTED_TEST_SECRET"] = "leakme"
    try:
        sb = Sandbox()
        try:
            result = sb.run("env", timeout=10)
            assert "leakme" not in result.output
            assert "QUICKSTARTED_TEST_SECRET" not in result.output
            # HOME points into the sandbox, not the real home
            home = sb.run("echo $HOME", timeout=10)
            assert str(sb.base) in home.output
            assert home.output.strip() != str(Path.home())
        finally:
            sb.cleanup()
    finally:
        del os.environ["QUICKSTARTED_TEST_SECRET"]


def test_workspace_starts_empty():
    """Scaffolders refuse a non-empty directory, so HOME must live elsewhere.

    `npm create vite@latest .` and `django-admin startproject .` both bail out
    if anything is already there, dotfiles included. A HOME inside the workspace
    used to seed it with .npm and .cache before the agent ran one command.
    """
    sb = Sandbox()
    try:
        listing = sb.run("ls -A | wc -l", timeout=10)
        assert listing.output.strip() == "0", listing.output
        # And HOME is still writable, wherever it went.
        assert sb.run("touch $HOME/probe && test -f $HOME/probe", timeout=10).exit_code == 0
        assert sb.run("ls -A | wc -l", timeout=10).output.strip() == "0"
    finally:
        sb.cleanup()


def test_timeout():
    sb = Sandbox()
    try:
        result = sb.run("sleep 5", timeout=1)
        assert result.timed_out
        assert result.exit_code == 124
        assert "timed out" in result.output
    finally:
        sb.cleanup()


def test_state_persists_on_disk_between_commands():
    sb = Sandbox()
    try:
        assert sb.run("echo hello > f.txt", timeout=10).exit_code == 0
        result = sb.run("cat f.txt", timeout=10)
        assert result.exit_code == 0
        assert "hello" in result.output
    finally:
        sb.cleanup()


def test_truncate_keeps_head_and_tail():
    text = "A" * 600 + "MIDDLE" + "B" * 600
    out = truncate(text, 200)
    assert out.startswith("A")
    assert out.endswith("B")
    assert "truncated" in out
    assert "MIDDLE" not in out
    assert truncate("short", 200) == "short"
