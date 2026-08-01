"""quickstarted CLI.

    quickstarted validate tasks/*.yaml
    quickstarted run tasks/foo.yaml --agent replay
    quickstarted run tasks/*.yaml --agent claude --repeat 5 --out results/
    quickstarted doctor

Exit code 0 when every task passed every evidential attempt, 1 otherwise,
so CI can gate on it. Runs that produced no evidence (rate limits, budget
exhaustion, harness bugs) do not silently turn into failures; use
`--strict-inconclusive` if you would rather they did.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from . import examples
from .agents.registry import AGENTS, build_agent
from .config import ConfigError, load_config
from .diff import DiffError, compare, format_diff, load_results
from .docs import AFFORDANCE_POLICIES, DocsClient
from .exec import (
    ExecutorError,
    available_backends,
    make_executor,
    needs_host_proxy,
    resolve_backend,
)
from .net.proxy import EgressProxy
from .pricing import PriceBook, refresh_live_prices
from .report import console_summary, markdown_report, markdown_suite_report, suite_summary
from .results import write_json, write_junit
from .run import EVIDENTIAL
from .schema import SCHEMA_LINE, TASK_SCHEMA
from .suite import run_suite
from .task import TaskError, load_task
from .trace import Trace

_LEGACY_DIR = "journeys"


#: Where tasks live when nobody says. Checked in order.
_DEFAULT_DIRS = ("tasks", ".")


def _expand(path: str) -> list[str]:
    """One argument to the task files it names.

    A directory becomes the task files in it, and a glob is expanded here as
    well as by the shell. PowerShell does not expand `tasks/*.yaml` before
    argv, so the documented command failed on Windows with 'no such file'.
    """
    given = Path(path)
    if given.is_dir():
        found = sorted(str(p) for p in given.glob("*.yaml"))
        if not found:
            print(f"warning  {path}/ contains no .yaml task files", file=sys.stderr)
        return found
    if any(char in path for char in "*?[") and not given.exists():
        return sorted(str(p) for p in Path().glob(path))
    return [path]


def _discover() -> list[str]:
    """What to run when the command named nothing."""
    for directory in _DEFAULT_DIRS:
        found = sorted(str(p) for p in Path(directory).glob("*.yaml"))
        if found:
            return found
    return []


def _resolve_paths(paths) -> list[str]:
    """Turn CLI arguments into task file paths.

    The `journeys/` fallback that 0.3.0 added is gone, as 0.3.0 said it would
    be. A config still pinned to that directory now gets 'no such file', which
    the message below points at `tasks/`.
    """
    if not paths:
        found = _discover()
        if not found:
            print(
                "no task files given, and none found in tasks/ or the current "
                "directory.\nWrite one with `quickstarted init <docs-url>`, or "
                "try `quickstarted run --example httpx --agent replay`.",
                file=sys.stderr,
            )
        return found
    resolved = []
    for path in paths:
        given = Path(path)
        if not given.exists() and given.parts[:1] == (_LEGACY_DIR,):
            print(
                f"warning  {path}: 'journeys/' was renamed to 'tasks/' in 0.3.0 "
                f"and the fallback was removed in 0.4.0. Use "
                f"tasks/{'/'.join(given.parts[1:])}.",
                file=sys.stderr,
            )
        resolved.extend(_expand(path))
    return resolved


def _check_entrypoint(task, docs) -> None:
    """Ask whether the documentation is actually reachable, before a paid run.

    A typo in an entrypoint costs a whole sweep otherwise: the agent is pointed
    at a 404, reads nothing, fails, and the run is classified as a documentation
    gap because from the harness's side that is exactly what it looks like.
    """
    if not docs.robots_allows(task.docs_entrypoint):
        print(
            f"warning  {task.docs_entrypoint} is disallowed by robots.txt, so "
            f"the agent will be refused it. Use --ignore-robots only if the "
            f"documentation is yours."
        )
        return
    try:
        result = docs.get(task.docs_entrypoint)
    except Exception as exc:
        print(f"warning  {task.docs_entrypoint} could not be fetched: {exc}")
        return
    if result.blocked_reason:
        print(f"warning  {task.docs_entrypoint} was blocked: {result.blocked_reason}")
    elif not result.text.strip():
        print(f"warning  {task.docs_entrypoint} fetched but had no readable text")
    elif result.followed_from:
        print(f"note     {task.docs_entrypoint} redirects to {result.url}")


def cmd_validate(args) -> int:
    failures = 0
    docs = DocsClient(offline=False) if args.check_urls else None
    paths = _task_paths(args)
    if not paths:
        # Exiting 0 here would let a CI job that runs in the wrong directory
        # report success for validating nothing.
        return 3
    for path in paths:
        try:
            task = load_task(path, args.task_defaults)
        except TaskError as exc:
            print(f"INVALID  {exc}")
            failures += 1
        else:
            modes = "replay+agent" if task.replay else "agent-only"
            print(f"ok       {path} ({task.name}, {modes})")
            for directory in task.unprepared_env_paths:
                print(
                    f"warning  the success check requires {directory}/bin/, which "
                    f"neither setup nor the replay commands create. Does the "
                    f"documentation promise that path? An agent that names its "
                    f"environment differently fails a check it should have "
                    f"passed, and the pass rate is wrong rather than low."
                )
            if task.can_fail_silently:
                print(
                    f"warning  {task.name}'s success check can exit non-zero "
                    f"without printing anything, so a failure would name a docs "
                    f"page and no reason. Add `|| qs_fail \"what you saw\"`."
                )
            if not task.replay:
                print(
                    f"note     {task.name} has no 'replay' commands, so "
                    f"`--agent replay` reports it as inconclusive rather than "
                    f"running it."
                )
            if docs:
                _check_entrypoint(task, docs)
            for host in task.network_conflicts:
                print(
                    f"warning  {host} is declared a docs host, so the shell "
                    f"cannot reach it; installs that need it will fail. "
                    f"Add it under network.allow if that is intended."
                )
            for host in task.attribution_gaps:
                print(
                    f"note     {host} is both a docs host and network-allowed, "
                    f"so pages the shell reads there are not recorded."
                )
            if task.needs_node and not task.image:
                print(
                    f"warning  {task.name}'s success script calls a Node tool "
                    f"but no 'image' is set, and the default image has no "
                    f"Node. Set image: node:22-slim (or similar)."
                )
    return 1 if failures else 0


#: Every agent that needs credentials, so `doctor` reports on the one you use
#: rather than on the one whose adapter happens to be imported here.
_PROVIDERS = (
    ("claude", "anthropic", "quickstarted.agents.claude"),
    ("openai", "openai", "quickstarted.agents.openai_agent"),
    ("gemini", "google.genai", "quickstarted.agents.gemini_agent"),
)


def _provider_status(module_name: str, sdk: str) -> str:
    import importlib
    import importlib.util

    installed = importlib.util.find_spec(sdk.split(".")[0]) is not None
    adapter = importlib.import_module(module_name)
    key = adapter.resolve_api_key()
    if key:
        source = (
            adapter.KEY_ENV
            if os.environ.get(adapter.KEY_ENV)
            else adapter.FALLBACK_KEY_ENV
        )
        where = f"key from {source}"
    else:
        where = f"no key ({adapter.KEY_ENV} or {adapter.FALLBACK_KEY_ENV})"
    return f"SDK {'installed' if installed else 'missing'}, {where}"


def _docker_report() -> list[str]:
    """Whether Docker can actually serve a run, not merely whether it exists.

    The first agent run otherwise stalls for a minute on a silent `docker pull`
    that looks like a hung harness.
    """
    from .exec import docker as docker_backend

    if not docker_backend.available():
        return ["  docker:             daemon not reachable"]
    lines = ["  docker:             daemon reachable"]
    probe = subprocess.run(
        ["docker", "image", "inspect", docker_backend.DEFAULT_IMAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    if probe.returncode == 0:
        lines.append(f"  default image:      {docker_backend.DEFAULT_IMAGE} pulled")
    else:
        lines.append(
            f"  default image:      {docker_backend.DEFAULT_IMAGE} not pulled; "
            f"the first run will fetch it"
        )
    return lines


def cmd_doctor(args) -> int:
    """What this machine can actually enforce, before you trust its numbers."""
    backends = available_backends()
    chosen = resolve_backend("auto")
    print("quickstarted doctor")
    print(f"  backends available: {', '.join(backends)}")
    print(f"  auto would choose:  {chosen}")
    for line in _docker_report():
        print(line)
    if chosen == "local":
        print()
        print("  WARNING: no enforced backend on this machine.")
        print("  Commands would run as you, on your filesystem, with your network,")
        print("  and an agent could read docs pages without the trace recording it.")
        print("  Fine for tasks you wrote; do not benchmark other people's")
        print("  projects this way. Install Docker, or run on macOS.")
        print()
    for agent, sdk, module_name in _PROVIDERS:
        print(f"  {agent + ':':20}{_provider_status(module_name, sdk)}")
    prices = PriceBook.load(args.prices)
    print(f"  price book:         {'loaded' if prices else 'none (token counts only)'}")
    config = load_config()
    print(f"  config file:        {config.source or 'none'}")
    found = _discover()
    if found:
        print(f"  tasks found:        {len(found)} in {Path(found[0]).parent}/")
        invalid = []
        for path in found:
            try:
                load_task(path, config.tasks)
            except TaskError as exc:
                invalid.append(str(exc))
        for message in invalid:
            print(f"    INVALID {message}")
    else:
        print("  tasks found:        none (try `quickstarted examples`)")
    return 0


_TEMPLATE = """{schema_line}
name: {name}

