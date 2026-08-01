# Trace events

> `trace.jsonl`, one JSON object per line, in the order things happened.

The trace is the raw material behind every report. One object per line, each
with `ts` and `type` plus event-specific fields.

```bash
quickstarted run tasks/x.yaml --agent claude --out results/
jq -r 'select(.type == "docs_read") | .url' results/x/trace.jsonl
```

## Lifecycle

| Type | Fields | When |
| --- | --- | --- |
| `run_start` | `task`, `agent`, `backend`, `enforced`, `attempt`, `affordance_policy` | First line |
| `setup` | `command`, `exit_code`, `output` | Per setup command |
| `run_end` | `stop_reason`, `passed`, `classification` | Last line |

## Agent activity

| Type | Fields | When |
| --- | --- | --- |
| `agent_turn` | `turn`, `stop_reason`, `model`, token counts | Per model call |
| `tool_call` | `tool`, `command` or `url` | Before a tool runs |
| `tool_result` | `tool`, `exit_code`, `duration`, `timed_out`, `output` | After `bash` |
| `agent_final` | `text` | The agent's closing summary |
| `api_retry` | `turn`, `attempt`, `sleep`, `error` | A transient fault was retried |

`agent_final` is the agent's own account of what it did. It is recorded and
never scored.

## Documentation

| Type | Fields | When |
| --- | --- | --- |
| `docs_read` | `url`, `chars`, `original_chars`, `truncated`, `from_cache`, `content_hash`, `resolved_to` | A page was read |
| `docs_redirect_followed` | `requested`, `resolved_to` | The page was a client-side redirect |
| `docs_changed` | `url`, `content_hash` | `--refresh` saw different bytes |
| `docs_read_blocked` | `url`, `reason` | Outside the allowlist, robots, or offline |
| `docs_read_error` | `url`, `error` | The read itself failed |
| `affordance_withheld` | `url` | Blocked by `--affordances none` |
| `affordances` | `entrypoint`, `found` | `--probe-affordances` |

One act has one name. The tool the model is offered is `read_docs`, and the
events it writes are `docs_read`, `docs_read_blocked` and `docs_read_error`.
0.4.0 wrote `docs_fetch`, `fetch_blocked` and `fetch_error` for the same three
things; `quickstarted show` and `report` still read those, so a trace from that
release does not render as a blank run, but nothing writes them any more.

`truncated` is worth watching. A page too large to read in one call is an
agent-experience defect in its own right, and `original_chars` tells you how
far past the limit it was.

`docs_redirect_followed` means the requested URL answered with a page whose only
content was a `<meta http-equiv="refresh">`, and the real page was fetched
instead. DuckDB's versioned URLs do this: 938 bytes of HTML that render as 73
characters of "Redirecting...", with the actual documentation at another path.
A browser follows it, so an agent with a browser reads the docs and an agent
without reads nothing, and the harness follows it to keep the two comparable.

The hop is only taken within the same host. A stub pointing elsewhere is left
alone, because reading a page the task never allowlisted is the attribution hole
the proxy exists to close. Both URLs are recorded, so a run never claims to have
read a page it did not get.

## Network policy

| Type | Fields | When |
| --- | --- | --- |
| `egress_allowed` | `host`, `port`, `method`, `path` | The proxy passed a request |
| `egress_blocked` | `host`, `reason`, `method` | The proxy refused one |
| `egress_error` | `host`, `error`, `method` | Upstream connection failed |

`reason` is one of `docs_host_requires_read_docs` (the shell tried to read
documentation), `not_allowlisted` (an unknown host), or
`explicit_network_override` on the allowed side.

Under Docker these come from the proxy sidecar and are merged into the trace
when the run tears down, so ordering against agent events is approximate.

## Success check

| Type | Fields |
| --- | --- |
| `success_check` | `exit_code`, `passed`, `output` |

The only event that determines the verdict.

## Worked example

```bash
# Which pages did the agent read, in order?
jq -r 'select(.type=="docs_read") | .url' trace.jsonl

# Did it try to read docs through the shell?
jq 'select(.type=="egress_blocked" and .reason=="docs_host_requires_read_docs")' trace.jsonl

# What did the last command do before the run failed?
jq -r 'select(.type=="tool_result") | "\(.exit_code) \(.output[0:120])"' trace.jsonl | tail -3

# Tokens per turn.
jq -r 'select(.type=="agent_turn") | "\(.turn) \(.output_tokens)"' trace.jsonl
```
