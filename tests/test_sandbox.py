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
            assert str(sb.root) in home.output
        finally:
            sb.cleanup()
    finally:
        del os.environ["QUICKSTARTED_TEST_SECRET"]


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
