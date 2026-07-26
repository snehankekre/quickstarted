# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-07-26

The v0.1 harness could be talked out of its own guarantees: the docs allowlist
lived in the `read_docs` tool, so any agent that ran `curl` read pages the
trace never saw, and commands ran unconfined on the host. This release makes
the boundary real and makes the output publishable.

### Added

- **Execution backends** (`quickstarted.exec`): `docker`, `seatbelt` (macOS), and
  `local`. `auto` prefers an enforced backend. `quickstarted run` refuses the
  unenforced one unless `--allow-unenforced` is given. Both enforced backends
  are verified against live daemons, including tests asserting that a direct
  connection bypassing the proxy fails.
- **Egress proxy** (`quickstarted.net`): all shell traffic leaves through a
  harness-owned proxy. Documentation hosts are unreachable from the shell, so
  the recorded set of pages read is complete; attempts to bypass are counted.
  `network.allow` in a journey names hosts a shell may reach for installs.
- **Run classification**: `passed`, `docs_gap`, `budget_exhausted`,
  `infra_error`, `harness_error`, `agent_refusal`. Only the first two are
  evidence about documentation. The rest are excluded from pass rates, and
  reported separately.
- **Pass rates**: `--repeat N` and `--workers N`. A single run is one sample,
  and the rate over several is the number worth reading.
- **Affordance policy**: `--affordances all|none` withholds `llms.txt` and
  `.md` variants so the same journey can be run both ways and the difference
  measured. `--probe-affordances` records what exists. Never scored.
- **Docs cache and politeness**: `--cache-dir`, `--refresh` (flags content
  that changed between runs), `--offline`, `--rate-limit`, `--ignore-robots`.
  Truthful User-Agent, robots.txt honoured by default.
- **Machine-readable output**: versioned `results.json` (schema 1.0) and
  `--junit` XML, where a docs gap is a failure and an infrastructure problem is
  an error.
- **More agents**: `openai` and `gemini` adapters alongside `claude`, sharing
  one prompt so cross-model numbers compare like with like. Neither assumes a
  default model. Token counts are normalised across vendors: OpenAI and Google
  report a prompt total that includes cached tokens while Anthropic excludes
  them, so adapters subtract the overlap and the four counters never bill the
  same token twice.
- **Retries** with exponential backoff on transient upstream faults. Every wait
  lands in the trace instead of being absorbed silently by the SDK.
- **Token budgets** (`budgets.max_tokens`) and optional cost estimation from a
  price book you supply (`--prices`). No prices ship with the tool.
- `quickstarted doctor`, reporting what this machine can enforce.
- Tests: proxy policy, Seatbelt confinement, classification, statistics,
  caching, robots, and the affordance ablation.

### Changed

- Cached prompt tokens are counted. Previously a run costing ~120k cache-read
  tokens reported "22 in" and looked free.
- The Claude adapter defaults to `claude-opus-5` and records the exact model
  the API served, since an alias can change under a benchmark.
- Agents are told what `setup` already did, so they stop rebuilding a
  virtualenv that exists.
- Journeys no longer list package registries under `docs.allow`; `validate`
  warns when they do, because the proxy will refuse `pip`.

### Fixed

- `Trace` is thread-safe; the proxy appends from its own threads.

## [0.1.0] - 2026-07-24

Initial release: journey spec, replay and Claude agent modes, sandboxed
execution, docs fetch with attribution, deterministic scoring, CLI and
GitHub Action.
