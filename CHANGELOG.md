# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.3.0] - 2026-07-26

Breaking, and deliberately early. The unit of testing is now a **task**, not a
journey.

### Changed

- **`journey` is now `task`**, everywhere: the `journeys/` directory is
  `tasks/`, `load_journey` is `load_task`, `run_journey` is `run_task`, the
  `Journey` dataclass is `Task`, and `JourneyError` is `TaskError`.
  "Journey" came from analytics funnels and describes the wrong shape. A task
  is a goal plus one exit code, and "can an agent complete this task from your
  docs" is the claim the tool actually tests.
- **`results.json` is schema 2.0**: the `journey` and `journeys` keys are now
  `task` and `tasks`. Nothing else about the document changed, so a 1.0
  consumer needs only that substitution.
- `quickstarted validate` and `quickstarted run` still accept paths under
  `journeys/` and read the matching file in `tasks/`, printing a warning. That
  fallback is removed in 0.4.0.

### Added

- **Per-task container image** (`image:` in a task file). The default
  `python:3.12-slim` has no Node, so a suite could not mix a Python quickstart
  with a JavaScript one; `--image` is one flag for a whole invocation.
  Precedence is task, then `--image`, then the default. The resolved image is
  recorded in `results.json` and printed beside the backend, because a pass
  rate is not comparable across base images.
- `validate` warns when a success script calls `npm`, `npx`, `node`, `pnpm`,
  `yarn`, or `bun` while no image is set, since that check would fail for a
  reason unrelated to the documentation.
- **Six more tasks**, doubling the set to 14 and covering both runtimes: `uv`,
  `django`, `prefect` (Python) and `vite`, `prisma`, `tailwind` (Node).
- Four hosts added to the default network allowlist:
  `release-assets.githubusercontent.com`, where npm packages with prebuilt
  native binaries fetch during install, and the Debian and Ubuntu mirrors, so a
  quickstart that opens with `apt-get install` works. `raw.githubusercontent.com`
  stays out on purpose: projects serve READMEs from it, and a documentation host
  the shell can reach is an attribution hole.

### Fixed

- **Docker workspaces no longer leak into the VM (macOS).** The sandbox root
  came from `tempfile.mkdtemp()`, which on macOS returns a path under
  `/var/folders`. That is not shared with the Docker VM, so `-v` created a
  directory of the same name *inside* the VM and mounted that instead. Runs
  passed, but the host saw an empty workspace, `--keep-sandbox` handed back
  nothing, and cleanup freed no bytes. Found by filling a 19 GB Colima disk with
  132 orphaned workspaces, after which every run failed with `no space left on
  device` and was correctly classified `harness_error`. The root now defaults to
  `~/.quickstarted/sandboxes` on macOS, overridable with
  `QUICKSTARTED_SANDBOX_DIR`, and the mount is probed in both directions at
  startup so a path the daemon cannot see is refused immediately.
- **The workspace starts empty.** `HOME` and `TMPDIR` used to point inside the
  workspace, so `.npm`, `.cache` and `tmp/` were there before the agent ran a
  single command, and every scaffolding tool that requires an empty directory
  refused: `npm create vite@latest .`, `django-admin startproject .`,
  `cargo new`. An agent had to notice and work around a mess the harness made,
  which is measurement noise dressed up as a documentation problem. Under
  `docker` both now live on the container's own filesystem; under `seatbelt` and
  `local` they are siblings of the workspace inside the same sandbox, so the
  kernel policy is unchanged.

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
