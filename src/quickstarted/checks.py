"""The shell prelude every success script gets, and the declarative form.

Four tasks in this repo hand-rolled the same twenty lines: background a server,
capture the PID, poll it with `urllib` because the image has no curl, keep the
last error instead of swallowing it, dump the log on failure, kill, exit. The
guide teaches that pattern at length, which is the tell that it should be code.
It is also the pattern people get wrong: a `set -e` that aborts before the
diagnostics run produces an exit code and no reason, and a `docs_gap` that names
a page and no reason is not a data point anyone can publish.

**Mechanism is the harness's, criteria are the author's.** These helpers start
processes, poll, capture logs and print diagnostics. What counts as success is
whatever the task file says, which is why `serve:` alone is a validation error
rather than a free pass. Nothing here consults a model, and nothing decides a
verdict the author did not write down.
"""

from __future__ import annotations

import zlib

#: Base of the port range `$QS_PORT` is chosen from. Above the ephemeral range
#: most quickstarts pick (3000, 5173, 8000, 8080) so a documented default and a
#: harness-chosen port do not collide.
_PORT_BASE = 21000
_PORT_SPAN = 20000

PRELUDE = r"""
# ---- quickstarted check helpers -------------------------------------------
# Prepended to every success script. Mechanism only: what counts as success is
# whatever this task asserts below.
QS_LOG="${TMPDIR:-/tmp}/quickstarted-serve.log"
QS_BODY="${TMPDIR:-/tmp}/quickstarted-body.out"
_qs_pids=""
_qs_last="never attempted"

# Report and stop. Printed last so the one-line console summary shows the
# reason rather than a stray line of somebody's log.
qs_fail() {
  printf 'check failed: %s\n' "$*"
  exit 1
}

# Pick a port nothing is listening on, starting from the task's base. Bash's
# /dev/tcp works in every image we support, unlike curl, which python:3.12-slim
# does not ship.
_qs_pick_port() {
  _qs_p="$QS_PORT_BASE"
  _qs_end=$(( QS_PORT_BASE + 20 ))
  while [ "$_qs_p" -lt "$_qs_end" ]; do
    if ! (exec 3<>"/dev/tcp/127.0.0.1/$_qs_p") 2>/dev/null; then
      QS_PORT="$_qs_p"
      export QS_PORT
      return 0
    fi
    _qs_p=$(( _qs_p + 1 ))
  done
  QS_PORT="$QS_PORT_BASE"
  export QS_PORT
}
_qs_pick_port

# Background a long-running command, keeping its output where a failure can
# quote it. `qs_serve .venv/bin/fastapi run app.py --port $QS_PORT`
qs_serve() {
  "$@" > "$QS_LOG" 2>&1 &
  _qs_pids="$_qs_pids $!"
}

# Kill anything qs_serve started, however the script leaves.
_qs_cleanup() {
  for _qs_pid in $_qs_pids; do
    kill "$_qs_pid" 2>/dev/null || true
  done
}
trap _qs_cleanup EXIT

_qs_log_tail() {
  if [ -s "$QS_LOG" ]; then
    printf -- '--- server log (last 20 lines) ---\n'
    tail -20 "$QS_LOG"
    printf -- '----------------------------------\n'
  else
    printf -- '(no server output; it may never have started)\n'
  fi
}

# One request. Sets _qs_status, writes the body to $QS_BODY, returns non-zero
# when the connection itself failed. Tries whatever the image actually has:
# python:3.12-slim has python3 and no curl, node:22-slim has node.
_qs_get() {
  _qs_url="$1"
  _qs_status=""
  : > "$QS_BODY"
  if command -v curl >/dev/null 2>&1; then
    _qs_status=$(curl -sS -o "$QS_BODY" -w '%{http_code}' --max-time 10 "$_qs_url" 2>>"$QS_BODY") || {
      _qs_last="connection failed: $(tail -1 "$QS_BODY" 2>/dev/null)"
      return 1
    }
  elif command -v python3 >/dev/null 2>&1; then
    _qs_status=$(python3 - "$_qs_url" "$QS_BODY" <<'PY' 2>/dev/null
import sys, urllib.request, urllib.error
url, out = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(url, timeout=10) as r:
        body, status = r.read(), r.status
except urllib.error.HTTPError as exc:
    body, status = exc.read(), exc.code
except Exception as exc:
    sys.stderr.write(f"{type(exc).__name__}: {exc}")
    sys.exit(1)
open(out, "wb").write(body)
print(status)
PY
    ) || {
      _qs_last="connection failed"
      return 1
    }
  elif command -v node >/dev/null 2>&1; then
    _qs_status=$(node -e '
      const [url, out] = process.argv.slice(1);
      fetch(url).then(async r => {
        require("fs").writeFileSync(out, Buffer.from(await r.arrayBuffer()));
        console.log(r.status);
      }).catch(e => { console.error(String(e)); process.exit(1); });
    ' "$_qs_url" "$QS_BODY" 2>/dev/null) || {
      _qs_last="connection failed"
      return 1
    }
  elif command -v wget >/dev/null 2>&1; then
    # No status code without parsing headers; a fetch that succeeded is 200.
    wget -q -O "$QS_BODY" -T 10 "$_qs_url" || { _qs_last="connection failed"; return 1; }
    _qs_status=200
  else
    qs_fail "no way to make an HTTP request in this image (no curl, python3, node, or wget)"
  fi
  return 0
}

# Poll until the endpoint answers the way this task says it should.
#
#   qs_wait_http /items/42 --json item_id=42
#   qs_wait_http http://127.0.0.1:8599/health --contains ok --timeout 60
#
# A bare path is resolved against http://127.0.0.1:$QS_PORT. Matching is by
# regular expression over the response body, not a JSON parse, so --json is a
# tolerant "this key holds this value" and nothing more.
qs_wait_http() {
  _qs_target="$1"; shift
  case "$_qs_target" in
    http://*|https://*) _qs_url="$_qs_target" ;;
    /*)  _qs_url="http://127.0.0.1:${QS_PORT}${_qs_target}" ;;
    *)   _qs_url="http://127.0.0.1:${QS_PORT}/${_qs_target}" ;;
  esac
  _qs_want_status=200
  _qs_timeout=40
  _qs_patterns=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --status)   _qs_want_status="$2"; shift 2 ;;
      --timeout)  _qs_timeout="$2"; shift 2 ;;
      --contains) _qs_patterns="$_qs_patterns
$(printf '%s' "$2" | sed 's/[][\.*^$(){}?+|/]/\\&/g')"; shift 2 ;;
      --matches)  _qs_patterns="$_qs_patterns
$2"; shift 2 ;;
      --json)
        _qs_key="${2%%=*}"; _qs_val="${2#*=}"
        _qs_patterns="$_qs_patterns
\"$_qs_key\"[[:space:]]*:[[:space:]]*\"?$_qs_val\"?"
        shift 2 ;;
      *) qs_fail "qs_wait_http: unknown option $1" ;;
    esac
  done

  _qs_deadline=$(( $(date +%s) + _qs_timeout ))
  while [ "$(date +%s)" -lt "$_qs_deadline" ]; do
    sleep 1
    if _qs_get "$_qs_url"; then
      if [ "$_qs_status" != "$_qs_want_status" ]; then
        _qs_last="HTTP $_qs_status, wanted $_qs_want_status. Body: $(head -c 300 "$QS_BODY")"
        continue
      fi
      # Without grep every pattern would fail to match and the check would
      # report a body mismatch that never happened. A wrong verdict is worse
      # than a loud one.
      command -v grep >/dev/null 2>&1 || \
        qs_fail "qs_wait_http needs grep, which this image does not have"
      _qs_ok=1
      _qs_missing=""
      _qs_saved_ifs="$IFS"
      IFS='
'
      for _qs_pat in $_qs_patterns; do
        [ -z "$_qs_pat" ] && continue
        if ! grep -Eq -- "$_qs_pat" "$QS_BODY"; then
          _qs_missing="$_qs_pat"
          _qs_ok=0
          break
        fi
      done
      IFS="$_qs_saved_ifs"
      if [ "$_qs_ok" = "1" ]; then
        return 0
      fi
      _qs_last="HTTP $_qs_status but the body does not match /$_qs_missing/. Body: $(head -c 300 "$QS_BODY")"
    fi
  done
  _qs_log_tail
  qs_fail "$_qs_url never answered as expected after ${_qs_timeout}s. Last attempt: $_qs_last"
}
# ---- end quickstarted check helpers ---------------------------------------
"""


def port_base(task_name: str) -> int:
    """A stable port range per task, so two tasks in one suite do not collide.

    Derived from the name rather than random, because a port that changes
    between runs makes a failure harder to reproduce by hand.
    """
    return _PORT_BASE + zlib.crc32(task_name.encode("utf-8")) % _PORT_SPAN


def prelude_for(task_name: str) -> str:
    return f'QS_PORT_BASE={port_base(task_name)}\n{PRELUDE}'
