#!/usr/bin/env bash
# Success check for fastapi-quickstart. Run by the harness after the agent
# stops, in the same workspace, with the qs_* helpers already defined.
set -e

test -f app.py || qs_fail "no app.py, so the tutorial never produced an application"

# Whichever documented way of serving is available, because the tutorial leads
# with `fastapi dev` while uvicorn is the older instruction, and requiring one
# of them measures my expectation rather than the docs. That mistake cost three
# runs: an agent that installed plain `fastapi` rather than `fastapi[standard]`
# had no uvicorn, and a working app was recorded as a documentation gap.
if [ -x .venv/bin/fastapi ]; then
  qs_serve .venv/bin/fastapi run app.py --host 127.0.0.1 --port "$QS_PORT"
elif .venv/bin/python -c "import uvicorn" 2>/dev/null; then
  qs_serve .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "$QS_PORT"
else
  qs_fail "neither the fastapi CLI nor uvicorn is installed, so nothing can serve app.py"
fi

qs_wait_http /items/42 --json item_id=42