# The only instruction the agent gets. Describe the outcome in the words a user
# would use, and do not name the API that produces it: an agent handed the
# answer tests nothing.
goal: >
  TODO: state what a reader should end up with after following the quickstart.

docs:
  entrypoint: {entrypoint}
  # Readable only through read_docs, never from the shell, which is what keeps
  # the record of pages read complete. Do not list package registries here.
  allow:
{allow}

# Commands run before the agent starts. The agent is told these ran, so it will
# not rebuild what they created.
setup:
  - python3 -m venv .venv

# Exit code 0 is a pass and nothing else is. Assert what your quickstart already
# promises the reader, and make a failure say what it saw.
success:
  script: |
    set -e
    test -f app.py || qs_fail "no app.py, so the quickstart produced nothing"

# The literal commands your documentation tells a reader to type. Free to run,
# needs no API key, and if these fail no reader stands a chance.
replay:
  - "true"  # TODO: replace with the documented commands
"""

#: Subdomains that name the site rather than the project.
_GENERIC_HOSTS = ("docs", "www", "api", "developer", "dev", "learn", "guide", "help")


def _name_from_host(host: str) -> str:
    """`fastapi.tiangolo.com` is fastapi; `docs.streamlit.io` is streamlit."""
    labels = host.split(".")
    first = labels[0]
    if first not in _GENERIC_HOSTS:
        return first
    return labels[-2] if len(labels) > 1 else first


def cmd_init(args) -> int:
    """Scaffold a task from a documentation URL.

    The alternative is copy-paste from a documentation page, which is how a
    first task acquires a field name that no longer exists.
    """
    parsed = urlparse(args.entrypoint)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        print(f"entrypoint must be an http(s) URL, got {args.entrypoint!r}", file=sys.stderr)
        return 3
    host = parsed.hostname.lower()
    name = args.name or re.sub(r"[^a-z0-9]+", "-", _name_from_host(host)) + "-quickstart"
    path = Path(args.out) if args.out else Path("tasks") / f"{name}.yaml"
    if path.exists() and not args.force:
        print(f"{path} already exists; pass --force to overwrite", file=sys.stderr)
        return 3

    # The bare registrable domain too, so a docs site that links to its own
    # marketing pages does not hand the agent a BLOCKED on the second hop.
    parts = host.split(".")
    hosts = [host] if len(parts) < 3 else [host, ".".join(parts[-2:])]
    body = _TEMPLATE.format(
        schema_line=SCHEMA_LINE,
        name=name,
        entrypoint=args.entrypoint,
        allow="\n".join(f"    - {h}" for h in hosts),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    print(f"wrote {path}")
    print("Next: write the goal and the success check, then")
    print(f"  quickstarted validate {path} --check-urls")
    return 0


def cmd_schema(args) -> int:
    print(json.dumps(TASK_SCHEMA, indent=2))
    return 0


def cmd_check(args) -> int:
    """Re-run only the success script, against a workspace a run kept.

    Developing a check otherwise costs an agent run per iteration, and the
    obvious workaround (`cd` into the kept sandbox and run the script by hand)
    judges it in a different environment from the one that will judge it for
    real: another Python, another PATH, no container.
    """
    try:
        task = load_task(args.task, args.task_defaults)
    except TaskError as exc:
        print(f"INVALID  {exc}", file=sys.stderr)
        return 3
    if args.show:
        print(task.check_script)
        return 0

    sandbox = Path(args.sandbox)
    if not sandbox.is_dir():
        print(
            f"no such workspace: {sandbox}\n"
            f"Run with --keep-sandbox first; the path is printed after the run.",
            file=sys.stderr,
        )
        return 3

    backend = resolve_backend(args.backend)
    proxy = None
    trace = Trace()
    if needs_host_proxy(backend):
        proxy = EgressProxy(
            network_allow=task.network_allow,
            docs_hosts=task.docs_allow,
            explicit_allow=task.network_explicit,
            trace=trace,
        )
        proxy.start()
    try:
        executor = make_executor(
            backend,
            proxy_url=proxy.url if proxy else None,
            network_allow=task.network_allow,
            docs_hosts=task.docs_allow,
            image=task.image or args.image or None,
            trace=trace,
            workspace=sandbox,
        )
    except ExecutorError as exc:
        if proxy:
            proxy.stop()
        print(f"could not start the {backend} backend: {exc}", file=sys.stderr)
        return 3
    try:
        result = executor.run(
            task.check_script,
            timeout=task.budgets.max_command_seconds,
            max_output_chars=task.budgets.max_output_chars,
        )
    finally:
        executor.cleanup()
        if proxy:
            proxy.stop()

    if result.output.strip():
        print(result.output.rstrip())
    verdict = "PASS" if result.exit_code == 0 else "FAIL"
    print(f"[{verdict}] {task.name} check exited {result.exit_code} ({backend})")
    if result.exit_code != 0 and not result.output.strip():
        print(
            "  note: the check printed nothing, so this failure cannot be "
            "diagnosed. Have it say what it saw."
        )
    return 0 if result.exit_code == 0 else 1


def _make_watcher(verbose: bool, show_task: bool):
    """Format trace events as they happen, so a run is not silent while it bills.

    Docs fetches alone answer the question people actually have, which is
    whether anything is still happening: a slow model and a hung container look
    identical when nothing prints for four minutes. `--verbose` adds the shell.
    """
    start = time.monotonic()

    def watch(task_name: str, attempt: int, event) -> None:
        kind = event.type
        if kind == "docs_fetch":
            detail = f"read {event.data.get('url', '')}"
        elif kind == "tool_call" and event.data.get("tool") == "bash":
            if not verbose:
                return
            command = " ".join(str(event.data.get("command", "")).split())
            detail = f"$ {command[:90]}"
        elif kind == "fetch_blocked":
            detail = f"BLOCKED {event.data.get('url', '')}"
        elif kind == "egress_blocked":
            detail = f"blocked from the shell: {event.data.get('host', '')}"
        elif kind == "success_check":
            detail = f"check exited {event.data.get('exit_code')}"
        elif kind == "run_start":
            detail = f"started on {event.data.get('backend')}"
        else:
            return
        where = f"{task_name}#{attempt} " if show_task else ""
        print(f"  [{time.monotonic() - start:5.0f}s] {where}{detail}", flush=True)

    return watch


def cmd_diff(args) -> int:
    """Did the documentation change move the pass rate, or is that noise?"""
    try:
        before = load_results(args.before)
        after = load_results(args.after)
    except DiffError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    delta = compare(before, after)
    print(format_diff(delta))
    if args.fail_on_regression and delta.regressions:
        names = ", ".join(d.task for d in delta.regressions)
        print(f"regression: {names}", file=sys.stderr)
        return 1
    return 0


def cmd_examples(args) -> int:
    """List the tasks that ship with the package."""
    print("Example tasks, runnable without cloning anything:")
    for name in examples.names():
        task = load_task(examples.path_for(name))
        modes = "replay+agent" if task.replay else "agent-only"
        print(f"  {name:12} {task.docs_entrypoint}  ({modes})")
    print()
    print("  quickstarted run --example httpx --agent replay")
    return 0


def _task_paths(args) -> list[str]:
    """The task files this invocation names, by path or by `--example`."""
    if getattr(args, "example", ""):
        try:
            return [str(examples.path_for(args.example))]
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return []
    return _resolve_paths(args.tasks)


def cmd_run(args) -> int:
    tasks = []
    invalid = False
    for path in _task_paths(args):
        try:
            tasks.append(load_task(path, args.task_defaults))
        except TaskError as exc:
            print(f"INVALID  {exc}")
            invalid = True
    if not tasks:
        return 1

    backend = resolve_backend(args.backend)
    if backend == "local" and not args.allow_unenforced:
        print(
            "REFUSING: no enforced execution backend is available, so the docs "
            "allowlist and the page-read record cannot be guaranteed.\n"
            "Run `quickstarted doctor` for details, or pass --allow-unenforced if "
            "you wrote the tasks and the project under test yourself.",
            file=sys.stderr,
        )
        return 1

    if getattr(args, "refresh_prices", False):
        refresh_live_prices()
    prices = PriceBook.load(args.prices)
    out_root = Path(args.out) if args.out else None

    # Running total, so a ceiling can be enforced between runs. Checking after
    # each one rather than predicting the next is the only honest option: what a
    # run costs is not knowable until it has happened.
    spent = [0.0]

    def emit(result) -> None:
        estimate = prices.estimate(result.model_reported or result.agent_name, result.outcome)
        if estimate:
            spent[0] += estimate
        print(console_summary(result))
        if args.keep_sandbox:
            print(f"  sandbox kept at: {result.sandbox_path}")
        if out_root:
            out_dir = out_root / result.task.name
            if result.attempt > 1:
                out_dir = out_dir / f"attempt-{result.attempt}"
            out_dir.mkdir(parents=True, exist_ok=True)
            result.trace.write_jsonl(out_dir / "trace.jsonl")
            (out_dir / "report.md").write_text(
                markdown_report(result), encoding="utf-8"
            )

    docs = DocsClient(
        cache_dir=args.cache_dir or None,
        rate_limit_seconds=args.rate_limit,
        respect_robots=not args.ignore_robots,
        affordances=args.affordances,
        refresh=args.refresh,
        offline=args.offline,
    )

    suite = run_suite(
        tasks,
        agent_factory=lambda: build_agent(args.agent, args.model),
        repeat=args.repeat,
        workers=args.workers,
        backend=args.backend,
        keep_sandbox=args.keep_sandbox,
        image=args.image or None,
        docs=docs,
        probe_affordances=args.probe_affordances,
        on_result=emit,
        on_event=(
            None
            if args.quiet
            else _make_watcher(args.verbose, show_task=args.workers > 1 or len(tasks) > 1)
        ),
        stop_check=(
            (lambda: spent[0] >= args.max_spend) if args.max_spend > 0 else None
        ),
    )

    print(suite_summary(suite, prices))

    if out_root:
        out_root.mkdir(parents=True, exist_ok=True)
        write_json(suite, out_root / "results.json", prices)
        (out_root / "suite.md").write_text(
            markdown_suite_report(suite, prices), encoding="utf-8"
        )
        if args.junit:
            write_junit(suite, args.junit)
        print(f"  results written to {out_root}/")
    elif args.junit:
        write_junit(suite, args.junit)

    if suite.halted_on_spend:
        print(
            f"stopped at --max-spend ${args.max_spend:.2f}; "
            f"${spent[0]:.4f} spent over {len(suite.runs)} run(s)",
            file=sys.stderr,
        )
        return 130
    if suite.interrupted:
        # Conventional for SIGINT, and distinct from "a task failed" so a
        # wrapper script can tell an abandoned sweep from a red one.
        return 130
    if invalid:
        return 1
    inconclusive = [r for r in suite.runs if r.classification not in EVIDENTIAL]
    if inconclusive and args.strict_inconclusive:
        return 1
    return 0 if suite.all_passed else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="quickstarted",
        description=(
            "Test whether an AI agent can complete your quickstart using only your docs."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    # Kept so `quickstarted.yaml` can ask a subcommand for its own defaults
    # without reaching into argparse internals.
    subparsers = {}

    p_validate = sub.add_parser("validate", help="validate task files")
    p_validate.add_argument("tasks", nargs="*")
    p_validate.add_argument(
        "--example", default="", help="validate a packaged example instead"
    )
    p_validate.add_argument(
        "--check-urls", action="store_true",
        help="also fetch each entrypoint, to catch a dead link before a paid run",
    )
    p_validate.set_defaults(func=cmd_validate)
    subparsers["validate"] = p_validate

    p_doctor = sub.add_parser("doctor", help="report what this machine can enforce")
    p_doctor.add_argument("--prices", default="", help="path to a price book JSON file")
    p_doctor.set_defaults(func=cmd_doctor)
    subparsers["doctor"] = p_doctor

    p_init = sub.add_parser("init", help="scaffold a task file from a docs URL")
    p_init.add_argument("entrypoint", help="the documentation page to start from")
    p_init.add_argument("--name", default="", help="task name (default: from the host)")
    p_init.add_argument("--out", default="", help="path to write (default: tasks/<name>.yaml)")
    p_init.add_argument("--force", action="store_true", help="overwrite an existing file")
    p_init.set_defaults(func=cmd_init)
    subparsers["init"] = p_init

    p_schema = sub.add_parser(
        "schema", help="print the task file JSON Schema, for editors and CI"
    )
    p_schema.set_defaults(func=cmd_schema)
    subparsers["schema"] = p_schema

    p_examples = sub.add_parser(
        "examples", help="list the example tasks that ship with the package"
    )
    p_examples.set_defaults(func=cmd_examples)
    subparsers["examples"] = p_examples

    p_diff = sub.add_parser(
        "diff", help="compare two results.json files and say whether the change is real"
    )
    p_diff.add_argument("before")
    p_diff.add_argument("after")
    p_diff.add_argument(
        "--fail-on-regression", action="store_true",
        help="exit 1 when a pass rate dropped by more than noise",
    )
    p_diff.set_defaults(func=cmd_diff)
    subparsers["diff"] = p_diff

    p_check = sub.add_parser(
        "check",
        help="re-run only the success script against a kept sandbox (no model, no cost)",
    )
    p_check.add_argument("task")
    p_check.add_argument(
        "--sandbox", default="",
        help="workspace from an earlier --keep-sandbox run",
    )
    p_check.add_argument(
        "--show", action="store_true",
        help="print the script that would run, helpers included, and stop",
    )
    p_check.add_argument("--backend", default="auto")
    p_check.add_argument("--image", default="")
    p_check.set_defaults(func=cmd_check)
    subparsers["check"] = p_check

    p_run = sub.add_parser("run", help="run tasks")
    p_run.add_argument("tasks", nargs="*")
    p_run.add_argument(
        "--example", default="",
        help="run a task that ships with the package; see `quickstarted examples`",
    )
    p_run.add_argument(
        "--agent", default="replay",
        help=f"one of: {', '.join(sorted(AGENTS))} (default: replay)",
    )
    p_run.add_argument("--model", default="", help="model override for LLM agents")
    p_run.add_argument("--out", default="", help="directory for traces and reports")
    p_run.add_argument("--junit", default="", help="write JUnit XML to this path")
    p_run.add_argument("--prices", default="", help="path to a price book JSON file")
    p_run.add_argument(
        "--refresh-prices", action="store_true",
        help="fetch current rates before pricing, for models newer than the bundled data",
    )
    p_run.add_argument(
        "--max-spend", type=float, default=0.0,
        help="stop the sweep once the estimated cost reaches this many dollars",
    )
    p_run.add_argument(
        "--repeat", type=int, default=1,
        help="attempts per task; >1 turns a verdict into a pass rate",
    )
    p_run.add_argument(
        "--workers", type=int, default=1, help="run this many attempts in parallel"
    )
    p_run.add_argument(
        "--backend", default="auto",
        help="execution backend: auto (default), docker, seatbelt, local",
    )
    p_run.add_argument(
        "--image", default="", help="container image for the docker backend"
    )
    p_run.add_argument(
        "--allow-unenforced", action="store_true",
        help="permit the local backend, whose network policy is advisory only",
    )
    p_run.add_argument(
        "--strict-inconclusive", action="store_true",
        help="exit non-zero when any run produced no evidence",
    )
    p_run.add_argument(
        "--verbose", action="store_true",
        help="also stream every shell command the agent runs",
    )
    p_run.add_argument(
        "--quiet", action="store_true",
        help="print only the per-run summaries, as before 0.4",
    )
    p_run.add_argument(
        "--keep-sandbox", action="store_true",
        help="keep the sandbox directory for inspection",
    )
    p_run.add_argument(
        "--affordances", default="all", choices=list(AFFORDANCE_POLICIES),
        help=(
            "which machine-facing files the agent may read. 'none' withholds "
            "llms.txt and .md variants: run both and compare pass rates to "
            "measure whether the affordance helps"
        ),
    )
    p_run.add_argument(
        "--probe-affordances", action="store_true",
        help="record which machine-facing files exist (context, never scored)",
    )
    p_run.add_argument("--cache-dir", default="", help="content-addressed docs cache")
    p_run.add_argument(
        "--refresh", action="store_true",
        help="re-fetch cached pages and flag any whose content changed",
    )
    p_run.add_argument(
        "--offline", action="store_true", help="use the cache only; never fetch"
    )
    p_run.add_argument(
        "--rate-limit", type=float, default=1.0,
        help="minimum seconds between requests to the same host (default: 1.0)",
    )
    p_run.add_argument(
        "--ignore-robots", action="store_true",
        help="fetch documentation even where robots.txt disallows it",
    )
    p_run.set_defaults(func=cmd_run)
    subparsers["run"] = p_run

    args = parser.parse_args(argv)
    try:
        config = load_config()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    if config:
        _apply_config(subparsers.get(args.command), args, config)
    args.task_defaults = config.tasks
    return args.func(args)


def _apply_config(subparser, args, config) -> None:
    """Let `quickstarted.yaml` supply flags the user did not type.

    A flag the user typed always wins. The comparison is against the parser's
    own default, so passing a value that happens to equal the default is
    indistinguishable from not passing it, which changes nothing.
    """
    if subparser is None:
        return
    for key, value in config.run.items():
        if hasattr(args, key) and getattr(args, key) == subparser.get_default(key):
            setattr(args, key, value)


if __name__ == "__main__":
    sys.exit(main())
