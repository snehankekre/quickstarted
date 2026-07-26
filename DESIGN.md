# Design notes

## The one decision everything follows from

Deterministic assertions are the only pass/fail truth. The success script runs
after the agent stops, in the same workspace, and its exit code is the
verdict. LLM judges may eventually classify WHY a run failed; they will never
decide WHETHER it failed. This keeps the tool falsifiable and keeps vendors
(including Anthropic) out of the scoring path.

## Attribution has to be enforced, not requested

Agents act only through the Toolbelt (`bash` + `read_docs`), so every page read
is recorded and failures attribute to a page.

v0.1 stopped there, and that was not enough. The allowlist lived in the
`read_docs` tool while `bash` had unrestricted network access, so any agent
that ran `curl` read documentation the trace never saw. The guarantee held only
while the agent cooperated, which is not a guarantee.

Now all shell traffic leaves through a proxy the harness owns, and
documentation hosts are unreachable from the shell. An attempted `curl` to a
docs host is refused and counted. The set of pages in the report is the set of
pages the agent read.

This creates one deliberate asymmetry: `docs.allow` hosts are readable only via
`read_docs`, and `network.allow` hosts (package registries) are reachable only
from the shell. When a host is genuinely both, PyPI being the obvious case, the
task says so explicitly and installs win. The resulting gap in attribution
is reported alongside the result.

## Backends, and saying which one ran

Three: `docker` (container on an internal network whose only route out is the
proxy sidecar), `seatbelt` (macOS, kernel-enforced, all egress denied except
the proxy port, home directory unreadable), and `local` (nothing enforced).

`local` is refused unless explicitly allowed, every result records which
backend ran and whether it was enforced, and `quickstarted doctor` says what a
machine can do before anyone trusts its numbers. An unenforced result still
tells you something. It just supports a weaker claim, and the claim should
travel with the number.

## A run is a sample; a rate is a measurement

The same docs and model can pass and then fail. `--repeat` produces a pass
rate, and every run is classified. Only `passed` and `docs_gap` are statements
about documentation. Rate limits, exhausted budgets, refusals, and our own bugs
are excluded from both the numerator and the denominator and reported
separately.

A sweep of fifty projects will hit 429s and flaky networks. Reporting those as
failed quickstarts would be a lie that is very easy to tell, and it is the
difference between a benchmark and a leaderboard-shaped rumour.

## Affordances are measured, never scored

Whether a project ships `llms.txt` is a checklist item anyone can `curl`, and
scoring it would be the proxy metric this tool exists to replace. So presence
is recorded as context, with sizes, and the affordance can be *withheld*:
`--affordances none` blocks `llms.txt` and `.md` variants while keeping the
prompt byte-identical. Run both conditions and the difference in pass rate is a
measurement of the affordance itself.

That question is currently argued without data. This is the only shape of tool
that can answer it, because answering it requires running the task.

## Replay mode is the floor, not a feature

Replay (documented commands verbatim, no LLM) is free, deterministic and
CI-friendly, and it defines a floor: if replay fails, agent mode is noise. It
is a weaker `runShell` than a docs-testing framework like Doc Detective
already offers. Sell it as a precondition, and let agent mode carry the
product.

## Trace as the product surface

Everything interesting is an event in the JSONL trace: setup, tool calls, docs
fetches with content hashes, egress decisions, agent turns with token usage,
retries, the success check. `results.json` (schema 1.0) is the stable contract
over those traces. The hosted product is, to a first approximation, storage
plus diffing plus alerting across models and time.

## Cost is reported in tokens

Cached prompt tokens are excluded from `input_tokens` by the API, so summing
that field alone made a run costing 120k cache-read tokens look free. All four
counters are tracked. Dollars appear only when the operator supplies a price
book: vendor rates change, and a stale table baked into a benchmarking tool
would quietly misreport what a sweep costs.

## Known gaps

- Both enforced backends are verified end to end against live daemons. In the
  container the isolation is stronger than Seatbelt's: a direct dial to an IP
  address fails with `Network is unreachable`. The sandbox network has no route
  out at all, so the isolation does not depend on name resolution.
- HTML-to-text is a crude tag stripper, so markdown-native docs read better.
  That is itself a finding worth publishing.
- Concurrency is per-attempt threads, not a scheduler; hosts are rate-limited
  individually but there is no global budget governor.
- No pip/npm cache; every run cold-installs.
- The Gemini adapter is written against the same Toolbelt contract but has not
  been run live; Claude and OpenAI have.
- Nothing distinguishes "the docs are wrong" from "the product is broken". Both
  surface as `docs_gap` and need a human.
