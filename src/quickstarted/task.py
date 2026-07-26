"""Task definitions: the YAML unit of testing.

A task states a goal an agent should reach using only the target project's
documentation, plus a machine-checkable success assertion. Pass/fail is always
decided by the assertion script's exit code, never by a model's opinion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .net.proxy import DEFAULT_NETWORK_ALLOW, host_matches

_NODE_TOOLS = ("npm", "npx", "node", "pnpm", "yarn", "bun")


class TaskError(ValueError):
    """Raised when a task file is missing or malformed."""


@dataclass(frozen=True)
class Budgets:
    max_turns: int = 20
    max_seconds: int = 900
    max_command_seconds: int = 300
    max_output_chars: int = 20_000
    #: Hard ceiling on billable tokens for one run, cache traffic included.
    #: 0 means unlimited. Prefer this to a dollar cap: it needs no price list
    #: and cannot drift when vendors change their rates.
    max_tokens: int = 0


@dataclass(frozen=True)
class Task:
    name: str
    goal: str
    docs_entrypoint: str
    docs_allow: tuple[str, ...]
    success_script: str
    setup: tuple[str, ...] = ()
    replay: tuple[str, ...] = ()
    budgets: Budgets = field(default_factory=Budgets)
    #: Hosts a shell may reach (package registries and the like). Documentation
    #: hosts are deliberately excluded: they are readable only through the
    #: recorded `read_docs` tool, which is what keeps attribution complete.
    network_allow: tuple[str, ...] = DEFAULT_NETWORK_ALLOW
    #: Hosts named by hand under `network.allow`/`network.only`. These beat the
    #: docs-host rule, so a registry that also serves documentation stays
    #: installable when the author says so.
    network_explicit: tuple[str, ...] = ()
    #: Container image for the docker backend. Empty means the CLI's `--image`,
    #: then the default. A task testing a Node quickstart needs Node in the
    #: sandbox, and one suite mixes runtimes, so the image belongs to the task
    #: rather than the invocation.
    image: str = ""
    source: str = ""

    @property
    def needs_node(self) -> bool:
        """Whether the success script calls a Node toolchain.

        Used only to warn: `python:3.12-slim` has no Node, so the check would
        fail for a reason that says nothing about the documentation.
        """
        script = self.success_script
        return any(
            re.search(rf"(^|[\s;&|(]){tool}\b", script) for tool in _NODE_TOOLS
        )

    @property
    def network_conflicts(self) -> tuple[str, ...]:
        """Docs hosts that installs usually need, which will now be refused.

        Declaring a package registry as a documentation host is the easy
        mistake: the proxy then refuses `pip install`, and the run fails for a
        reason that has nothing to do with the documentation.
        """
        return tuple(
            host
            for host in self.docs_allow
            if host_matches(host, DEFAULT_NETWORK_ALLOW)
            and not host_matches(host, self.network_explicit)
        )

    @property
    def attribution_gaps(self) -> tuple[str, ...]:
        """Docs hosts a shell may also reach, so their reads are not all logged."""
        return tuple(
            host for host in self.docs_allow if host_matches(host, self.network_explicit)
        )

    def host_allowed(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        return host_matches(host, self.docs_allow)


def _require(data: dict, key: str, source: str):
    if key not in data or data[key] in (None, "", []):
        raise TaskError(f"{source}: missing required field '{key}'")
    return data[key]


def _str_list(value, key: str, source: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise TaskError(f"{source}: '{key}' must be a list of strings")
    return tuple(x.strip() for x in value if x.strip())


def _normalize_host(entry: str, source: str) -> str:
    entry = entry.strip().lower()
    if "://" in entry:
        entry = urlparse(entry).hostname or ""
    entry = entry.strip("/")
    if not entry or "/" in entry:
        raise TaskError(
            f"{source}: docs.allow entries must be bare hostnames, got {entry!r}"
        )
    return entry


def load_task(path: str | Path) -> Task:
    path = Path(path)
    source = str(path)
    if not path.is_file():
        raise TaskError(f"{source}: no such file")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise TaskError(f"{source}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise TaskError(f"{source}: top level must be a mapping")

    name = str(_require(data, "name", source))
    goal = str(_require(data, "goal", source)).strip()

    docs = _require(data, "docs", source)
    if not isinstance(docs, dict):
        raise TaskError(f"{source}: 'docs' must be a mapping")
    entrypoint = str(_require(docs, "entrypoint", source)).strip()
    parsed = urlparse(entrypoint)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise TaskError(f"{source}: docs.entrypoint must be an http(s) URL")
    allow = [
        _normalize_host(h, source)
        for h in _str_list(docs.get("allow"), "docs.allow", source)
    ]
    entry_host = parsed.hostname.lower()
    if entry_host not in allow:
        allow.insert(0, entry_host)

    network = data.get("network") or {}
    if not isinstance(network, dict):
        raise TaskError(f"{source}: 'network' must be a mapping")
    unknown_net = set(network) - {"allow", "only"}
    if unknown_net:
        raise TaskError(f"{source}: unknown network keys: {sorted(unknown_net)}")
    extra_net = [
        _normalize_host(h, source)
        for h in _str_list(network.get("allow"), "network.allow", source)
    ]
    only_net = [
        _normalize_host(h, source)
        for h in _str_list(network.get("only"), "network.only", source)
    ]
    network_allow = tuple(only_net) if only_net else DEFAULT_NETWORK_ALLOW + tuple(extra_net)

    success = _require(data, "success", source)
    if not isinstance(success, dict):
        raise TaskError(f"{source}: 'success' must be a mapping")
    success_script = str(_require(success, "script", source))

    budgets_data = data.get("budgets") or {}
    if not isinstance(budgets_data, dict):
        raise TaskError(f"{source}: 'budgets' must be a mapping")
    known = set(Budgets.__dataclass_fields__)
    unknown = set(budgets_data) - known
    if unknown:
        raise TaskError(f"{source}: unknown budget keys: {sorted(unknown)}")
    budgets = Budgets(**{k: int(v) for k, v in budgets_data.items()})

    image = str(data.get("image") or "").strip()

    return Task(
        name=name,
        goal=goal,
        docs_entrypoint=entrypoint,
        docs_allow=tuple(allow),
        success_script=success_script,
        setup=_str_list(data.get("setup"), "setup", source),
        replay=_str_list(data.get("replay"), "replay", source),
        budgets=budgets,
        network_allow=network_allow,
        network_explicit=tuple(only_net or extra_net),
        image=image,
        source=source,
    )
