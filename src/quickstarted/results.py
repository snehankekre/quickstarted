"""Machine-readable results: a versioned JSON document and JUnit XML.

`SCHEMA_VERSION` is a promise. The hosted product, the benchmark report, and
anyone's CI dashboard all parse this document, so fields get added but not
repurposed, and the version goes up when that stops being true.
"""

from __future__ import annotations

import json
import platform
import socket
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

from ._version import __version__
from .pricing import PriceBook
from .run import PASSED, SKIPPED, RunResult
from .suite import SuiteResult

#: 2.0 renamed the `journey`/`journeys` keys to `task`/`tasks`. Nothing else
#: about the document changed, so a 1.0 consumer needs only that substitution.
SCHEMA_VERSION = "2.0"


def _run_document(run: RunResult) -> dict:
    return {
        "task": run.task.name,
        "attempt": run.attempt,
        "agent": run.agent_name,
        "model_reported": run.model_reported,
        "classification": run.classification,
        "passed": run.passed,
        "evidential": run.evidential,
        "stop_reason": run.outcome.stop_reason,
        "turns": run.outcome.turns,
        "duration_seconds": round(run.duration, 2),
        "backend": run.backend,
        "enforced": run.enforced,
        "image": run.image,
        "docs_pages_read": run.trace.fetched_urls(),
        "suspect_page": run.suspect_page,
        "docs_bypass_attempts": run.bypass_attempts,
        "success_check": (
            None
            if run.score is None
            else {"exit_code": run.score.exit_code, "output": run.score.output[-2000:]}
        ),
        "tokens": {
            "input": run.outcome.input_tokens,
            "output": run.outcome.output_tokens,
            "cache_write": run.outcome.cache_write_tokens,
            "cache_read": run.outcome.cache_read_tokens,
        },
    }


def suite_document(suite: SuiteResult, prices: PriceBook | None = None) -> dict:
    prices = prices or PriceBook()
    tasks = []
    for stat in suite.stats:
        tasks.append(
            {
                "task": stat.task,
                "agent": stat.agent,
                "attempts": stat.attempts,
                "passes": stat.passes,
                "evidential_runs": len(stat.evidential),
                "pass_rate": stat.pass_rate,
                "discarded": stat.discarded,
                "skipped": stat.skipped,
                "models_reported": stat.models_seen,
                "suspect_pages": stat.suspect_pages,
                "tokens": stat.tokens(),
                "estimated_cost_usd": stat.cost(prices),
                "runs": [_run_document(r) for r in stat.runs],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "quickstarted_version": __version__,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "hostname": socket.gethostname(),
            "backend": suite.backend,
        },
        "repeat": suite.repeat,
        "duration_seconds": round(suite.duration, 2),
        # A partial sweep is still evidence, but a reader comparing two
        # documents needs to know that one of them stopped early.
        "interrupted": suite.interrupted,
        "totals": {
            "runs": len(suite.runs),
            "tokens": suite.tokens(),
            "estimated_cost_usd": suite.cost(prices),
            # Named so a consumer can tell a complete total from a partial one.
            "unpriced_models": list(suite.unpriced_models(prices)),
        },
        "tasks": tasks,
    }


def write_json(suite: SuiteResult, path: str | Path, prices=None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(suite_document(suite, prices), indent=2) + "\n", encoding="utf-8"
    )


def junit_xml(suite: SuiteResult) -> str:
    """JUnit XML so existing CI reporters can render a run with no new tooling."""
    suites = ET.Element("testsuites", name="quickstarted")
    total_failures = total_errors = total_tests = 0
    for stat in suite.stats:
        element = ET.SubElement(
            suites,
            "testsuite",
            name=stat.task,
            tests=str(stat.attempts),
        )
        failures = errors = 0
        for run in stat.runs:
            case = ET.SubElement(
                element,
                "testcase",
                classname=f"quickstarted.{stat.task}",
                name=f"{stat.agent} attempt {run.attempt}",
                time=f"{run.duration:.2f}",
            )
            if run.classification == PASSED:
                continue
            if run.classification == SKIPPED:
                # JUnit has a word for this, and it is not "error".
                ET.SubElement(
                    case, "skipped", message=run.outcome.detail or "not run in this mode"
                )
                continue
            if run.evidential:
                failures += 1
                node = ET.SubElement(
                    case, "failure", type=run.classification,
                    message=(
                        "success check exit "
                        f"{run.score.exit_code if run.score else 'n/a'}"
                    ),
                )
                detail = [f"stop reason: {run.outcome.stop_reason}"]
                if run.suspect_page:
                    detail.append(f"last docs page read: {run.suspect_page}")
                if run.score:
                    detail.append(run.score.output[-1000:])
                node.text = "\n".join(detail)
            else:
                # Not a docs failure: infrastructure, budget, or our own bug.
                errors += 1
                node = ET.SubElement(
                    case, "error", type=run.classification,
                    message=run.outcome.detail or run.classification,
                )
                node.text = run.outcome.detail
        element.set("failures", str(failures))
        element.set("errors", str(errors))
        total_failures += failures
        total_errors += errors
        total_tests += stat.attempts
    suites.set("tests", str(total_tests))
    suites.set("failures", str(total_failures))
    suites.set("errors", str(total_errors))
    suites.set("time", f"{suite.duration:.2f}")
    return ET.tostring(suites, encoding="unicode")


def write_junit(suite: SuiteResult, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(junit_xml(suite) + "\n", encoding="utf-8")
