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
    def check_script(self) -> str:
        """What the harness actually runs: the helper prelude, then the check.

        `success_script` stays exactly what the author wrote, so reports and
        `quickstarted check --show` quote them rather than 150 lines of shell
        they did not write.
        """
        from .checks import prelude_for

        return prelude_for(self.name) + "\n" + self.success_script

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
    def unprepared_env_paths(self) -> tuple[str, ...]:
        """Interpreter paths the check demands that `setup` never creates.

        The expensive version of this mistake: a check asserted `.venv/bin/...`,
        an agent created `venv/` instead, did everything else correctly, and was
        recorded as a documentation failure. The pass rate was wrong, and
        nothing in the report said so.

        Only environment directories are flagged, never ordinary files. A check
        may legitimately assert `app.py` or `dist/index.html`, because the
        documentation promised those; nothing promises where an agent puts its
        virtualenv unless `setup` put it there.
        """
        # Only the directory immediately before `/bin/`, so `.venv/bin/python`
        # and `"$WS/.venv/bin/python"` both name `.venv` rather than dragging a
        # shell variable into the message.
        found = re.findall(r"([\w.-]+)/bin/", self.success_script)
        # A path the documented commands themselves create is one the
        # documentation promises, which is the whole distinction being drawn.
        promised = " ".join(self.setup) + " " + " ".join(self.replay)
        return tuple(
            sorted(
                {
                    directory
                    for directory in found
                    if directory not in (".", "..", "usr", "local", "opt", "env")
                    and directory not in promised
                }
            )
        )

    @property
    def can_fail_silently(self) -> bool:
        """Could this check exit non-zero while printing nothing?

        A `docs_gap` that names a page and no reason sends whoever reads it to a
        page that may be perfectly fine. `quickstarted run` says so after the
        fact; a multi-assertion check with no way to report which assertion
        failed is detectable before anyone spends a token on it.
        """
        script = self.success_script
        if re.search(r"qs_fail|qs_wait_http|echo|printf|\bfail\b", script):
            return False
        assertions = len(
            re.findall(r"(?m)^\s*(?:test |\[ |\[\[ |grep -[a-zA-Z]*q|diff |cmp )", script)
        )
        return assertions >= 2

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


_SUCCESS_KEYS = {"script", "file", "serve", "wait_http"}


def _assertion_script(success: dict, task_path: Path, source: str) -> str:
    """The author's own check, from `script:` inline or `file:` alongside the task.

    A file is read here and carried as text, never handed to the executor as a
    path. The check has to stay off the workspace disk while the agent is
    working: the workspace is the agent's own directory, and a readable success
    script is an answer key.
    """
    inline = success.get("script")
    ref = success.get("file")
    if inline and ref:
        raise TaskError(
            f"{source}: success has both 'script' and 'file'; use one or the other"
        )
    if inline:
        return str(inline)
    if not ref:
        return ""
    if not isinstance(ref, str):
        raise TaskError(f"{source}: success.file must be a path")
    if Path(ref).is_absolute():
        raise TaskError(
            f"{source}: success.file must be relative to the task file, got {ref!r}"
        )
    script_path = (task_path.parent / ref).resolve()
    if not script_path.is_file():
        raise TaskError(f"{source}: success.file {ref!r} does not exist")
    text = script_path.read_text(encoding="utf-8")
    if not text.strip():
        raise TaskError(f"{source}: success.file {ref!r} is empty")
    return text


def _wait_http_call(spec, source: str) -> str:
    """Generate one `qs_wait_http` line from the declarative form.

    The harness owns the mechanism (background, poll, keep the last error, dump
    the log). The task owns every criterion, which is why a `wait_http` with no
    status, no body match and no assertion beside it is rejected below.
    """
    if not isinstance(spec, dict):
        raise TaskError(f"{source}: success.wait_http must be a mapping")
    unknown = set(spec) - {"path", "url", "status", "contains", "matches", "json", "timeout"}
    if unknown:
        raise TaskError(f"{source}: unknown wait_http keys: {sorted(unknown)}")
    target = spec.get("url") or spec.get("path")
    if not target:
        raise TaskError(f"{source}: success.wait_http needs 'path' or 'url'")
    args = [_shell_quote(str(target))]
    for key, flag in (("status", "--status"), ("timeout", "--timeout")):
        if spec.get(key) is not None:
            args += [flag, _shell_quote(str(spec[key]))]
    for key, flag in (("contains", "--contains"), ("matches", "--matches")):
        value = spec.get(key)
        if value is None:
            continue
        for item in value if isinstance(value, list) else [value]:
            args += [flag, _shell_quote(str(item))]
    body = spec.get("json") or {}
    if not isinstance(body, dict):
        raise TaskError(f"{source}: success.wait_http.json must be a mapping")
    for key, value in body.items():
        args += ["--json", _shell_quote(f"{key}={value}")]
    return "qs_wait_http " + " ".join(args)


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _load_success_script(success: dict, task_path: Path, source: str) -> str:
    unknown = set(success) - _SUCCESS_KEYS
    if unknown:
        raise TaskError(f"{source}: unknown success keys: {sorted(unknown)}")
    assertion = _assertion_script(success, task_path, source)
    serve = success.get("serve")
    wait = success.get("wait_http")

    if not (assertion or serve or wait):
        raise TaskError(f"{source}: missing required field 'script' (or 'file')")
    if serve and not (wait or assertion):
        # Starting a server proves nothing. Without something that decides, the
        # check would exit 0 for any application that boots, including one that
        # answers every request with a 500.
        raise TaskError(
            f"{source}: success.serve starts a server but nothing checks it; "
            f"add 'wait_http' or a 'script'"
        )
    if wait is not None and not isinstance(wait, dict):
        raise TaskError(f"{source}: success.wait_http must be a mapping")

    # No injected `set -e`. An inline script governs itself today and a
    # declarative one should behave the same way; `qs_wait_http` exits on its
    # own when it gives up, so the generated lines do not need it.
    lines = []
    if serve:
        if not isinstance(serve, str):
            raise TaskError(f"{source}: success.serve must be a command string")
        lines.append(f"qs_serve {serve.strip()}")
    if wait:
        lines.append(_wait_http_call(wait, source))
    if assertion:
        lines.append(assertion)
    return "\n".join(lines) + "\n" if len(lines) > 1 else assertion


def load_task(path: str | Path, defaults: dict | None = None) -> Task:
    """Load a task. `defaults` come from `quickstarted.yaml`; the task wins."""
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
    if defaults:
        from .config import merge_defaults

        data = merge_defaults(defaults, data)

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
    success_script = _load_success_script(success, path, source)

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
