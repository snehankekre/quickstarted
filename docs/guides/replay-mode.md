# Replay mode

> Run the commands your documentation actually prints, for free, on every push.

Agent mode is the reason this tool exists. Replay mode is the cheap check you
run underneath it, and the two answer different questions.

A `replay` block is the literal sequence a reader is told to type:

```yaml
replay:
  - .venv/bin/pip install --quiet httpx
  - |
    cat > fetch.py <<'PY'
    import httpx

    print(httpx.get("https://www.python-httpx.org/").status_code)
    PY
  - .venv/bin/python fetch.py
```

```bash
quickstarted run tasks/httpx.yaml --agent replay
```

The harness runs them in order, stops at the first non-zero exit, and then runs
the same `success.script` agent mode would. No model is involved, so a run costs
nothing and takes seconds.

## What it can and cannot tell you

It catches the failures that are nobody's judgment call: a package that was
renamed, a flag that was removed, an import path that moved, a code block with
a typo. Those break every reader equally.

It cannot tell you whether a reader could have *found* those commands, whether
the order on the page makes sense, or whether step four assumes something only
step one's author knew. Replay follows a path you already laid out. Only an
agent has to find one.

So treat replay as a precondition. If it fails, fix that first, because an agent
failure on top of broken commands tells you nothing new.

## Every failure gets a classification

Break a replay block on purpose by installing a package that does not exist:

```yaml
replay:
  - .venv/bin/pip install --quiet httpxx
```

```
[INCONCLUSIVE] httpx-quickstart (replay)
  classification: harness_error
  stop reason: command_failed (replay step 1 failed: .venv/bin/pip install --quiet httpxx)
```

Note that this is not a `docs_gap`. quickstarted separates "your documentation
is wrong" from "this run never produced evidence", and a command that could not
resolve a package lands in the second group and is excluded from pass rates.
Guessing between the two is how benchmarks end up publishing noise. See
[Pass rates](pass-rates.md).

## Both, on two schedules

```bash
quickstarted run tasks/*.yaml --agent replay              # every push
quickstarted run tasks/*.yaml --agent claude --repeat 3   # weekly
```

Replay is free and deterministic, so gating merges on it is reasonable. Agent
mode costs tokens and varies between runs, so it belongs on a schedule or on a
new model release, read as a rate rather than a verdict. [Running in
CI](ci.md) has both jobs.

A task may declare either block or both. `quickstarted validate` reports
which modes each file supports:

```
ok       tasks/httpx.yaml (httpx-quickstart, replay+agent)
ok       tasks/streamlit-quickstart.yaml (streamlit-quickstart, agent-only)
```
