import textwrap

from quickstarted.cli import main

TASK = textwrap.dedent(
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
    path.write_text(TASK)
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
    path.write_text(TASK)
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
    path.write_text(TASK.replace("echo x > done.txt", "exit 1"))
    assert main(
        ["run", str(path), "--agent", "replay", "--backend", "local",
         "--allow-unenforced"]
    ) == 1
    assert "FAIL" in capsys.readouterr().out


def test_run_refuses_an_unenforced_backend_by_default(tmp_path, capsys):
    """Silently running without a boundary would make every result unciteable."""
    path = tmp_path / "j.yaml"
    path.write_text(TASK)
    code = main(["run", str(path), "--agent", "replay", "--backend", "local"])
    assert code == 1
    assert "REFUSING" in capsys.readouterr().err


def test_legacy_journeys_path_still_resolves(tmp_path, capsys, monkeypatch):
    """A CI config pinned to the pre-0.3 directory keeps working, with a warning."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "demo.yaml").write_text(TASK)

    assert main(["validate", "journeys/demo.yaml"]) == 0
    captured = capsys.readouterr()
    assert "renamed to 'tasks/'" in captured.err
    assert "cli-demo" in captured.out


def test_missing_file_is_still_an_error(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["validate", "journeys/absent.yaml"]) == 1
    assert "no such file" in capsys.readouterr().out


def test_node_script_without_image_warns(tmp_path, capsys):
    path = tmp_path / "j.yaml"
    path.write_text(TASK.replace("script: test -f done.txt", "script: npm run build"))
    assert main(["validate", str(path)]) == 0
    assert "no 'image' is set" in capsys.readouterr().out


def test_check_reruns_only_the_success_script(tmp_path, capsys):
    """The dev loop: iterate on a check against a kept workspace, no model."""
    path = tmp_path / "j.yaml"
    path.write_text(TASK)
    workspace = tmp_path / "kept" / "workspace"
    workspace.mkdir(parents=True)

    assert main(["check", str(path), "--sandbox", str(workspace), "--backend", "local"]) == 1
    assert "FAIL" in capsys.readouterr().out

    (workspace / "done.txt").write_text("x")
    assert main(["check", str(path), "--sandbox", str(workspace), "--backend", "local"]) == 0
    assert "PASS" in capsys.readouterr().out
    # The workspace is the user's; running a check must never consume it.
    assert (workspace / "done.txt").exists()


def test_check_show_prints_the_script_with_helpers(tmp_path, capsys):
    path = tmp_path / "j.yaml"
    path.write_text(TASK)
    assert main(["check", str(path), "--show"]) == 0
    out = capsys.readouterr().out
    assert "qs_wait_http()" in out
    assert "test -f done.txt" in out


def test_check_missing_sandbox_says_how_to_get_one(tmp_path, capsys):
    path = tmp_path / "j.yaml"
    path.write_text(TASK)
    assert main(["check", str(path), "--sandbox", str(tmp_path / "nope")]) == 3
    assert "--keep-sandbox" in capsys.readouterr().err


def test_init_scaffolds_a_task_that_validates(tmp_path, capsys, monkeypatch):
    """The scaffold must parse on first sight; INVALID reads as a broken tool."""
    monkeypatch.chdir(tmp_path)
    assert main(["init", "https://fastapi.tiangolo.com/tutorial/first-steps/"]) == 0
    written = tmp_path / "tasks" / "fastapi-quickstart.yaml"
    assert written.exists()
    body = written.read_text()
    assert "yaml-language-server: $schema=" in body
    assert "fastapi.tiangolo.com" in body
    capsys.readouterr()
    assert main(["validate", str(written)]) == 0


def test_init_names_the_project_not_the_registrar(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "https://docs.streamlit.io/get-started"]) == 0
    assert (tmp_path / "tasks" / "streamlit-quickstart.yaml").exists()
    capsys.readouterr()


def test_init_refuses_to_clobber(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "https://vite.dev/guide/"]) == 0
    capsys.readouterr()
    assert main(["init", "https://vite.dev/guide/"]) == 3
    assert "--force" in capsys.readouterr().err


def test_schema_command_emits_valid_json(capsys):
    import json

    assert main(["schema"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["title"] == "quickstarted task"


def test_config_supplies_flags_the_user_did_not_type(tmp_path, capsys, monkeypatch):
    import quickstarted.transport as transport

    monkeypatch.setattr(
        transport,
        "http_get",
        lambda url, timeout=30, method="GET": transport.HttpResponse(
            200, "text/plain", "docs"
        ),
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "quickstarted.yaml").write_text("run:\n  backend: local\n")
    path = tmp_path / "j.yaml"
    path.write_text(TASK)
    # `run` defaults to --backend auto, which on a machine with Docker would not
    # be local; the config is what makes this local. The safety gate still
    # applies to a backend a config chose, which is why --allow-unenforced is
    # still required here.
    assert main(["run", str(path), "--agent", "replay", "--allow-unenforced"]) == 0
    assert "backend: local" in capsys.readouterr().out


def test_a_malformed_config_is_reported_not_ignored(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "quickstarted.yaml").write_text("run:\n  agent: claude\n")
    path = tmp_path / "j.yaml"
    path.write_text(TASK)
    assert main(["validate", str(path)]) == 3
    assert "agent" in capsys.readouterr().err
