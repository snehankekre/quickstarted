# Changelog

All notable changes to this project are documented here. This project follows
[Semantic Versioning](https://semver.org/).

## [0.6.0] - 2026-08-02

The release that goes back and asks whether the tasks in this repository were
testing the quickstarts they named. Mostly they were not, and two of the
reasons were bugs in the harness rather than in anybody's documentation.

### Fixed

- **HTML to text ran adjacent code blocks together.** The extractor joined text
  nodes with no separator, so a page offering npm/yarn/pnpm/bun in tabs reached
  the agent as `npm create vite@latestbash$ yarn create vite`, and Tailwind's
  install page as `npm create vite@latest my-projectcd my-project`. Block tags
  now end a line, `<pre>` keeps its indentation so a Python sample still runs,
  and a highlighter's per-line spans end a line too: Shiki's `class="line"`,
  which tailwindcss.com uses, and prism-react-renderer's `class="token-line"`,
  which every Docusaurus site uses. Six of the eleven documentation sites
  tested here were affected, which means the harness was scoring its own HTML
  handling as a documentation gap. A blank line inside a sample survives as one
  rather than reading the same as a line ending, adjacent inline `<code>`
  elements no longer run together, and an unbalanced `<pre>` inside a `<script>`
  or `<svg>` no longer leaks verbatim whitespace across the rest of the page.
- **A `wait_http` with no `script` beside it compiled to an empty check**,
  which exits 0 and therefore passed anything at all.

### Added

- **`success.expect_output`** asserts on what the run printed, with `contains`
  and `matches`. Most quickstarts do not end at a file: DuckDB's persistent
  storage example prints a table, Polars' getting started guide ends at
  `print(df_csv)`, Prisma's SQLite quickstart ends at two `console.log` calls.
  A check that could only see the filesystem forced its author to bolt an
  artefact onto the goal, and the task then measured the invention. The harness
  writes what the agent's commands printed to `.quickstarted-session.log` after
  the agent stops and before the check runs; `qs_expect_output` is the shell
  helper behind it, for checks that outgrow the declarative form.

  What goes into that file is the part that matters. The commands themselves
  are excluded, or a heredoc counts as output and a run that writes
  `INSERT INTO test VALUES (42)` into a file and then dies on
  `ModuleNotFoundError` satisfies `contains: "42"`. Output from commands that
  exited non-zero is excluded too, or a stack trace quoting the source line
  counts as the program having printed it. So is `setup` output, which belongs
  to the harness rather than the reader.

  The loader refuses an empty pattern, which `grep -E` matches against any
  non-empty file, and a multi-line one, which `grep` reads as an alternation
  and would silently weaken to an OR. An `expect_output:` or `wait_http:` with
  nothing under it is now an error rather than a key that is silently dropped.

### Changed

- **`docs.entrypoint` became `docs.path`, an ordered list.** A quickstart is
  rarely one page. FastAPI's install instruction is on `/tutorial/` and its
  first application is on `/tutorial/first-steps/`; a task naming only the
  second measures whether the agent thinks to go looking, and the harness then
  attributes the failure to a page that is missing nothing. In the 0.3.0
  benchmark this was the whole of the FastAPI result: three runs that read only
  first-steps failed, five that also read the index passed, same model and same
  day. `entrypoint` is still accepted as the one-page case. Giving both is an
  error, because which page a reader starts at is the measurement and the
  harness must not guess at it.
- **Every page on the path is offered to the agent**, in the documentation's
  own order, read by `--agent replay`, and checked by `validate --check-urls`.
- **Every task was rewritten so that it names no file the target documentation
  does not name.** `total.txt`, `out.csv`, `out.json`, `fetch.py`, `app.py` and
  `script.py` appear in no project's documentation and are gone. FastAPI's task
  now asserts `main.py`, which is the file the tutorial names in those words.
  Tailwind's points at the CLI installation page instead of the Vite one, whose
  documented step is a watcher this sandbox cannot leave running. Streamlit's
  and uv's old entrypoints were hub pages carrying no commands at all.
- **`quickstarted init` scaffolds a `path`**, and its starter check no longer
  suggests asserting `app.py`.

### Removed

- **The Prefect task.** Its quickstart is a deploy story: log in to Prefect
  Cloud, or start a server and `.serve()`. The task forbade all three and
  substituted an invented flow that summed a file, so it tested roughly the
  first step of the page. A task that fights its own documentation cannot be
  fixed by rewording it.

## [0.5.0] - 2026-08-01

The last of the papercuts, and a documentation site that says what 0.4.0
actually shipped.

### Changed

- **One name for one act: `read_docs`.** The tool the model is offered was
  `read_docs`, the method behind it was `fetch`, and the events they wrote were
  `docs_fetch`, `fetch_blocked` and `fetch_error`. Three words for the same
  thing, and a trace was where a reader met all three. Everything is `read_docs`
  now, and the trace events are `docs_read`, `docs_read_blocked` and
  `docs_read_error`. `Trace.fetched_urls` is `pages_read`, which is the name
  `results.json` already used for the field it fills. `quickstarted show` and
  `report` still read the 0.4.0 event names, so traces already sitting in a
  results directory do not render as blank runs.
- **The task schema reads its budget defaults off the code.** It advertised
  `max_seconds: 900` for a release after the default had moved to 480, and the
  published-copy test passed because the published copy was wrong in the same
  way. A test now compares the schema against the `Budgets` dataclass.
- **`success` carries the exactly-one-of `script`/`file` rule**, which the
  loader has always enforced, so an editor says it before a run does.

### Documentation

- **The site describes 0.4.0.** The composite action listed ten inputs and has
  nineteen. `results.json` gained `interrupted`, `totals.unpriced_models` and a
  per-task `skipped` count, and the reference described none of them, so
  anything written against that page would have read a partial cost total as a
  complete one. `skipped` was missing from the classification table entirely.
  Agent mode still said a price book was the only route to dollars, and the CI
  guide still said schema 1.0.
- `quickstarted show`, `report` and `diff` now appear in the pages where
  somebody would look for them rather than only in the CLI reference, and
  `validate`'s notes are described as notes rather than warnings.
- **A theme that looks like the thing it documents.** Serif prose, mono
  structure, and output the tool printed set on a dark readout panel while
  commands you type stay on paper. That distinction was already in the Markdown
  and nothing had ever drawn it. `[PASS]` and `[FAIL]` are coloured inside those
  panels the way the CLI colours them, with a test that fails if the CLI grows a
  label the site does not know about.

## [0.4.0] - 2026-08-01

The release about the hour between `pip install` and a task you trust, and
about what happens after the run. Most of it exists because a badly written
check does not produce a bad experience; it produces a wrong number, and
nothing in the report says so.

### Added: writing a task

- **`success.file`**, a path to a shell file beside the task, so a check can be
  shellchecked, syntax highlighted and read without counting YAML indentation.
  It is read at load time and never written into the workspace: the workspace is
  the agent's own directory, and a success script it could read is an answer key.
  A test makes an agent grep for its own criteria and find nothing.
- **`success.serve` and `success.wait_http`**, a declarative form for the
  commonest hard check. The harness backgrounds the process, polls, keeps the
  last error, prints the server log when it gives up, and names the reason on
  the last line, which is the line the console summary shows. Four tasks in this
  repo had their own copy of those twenty lines, and the copies were where the
  `if !` idiom got dropped. The FastAPI check went from 53 lines to 20, and
  Streamlit's from 37 to 9.
- **`qs_serve`, `qs_wait_http` and `qs_fail`** are defined for every success
  script. The declarative form generates calls to them, so a check that outgrows
  the schema drops to shell without losing anything, which is what
  `tasks/checks/fastapi.sh` does to keep supporting both documented ways of
  serving.
- **`quickstarted check TASK --sandbox PATH`** re-runs only the success script
  against a workspace a `--keep-sandbox` run left behind. No model, no key, and
  the same backend that judged the run: about a second per iteration instead of
  a paid run per iteration. `--show` prints the script the harness will run.
- **`quickstarted init URL`** scaffolds a task from a documentation URL, with
  the allowlist derived from the host and a schema line for editor completion.
  The result validates as written.
- **`quickstarted schema`** prints a JSON Schema for task files, published at
  `snehankekre.com/quickstarted/task-schema.json`. A test fails if the published
  copy drifts from the code.
- **`quickstarted.yaml`** for repo defaults, `run:` for flags and `tasks:` for
  task fields. A flag you typed beats `run:`; a task file beats `tasks:`. It
  refuses `agent`, `model`, `repeat` and `affordances`, because a file that
  quietly changed which model served a task would make two runs incomparable
  for a reason invisible in the command you typed.
- **`validate` warnings for the mistakes that corrupt a pass rate**: a check
  requiring an environment directory neither `setup` nor `replay` creates, which
  is how a working run gets recorded as a documentation failure; a check that
  can exit non-zero while printing nothing; and a task with no `replay` block.
  `--check-urls` also fetches each entrypoint, so a dead link surfaces before a
  sweep pays for it.

### Added: getting to a first result

- **Three example tasks ship inside the wheel** (`httpx`, `streamlit`, `vite`),
  with `quickstarted examples` and `--example NAME`. `tasks/` is in the sdist
  only, so a `pip install` user did not have the file the documentation told
  them to start with. `uvx quickstarted run --example streamlit --agent replay`
  now produces a real result with nothing installed and no key, which also
  makes the tool usable from a JavaScript or Go project without adopting a
  Python environment.
- **`run` and `validate` find tasks on their own.** With no paths they read
  `tasks/`, or the current directory. A path may be a file, a directory, or a
  glob, and globs are expanded internally as well as by the shell, because
  PowerShell hands `tasks/*.yaml` through literally and the documented command
  died on Windows with 'no such file'. Validating nothing exits 3 rather than 0,
  so a CI job in the wrong directory stops reporting success.
- **A run says what it is doing while it does it.** Each documentation page as
  the agent reads it, each blocked egress attempt, and the check's exit code.
  `--repeat 5 --workers 3` printed nothing for minutes while spending money,
  and a slow model looked exactly like a hung container. `--verbose` adds every
  shell command, `--quiet` restores the old behaviour, and lines are labelled
  with task and attempt when more than one is in flight.
- **`doctor` covers the machine, not just Anthropic.** All three providers with
  the environment variable each key came from, whether the Docker daemon
  answers and the default image is pulled, which config file is in effect, and
  whether the tasks it can find parse.

### Added: reading a run back

- **`quickstarted diff before/results.json after/results.json`**: pass rate
  delta per task, suspect pages that appeared or cleared, classification
  changes, and a two-sided Fisher exact test on every comparison. Exact rather
  than approximate because the samples are tiny and `math.comb` costs nothing.
  When no possible outcome at these sample sizes could have reached
  significance it says so, which is more useful than a verdict: three attempts
  a side can never clear p<0.05, and four can. Runs served by different models
  are reported as not comparable rather than subtracted.
  `--fail-on-regression` exits 1 when a rate dropped by more than noise.
- **`quickstarted show`** renders a `trace.jsonl` as a transcript, and
  **`quickstarted report`** turns a results directory into one self-contained
  HTML page: pass rates, every gap with the check's own output and the page the
  agent was on, transcripts folded away. No external stylesheet, script or
  font, because a report that fetches anything renders differently for whoever
  you sent it to.
- **`--max-spend`** stops a sweep at a dollar ceiling, checked between runs and
  never predicted ahead of one.
- **`pip install "quickstarted[prices]"`** prices runs from `genai-prices`, so
  dollars appear without a hand-written price book. No table of rates lives in
  this repository, which is the rule that made the price book explicit in the
  first place; a price book you supply still wins. `--refresh-prices` asks for
  current rates before pricing. The extra needs Python 3.10, which genai-prices
  requires and this package does not.
- **`--github-summary`** appends the markdown report to `$GITHUB_STEP_SUMMARY`,
  and a documentation gap emits `::error file=tasks/foo.yaml` with the check's
  message and the last page read, so it lands beside the diff instead of inside
  a log. The composite action gains the inputs it was missing: `image`,
  `cache-dir`, `prices`, `max-spend`, `probe-affordances`,
  `strict-inconclusive`, `allow-unenforced`, `github-summary`, and
  `working-directory`.

### Changed

- **Exit codes distinguish what went wrong**, because "your quickstart is
  broken" and "somebody else's API returned 429" need different people to do
  different things: 0 passed, 1 a documentation gap, 2 no evidence at all, 3
  usage, 130 interrupted. `--strict-inconclusive` collapses 2 into 1.
- **An agent-only task under `--agent replay` is `skipped`, not a harness
  error.** A suite of them reported "no evidence" on every push, which reads
  like the tool is broken rather than like there was nothing to run. Skips stay
  out of the discarded counts and appear in JUnit as `<skipped/>`.
- **An interrupted sweep keeps the runs that finished.** `results.json` was
  assembled only after the last run landed, so Ctrl-C on a forty-minute sweep
  discarded everything it had already paid for. The document now records
  `interrupted`, and the exit code is 130 so a wrapper can tell an abandoned
  sweep from a red one.
- **The `journeys/` path fallback is gone**, as 0.3.0 said it would be. A path
  under `journeys/` now fails and the error names the `tasks/` path to use
  instead. The deprecated `journeys` input on the Action is removed with it.
- Unknown keys under `success` are now an error, matching `budgets` and
  `network`, so a typo fails loudly instead of being ignored.
- `budgets.max_seconds` defaults to 480 rather than 900. Every task in this repo
  sets 420 or 480, so the old default quietly bought a task that omitted budgets
  fifteen minutes of agent time.
- `--out` writes every attempt at the same depth when `--repeat` is above one.
  Attempt 1 used to sit a level above the rest, so anything walking the tree
  needed a special case for it.

### Fixed

- **The seatbelt backend could not run any task that starts a server.** The
  profile's `(allow network-bind (local ip "localhost:*"))` never matched, so
  the bind was refused outright, and polling was denied separately because only
  the proxy port was reachable. Binding now uses `"*:*"`, with inbound and
  outbound allowed on loopback only. Remote egress stays denied, verified
  directly: a TCP dial to a literal IP and an HTTP request to a remote host are
  both refused, so documentation hosts remain unreachable from the shell.
- **Six tasks in this repo could still fail in silence**, which 0.3.1 believed
  it had finished. `prisma` and `vite` actually did it during a replay sweep,
  reporting a documentation page with no reason to go and read it. Every shell
  assertion in `django`, `duckdb`, `polars`, `prisma`, `vite` and
  `quickstarted-quickstart` now names what it saw.
- **A skipped run was still scored.** Its success check ran anyway, so a task
  whose assertions happen to hold in an empty workspace reported `passed`
  having done nothing at all.
- **A model with no published price was dropped from the cost in silence**, so a
  two-model sweep could report one model's spend as the whole figure. The
  summary, the markdown report and `results.json` now name what is excluded.
  Not hypothetical: neither the bundled nor the live genai-prices data prices
  `claude-opus-5`, this tool's default model.

## [0.3.1] - 2026-07-27

A failure that cannot be diagnosed is barely a failure. This release is about
making every one of them say what it saw.

### Added

- `quickstarted run` flags a success check that printed nothing:

  ```
    success check exit code: 1
    note: the check printed nothing, so this failure cannot be diagnosed.
  ```

  A `docs_gap` names the page the agent was reading. Without check output it
  names a page and no reason, and sends the reader off to a page that may be
  perfectly fine.

### Changed

- Every task in this repo now names the assertion that failed. Six of them could
  previously exit 1 in silence, including `uv-quickstart`, where a run that read
  four pages of documentation and then failed said nothing about why. They now
  report lines like `check failed: httpx is not a dependency in pyproject.toml`.
- `guides/writing-tasks.md` shows the `fail()` pattern the tasks use.

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

- **Client-side redirects are followed.** DuckDB answers its own versioned doc
  URLs with 938 bytes of HTML that render as 73 characters of "Redirecting...",
  naming the real page in a `<meta http-equiv="refresh">`. The fetcher handed
  those 73 characters to the agent as though they were documentation, so the
  duckdb task was measuring recovery from an empty page. A browser follows the
  refresh, so an agent with one reads the docs and an agent without reads
  nothing; following it keeps the two comparable. The hop is taken only within
  the same host, since a stub pointing elsewhere would read a page the task
  never allowlisted, and both URLs land in the trace as
  `docs_redirect_followed`. The same entrypoint now yields 21,659 characters.
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
