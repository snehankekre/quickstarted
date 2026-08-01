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
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from .agents.registry import AGENTS, build_agent
from .config import ConfigError, load_config
from .docs import AFFORDANCE_POLICIES, DocsClient
from .exec import (
    ExecutorError,
    available_backends,
    make_executor,
    needs_host_proxy,
    resolve_backend,
)
from .net.proxy import EgressProxy
from .pricing import PriceBook
from .report import console_summary, markdown_report, markdown_suite_report, suite_summary
from .results import write_json, write_junit
from .run import EVIDENTIAL
from .schema import SCHEMA_LINE, TASK_SCHEMA
from .suite import run_suite
from .task import TaskError, load_task
from .trace import Trace

_LEGACY_DIR = "journeys"


def _resolve_paths(paths) -> list[str]:
    """Accept pre-0.3 `journeys/` paths, loudly.

    0.3.0 renamed the directory to `tasks/`. A pinned CI config should keep
    working for one minor version instead of dying on 'no such file', but it
    should also say so every time, because the shim goes away in 0.4.
    """
    resolved = []
    for path in paths:
        given = Path(path)
        if not given.exists() and given.parts[:1] == (_LEGACY_DIR,):
            moved = Path("tasks", *given.parts[1:])
            if moved.exists():
                print(
                    f"warning  {path}: 'journeys/' was renamed to 'tasks/' in "
                    f"0.3.0. Reading {moved} instead; this fallback is removed "
                    f"in 0.4.0.",
                    file=sys.stderr,
                )
                resolved.append(str(moved))
                continue
        resolved.append(path)
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
    for path in _resolve_paths(args.tasks):
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


def cmd_doctor(args) -> int:
    """What this machine can actually enforce, before you trust its numbers."""
    backends = available_backends()
    chosen = resolve_backend("auto")
    print("quickstarted doctor")
    print(f"  backends available: {', '.join(backends)}")
    print(f"  auto would choose:  {chosen}")
    if chosen == "local":
        print()
        print("  WARNING: no enforced backend on this machine.")
        print("  Commands would run as you, on your filesystem, with your network,")
        print("  and an agent could read docs pages without the trace recording it.")
        print("  Fine for tasks you wrote; do not benchmark other people's")
        print("  projects this way. Install Docker, or run on macOS.")
    prices = PriceBook.load(args.prices)
    print(f"  price book loaded:  {'yes' if prices else 'no (token counts only)'}")
    from .agents.claude import KEY_ENV, resolve_api_key

    print(f"  {KEY_ENV}: {'set' if resolve_api_key() else 'not set'}")
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


def cmd_run(args) -> int:
    tasks = []
    invalid = False
    for path in _resolve_paths(args.tasks):
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

    prices = PriceBook.load(args.prices)
    out_root = Path(args.out) if args.out else None

    def emit(result) -> None:
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
    p_validate.add_argument("tasks", nargs="+")
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
    p_run.add_argument("tasks", nargs="+")
    p_run.add_argument(
        "--agent", default="replay",
        help=f"one of: {', '.join(sorted(AGENTS))} (default: replay)",
    )
    p_run.add_argument("--model", default="", help="model override for LLM agents")
    p_run.add_argument("--out", default="", help="directory for traces and reports")
    p_run.add_argument("--junit", default="", help="write JUnit XML to this path")
    p_run.add_argument("--prices", default="", help="path to a price book JSON file")
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
