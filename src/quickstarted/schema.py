"""JSON Schema for a task file, and the scaffolding that points editors at it.

A task is YAML with no editor support, so every field name is guessed from the
documentation and typos surface as a loader error at best. With the
`yaml-language-server` line at the top of a task, VS Code and anything else
speaking the language server protocol offer completions and mark unknown keys
as you type.

The schema is generated from this module rather than hand-maintained beside it,
and `tests/test_schema.py` fails if the published copy in `docs/` has drifted.
"""

from __future__ import annotations

import dataclasses

from .task import Budgets

SCHEMA_URL = "https://snehankekre.com/quickstarted/task-schema.json"

#: Read off the dataclass rather than retyped. The schema said `max_seconds`
#: defaults to 900 for a release after the code had moved to 480, and nothing
#: caught it: the published copy is compared against this module, and both were
#: wrong together.
_BUDGET_DEFAULTS = {
    f.name: f.default for f in dataclasses.fields(Budgets)
}

#: The editor hint that makes a task file self-describing.
SCHEMA_LINE = f"# yaml-language-server: $schema={SCHEMA_URL}"

_HOSTNAMES = {
    "type": "array",
    "items": {"type": "string", "pattern": r"^[A-Za-z0-9.-]+$"},
    "description": "Bare hostnames. A hostname matches itself and its subdomains.",
}

TASK_SCHEMA: dict = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": SCHEMA_URL,
    "title": "quickstarted task",
    "description": (
        "A goal an agent should reach using only the target project's "
        "documentation, plus a machine-checkable success assertion."
    ),
    "type": "object",
    "required": ["name", "goal", "docs", "success"],
    "additionalProperties": False,
    "properties": {
        "name": {
            "type": "string",
            "description": "Identifier used in output paths and reports.",
        },
        "goal": {
            "type": "string",
            "description": (
                "The only instruction the agent receives. Describe an outcome "
                "in the words a user would use; naming the API that produces it "
                "hands over the answer."
            ),
        },
        "image": {
            "type": "string",
            "description": (
                "Container image for the docker backend. The default "
                "python:3.12-slim has no Node, Go, or Rust."
            ),
        },
        "docs": {
            "type": "object",
            "required": ["entrypoint"],
            "additionalProperties": False,
            "properties": {
                "entrypoint": {
                    "type": "string",
                    "format": "uri",
                    "pattern": "^https?://",
                    "description": "First page the agent is pointed at.",
                },
                "allow": dict(
                    _HOSTNAMES,
                    description=(
                        "Additional documentation hosts. Readable only through "
                        "read_docs; the shell cannot reach them, which is what "
                        "keeps the record of pages read complete."
                    ),
                ),
            },
        },
        "network": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "allow": dict(
                    _HOSTNAMES, description="Added to the default registry list."
                ),
                "only": dict(
                    _HOSTNAMES, description="Replaces the default registry list."
                ),
            },
        },
        "setup": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Commands run before the agent starts. The agent is told these "
                "ran, so it will not rebuild what they created."
            ),
        },
        "replay": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "The literal commands the documentation tells a reader to type. "
                "Runs with no model and no API key, and stops at the first "
                "failure."
            ),
        },
        "success": {
            "type": "object",
            "additionalProperties": False,
            "description": (
                "What decides the verdict. The harness owns the mechanism; every "
                "criterion is yours."
            ),
            # Exactly one of the two, which is what the loader enforces. Saying
            # it here means the editor says it too, before the run.
            "anyOf": [
                {"required": ["script"], "not": {"required": ["file"]}},
                {"required": ["file"], "not": {"required": ["script"]}},
            ],
            "properties": {
                "script": {
                    "type": "string",
                    "description": "Shell run after the agent stops. Exit 0 is a pass.",
                },
                "file": {
                    "type": "string",
                    "description": (
                        "Path to a shell file, relative to the task file. Read at "
                        "load time and never written into the workspace, so the "
                        "agent cannot read its own success criteria."
                    ),
                },
                "serve": {
                    "type": "string",
                    "description": (
                        "A long-running command to background before checking. "
                        "$QS_PORT is a free port chosen for this task. Starting a "
                        "server proves nothing on its own, so a task with serve "
                        "must also assert something."
                    ),
                },
                "wait_http": {
                    "type": "object",
                    "additionalProperties": False,
                    "description": (
                        "Poll until the endpoint answers as this task says it "
                        "should, keeping the last error and dumping the server "
                        "log on failure."
                    ),
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Resolved against http://127.0.0.1:$QS_PORT.",
                        },
                        "url": {"type": "string", "description": "A full URL instead."},
                        "status": {"type": "integer", "default": 200},
                        "contains": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ],
                            "description": "Literal text the body must contain.",
                        },
                        "matches": {
                            "oneOf": [
                                {"type": "string"},
                                {"type": "array", "items": {"type": "string"}},
                            ],
                            "description": "Extended regular expression the body must match.",
                        },
                        "json": {
                            "type": "object",
                            "description": (
                                "Key/value pairs the body must carry. Matched by "
                                "regular expression, not a JSON parse."
                            ),
                        },
                        "timeout": {"type": "integer", "default": 40},
                    },
                },
            },
        },
        "budgets": {
            "type": "object",
            "additionalProperties": False,
            "description": (
                "Limits on the agent phase. A task that routinely exhausts its "
                "budget is excluded from pass rates rather than counted as a "
                "failure, so too small a budget quietly removes it from results."
            ),
            "properties": {
                "max_turns": {
                    "type": "integer",
                    "default": _BUDGET_DEFAULTS["max_turns"],
                },
                "max_seconds": {
                    "type": "integer",
                    "default": _BUDGET_DEFAULTS["max_seconds"],
                    "description": "Wall clock for the agent phase.",
                },
                "max_command_seconds": {
                    "type": "integer",
                    "default": _BUDGET_DEFAULTS["max_command_seconds"],
                },
                "max_output_chars": {
                    "type": "integer",
                    "default": _BUDGET_DEFAULTS["max_output_chars"],
                    "description": "Per command. The head and the tail are kept.",
                },
                "max_tokens": {
                    "type": "integer",
                    "default": _BUDGET_DEFAULTS["max_tokens"],
                    "description": "Billable tokens, cache included. 0 means unlimited.",
                },
            },
        },
    },
}
