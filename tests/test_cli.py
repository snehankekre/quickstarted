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


def test_legacy_journeys_path_fails_and_says_where_to_look(tmp_path, capsys, monkeypatch):
    """0.3.0 promised the fallback would go in 0.4.0, so it went."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "demo.yaml").write_text(TASK)

    assert main(["validate", "journeys/demo.yaml"]) == 1
    captured = capsys.readouterr()
    assert "removed in 0.4.0" in captured.err
    assert "tasks/demo.yaml" in captured.err


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


def test_run_discovers_tasks_when_given_none(tmp_path, capsys, monkeypatch):
    import quickstarted.transport as transport

    monkeypatch.setattr(
        transport,
        "http_get",
        lambda url, timeout=30, method="GET": transport.HttpResponse(
            200, "text/plain", "docs"
        ),
    )
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "a.yaml").write_text(TASK)
    assert main(["run", "--agent", "replay", "--backend", "local", "--allow-unenforced"]) == 0
    assert "cli-demo" in capsys.readouterr().out


def test_a_directory_and_an_unexpanded_glob_both_work(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "a.yaml").write_text(TASK)
    assert main(["validate", "tasks"]) == 0
    assert "cli-demo" in capsys.readouterr().out
    # PowerShell hands the glob through literally.
    assert main(["validate", "tasks/*.yaml"]) == 0
    assert "cli-demo" in capsys.readouterr().out


def test_validating_nothing_is_not_success(tmp_path, capsys, monkeypatch):
    """A CI job in the wrong directory must not report success."""
    monkeypatch.chdir(tmp_path)
    assert main(["validate"]) == 3
    assert "none found" in capsys.readouterr().err


def test_examples_ship_in_the_package(capsys):
    assert main(["examples"]) == 0
    out = capsys.readouterr().out
    assert "httpx" in out and "streamlit" in out


def test_run_example_needs_no_task_file(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["validate", "--example", "httpx"]) == 0
    assert "httpx-quickstart" in capsys.readouterr().out


def test_unknown_example_lists_the_real_ones(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["validate", "--example", "nope"]) == 3
    assert "available: httpx" in capsys.readouterr().err


def test_a_run_reports_progress_while_it_happens(tmp_path, capsys, monkeypatch):
    """Silence for four minutes makes a slow model and a hung container identical."""
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
    assert main(
        ["run", str(path), "--agent", "replay", "--backend", "local",
         "--allow-unenforced"]
    ) == 0
    out = capsys.readouterr().out
    assert "read https://example.com/docs/" in out
    assert "check exited 0" in out
    # The shell stays out of the way until asked for.
    assert "$ echo x > done.txt" not in out


def test_verbose_streams_the_shell_and_quiet_streams_nothing(tmp_path, capsys, monkeypatch):
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
    base = ["run", str(path), "--agent", "replay", "--backend", "local",
            "--allow-unenforced"]

    assert main([*base, "--verbose"]) == 0
    assert "$ echo x > done.txt" in capsys.readouterr().out

    assert main([*base, "--quiet"]) == 0
    out = capsys.readouterr().out
    assert "read https://example.com/docs/" not in out
    assert "PASS" in out


def test_a_broken_watcher_cannot_kill_a_paid_run():
    from quickstarted.trace import Trace

    def explode(event):
        raise RuntimeError("watcher bug")

    trace = Trace(listener=explode)
    trace.add("docs_fetch", url="https://example.com/")
    assert trace.fetched_urls() == ["https://example.com/"]
