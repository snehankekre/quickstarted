import textwrap

from quickstarted.cli import main

JOURNEY = textwrap.dedent(
    """
    name: cli-demo
    goal: create done.txt
    docs:
      entrypoint: https://example.com/docs/
    success:
      script: test -f done.txt
    budgets:
      max_seconds: 60
    replay:
      - echo x > done.txt
    """
)


def test_validate_ok(tmp_path, capsys):
    path = tmp_path / "j.yaml"
    path.write_text(JOURNEY)
    assert main(["validate", str(path)]) == 0
    assert "ok" in capsys.readouterr().out


def test_validate_bad(tmp_path, capsys):
    path = tmp_path / "j.yaml"
    path.write_text("name: only-a-name\n")
    assert main(["validate", str(path)]) == 1
    assert "INVALID" in capsys.readouterr().out


def test_run_replay_writes_outputs(tmp_path, capsys, monkeypatch):
    # Replay fetches the entrypoint; stub the network out.
    import quickstarted.transport as transport

    monkeypatch.setattr(
        transport,
        "http_get",
        lambda url, timeout=30, method="GET": transport.HttpResponse(
            200, "text/plain", "docs"
        ),
    )
    path = tmp_path / "j.yaml"
    path.write_text(JOURNEY)
    out_dir = tmp_path / "results"
    code = main(
        ["run", str(path), "--agent", "replay", "--out", str(out_dir),
         "--backend", "local", "--allow-unenforced"]
    )
    captured = capsys.readouterr().out
    assert code == 0
    assert "PASS" in captured
    assert (out_dir / "cli-demo" / "trace.jsonl").is_file()
    assert (out_dir / "cli-demo" / "report.md").is_file()


def test_run_exit_code_on_failure(tmp_path, capsys, monkeypatch):
    import quickstarted.transport as transport

    monkeypatch.setattr(
        transport,
        "http_get",
        lambda url, timeout=30, method="GET": transport.HttpResponse(
            200, "text/plain", "docs"
        ),
    )
    path = tmp_path / "j.yaml"
    path.write_text(JOURNEY.replace("echo x > done.txt", "exit 1"))
    assert main(
        ["run", str(path), "--agent", "replay", "--backend", "local",
         "--allow-unenforced"]
    ) == 1
    assert "FAIL" in capsys.readouterr().out


def test_run_refuses_an_unenforced_backend_by_default(tmp_path, capsys):
    """Silently running without a boundary would make every result unciteable."""
    path = tmp_path / "j.yaml"
    path.write_text(JOURNEY)
    code = main(["run", str(path), "--agent", "replay", "--backend", "local"])
    assert code == 1
    assert "REFUSING" in capsys.readouterr().err
