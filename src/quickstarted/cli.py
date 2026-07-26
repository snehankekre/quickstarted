"""quickstarted CLI.

    quickstarted validate journeys/*.yaml
    quickstarted run journeys/foo.yaml --agent replay
    quickstarted run journeys/*.yaml --agent claude --repeat 5 --out results/
    quickstarted doctor

Exit code 0 when every journey passed every evidential attempt, 1 otherwise,
so CI can gate on it. Runs that produced no evidence (rate limits, budget
exhaustion, harness bugs) do not silently turn into failures; use
`--strict-inconclusive` if you would rather they did.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agents.registry import AGENTS, build_agent
from .docs import AFFORDANCE_POLICIES, DocsClient
from .exec import available_backends, resolve_backend
from .journey import JourneyError, load_journey
from .pricing import PriceBook
from .report import console_summary, markdown_report, markdown_suite_report, suite_summary
from .results import write_json, write_junit
from .run import EVIDENTIAL
from .suite import run_suite


def cmd_validate(args) -> int:
    failures = 0
    for path in args.journeys:
        try:
            journey = load_journey(path)
        except JourneyError as exc:
            print(f"INVALID  {exc}")
            failures += 1
        else:
            modes = "replay+agent" if journey.replay else "agent-only"
            print(f"ok       {path} ({journey.name}, {modes})")
            for host in journey.network_conflicts:
                print(
                    f"warning  {host} is declared a docs host, so the shell "
                    f"cannot reach it; installs that need it will fail. "
                    f"Add it under network.allow if that is intended."
                )
            for host in journey.attribution_gaps:
                print(
                    f"note     {host} is both a docs host and network-allowed, "
                    f"so pages the shell reads there are not recorded."
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
        print("  Fine for journeys you wrote; do not benchmark other people's")
        print("  projects this way. Install Docker, or run on macOS.")
    prices = PriceBook.load(args.prices)
    print(f"  price book loaded:  {'yes' if prices else 'no (token counts only)'}")
    from .agents.claude import KEY_ENV, resolve_api_key

    print(f"  {KEY_ENV}: {'set' if resolve_api_key() else 'not set'}")
    return 0


def cmd_run(args) -> int:
    journeys = []
    invalid = False
    for path in args.journeys:
        try:
            journeys.append(load_journey(path))
        except JourneyError as exc:
            print(f"INVALID  {exc}")
            invalid = True
    if not journeys:
        return 1

    backend = resolve_backend(args.backend)
    if backend == "local" and not args.allow_unenforced:
        print(
            "REFUSING: no enforced execution backend is available, so the docs "
            "allowlist and the page-read record cannot be guaranteed.\n"
            "Run `quickstarted doctor` for details, or pass --allow-unenforced if "
            "you wrote the journeys and the project under test yourself.",
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
            out_dir = out_root / result.journey.name
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
        journeys,
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
            "Test whether an AI agent can complete your quickstart from your docs alone."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_validate = sub.add_parser("validate", help="validate journey files")
    p_validate.add_argument("journeys", nargs="+")
    p_validate.set_defaults(func=cmd_validate)

    p_doctor = sub.add_parser("doctor", help="report what this machine can enforce")
    p_doctor.add_argument("--prices", default="", help="path to a price book JSON file")
    p_doctor.set_defaults(func=cmd_doctor)

    p_run = sub.add_parser("run", help="run journeys")
    p_run.add_argument("journeys", nargs="+")
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
        help="attempts per journey; >1 turns a verdict into a pass rate",
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
