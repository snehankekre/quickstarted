# Testing the quickstart, not your idea of it

> Why a task may name nothing its target documentation does not name.

A task is supposed to ask one question: if a reader follows this quickstart,
do they reach the outcome it promises? A task that adds a requirement the page
never made is asking a different question and reporting the answer under the
first question's name.

## How the drift happens

Nobody sets out to do this. The pressure comes from the check.

Until 0.6.0 a success check could only observe the filesystem after the run.
So the author would ask "what can I assert?" before asking "what does the page
promise?", and the goal would get written backwards from the answer. Most
quickstarts do not end at a file:

| Project | Where its quickstart ends |
| --- | --- |
| DuckDB | `con.table("test").show()`, a table on the terminal |
| Polars | `print(df_csv)` |
| Prisma | two `console.log` calls |
| HTTPX | a REPL session showing `200` |

None of those leave anything to `test -f`. So the author bolts on an artefact,
and the task now says "write the total to `total.txt`". The check passes, the
number looks real, and what was measured is the author's invention.

## What it looks like

Here is the gap, for seven real quickstarts:

| Task | The documentation says | The task demanded |
| --- | --- | --- |
| fastapi | "copy that to a file `main.py`" | `app.py` |
| uv | `uv init` generates a `main.py` that prints a greeting | overwrite it to print `ok` |
| prisma | ends at `console.log` | write `out.json` |
| polars | ends at `print(df_csv)` | write `script.py` and `out.csv` |
| duckdb | `con.table("test").show()` | write `script.py`, `shop.db`, `total.txt` |
| httpx | a REPL session | write `fetch.py` |
| tailwind | builds to `src/output.css` | build to `out.css`, from a page whose documented step is a watcher |

The FastAPI row is the clearest. The tutorial says, in those words, "copy that
to a file `main.py`". A reader who followed it exactly produced `main.py` and
failed a check looking for `app.py`. Whatever that measured, it was not the
tutorial.

## The rule

**Write the goal from the page. Write the check from the goal.**

If you find yourself writing the goal from the check, stop. You are about to
invent an artefact so the check has something to look at.

Two features exist to remove the pressure:

- [`expect_output`](../reference/task-schema.md#expect_output) makes the
  terminal assertable, so a quickstart that ends at a printed value can be
  checked where it actually ends.
- [`docs.path`](../reference/task-schema.md#why-a-path-rather-than-a-page) lets
  a task name the whole route a reader takes, so the install page and the
  example page are both in scope.

Where the documentation genuinely names a file, name it, and match it exactly.
Where it does not, find it rather than dictating it. Streamlit writes
`streamlit run your_script.py`, a placeholder, so the shipped task searches the
workspace for a script importing streamlit instead of demanding a name.

## When the documentation and the sandbox disagree

Sometimes a documented route cannot run here. Tailwind's main installation page
ends at `npm run dev`, a watcher; uv's primary installer is a script on a host
the sandbox deliberately cannot reach; Prefect's quickstart is a deploy story
that needs a server or a cloud login.

There are three honest responses, in order of preference:

1. **Point at the documented route that does work.** Tailwind's task now uses
   the Tailwind CLI installation page, which is a first-class documented path
   that produces a file without a watcher.
2. **State the constraint in the goal and take the deviation on the record.**
   uv's task says the standalone installer is unreachable and asks the agent to
   use one of the other methods the page lists.
3. **Drop the task.** Prefect's was removed in 0.6.0. It forbade all three of
   the things its own quickstart tells a reader to do, and substituted an
   invented flow. A task that fights its documentation cannot be reworded into
   a measurement.

What is never acceptable is the fourth option: keep the task, keep the
constraint, and report the resulting failure as a documentation gap.

## The honest limitation

`expect_output` reads what the run printed. The commands themselves are kept
out of that record, and so is anything a failing command printed, because
otherwise a heredoc or a stack trace counts as output. What remains is still the
agent's own transcript: deterministic, and seen by no model, but unable to tell
a computed value from an echoed one.

This is not new. A check that greps a file the agent wrote has always had the
same hole, which is why the DuckDB task reopens the database rather than
trusting an answer file. The discipline is unchanged: where the documentation
leaves durable state, assert the state too.

```yaml
success:
  expect_output:
    contains: "42"
  script: |
    set -e
    test -f file.db || qs_fail "no file.db"
    .venv/bin/python - <<'PY'
    import duckdb
    con = duckdb.connect("file.db", read_only=True)
    assert con.execute("select i from test").fetchall() == [(42,)]
    PY
```
