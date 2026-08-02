#!/usr/bin/env bash
# Success check for fastapi-quickstart. Run by the harness after the agent
# stops, in the same workspace, with the qs_* helpers already defined.
set -e

# The tutorial says, in these words, "copy that to a file main.py". Asserting
# app.py instead is asserting a filename the documentation never uses, which is
# testing the task author rather than the docs.
test -f main.py || qs_fail "no main.py, so the tutorial never produced an application"

# The project environment is the agent's to choose: the tutorial index leads
# with `uv add "fastapi[standard]"`, and documents pip underneath. Look for the
# app wherever it landed rather than requiring one of them, because requiring
# one measures my expectation instead of the documentation.
for candidate in ./.venv/bin/fastapi ./.venv/Scripts/fastapi fastapi; do
  # `[ -x fastapi ]` tests the relative path ./fastapi, never $PATH, so a
  # globally installed CLI was missed and a stray executable of that name in
  # the workspace was found and then not run. Resolve it the way the shell
  # will, and serve exactly what was resolved.
  resolved=$(command -v "$candidate" 2>/dev/null) || continue
  if [ -n "$resolved" ] && [ -x "$resolved" ]; then
    qs_serve "$resolved" run main.py --host 127.0.0.1 --port "$QS_PORT"
    served=1
    break
  fi
done
if [ -z "${served:-}" ]; then
  for python in .venv/bin/python python3 python; do
    if command -v "$python" >/dev/null 2>&1 && "$python" -c "import uvicorn" 2>/dev/null; then
      qs_serve "$python" -m uvicorn main:app --host 127.0.0.1 --port "$QS_PORT"
      served=1
      break
    fi
  done
fi
[ -n "${served:-}" ] || \
  qs_fail "neither the fastapi CLI nor uvicorn is installed, so nothing can serve main.py"

# The documented example: @app.get("/") returning {"message": "Hello World"}.
qs_wait_http / --json message="Hello World"
