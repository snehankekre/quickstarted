"""Repo-level defaults, so an invocation and a task file stop repeating themselves.

Every task in a suite tends to want the same `setup`, the same budgets, and the
same image, and every invocation the same `--backend`, `--cache-dir` and
`--prices`. Without somewhere to say that once, the flags get pasted into a
shell history and a README and eventually diverge.

YAML rather than TOML deliberately: `tomllib` arrived in 3.11 and this package
supports 3.9, so TOML would mean a second runtime dependency for a file most
projects will never write. Tasks are already YAML.

    # quickstarted.yaml
    run:
      backend: docker
      cache_dir: .cache
    tasks:
      setup:
        - python3 -m venv .venv
      budgets:
        max_seconds: 420

Precedence is the same in both directions: the more specific statement wins. A
CLI flag beats `run:`, and a task file beats `tasks:`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_NAME = "quickstarted.yaml"

#: Only settings that cannot change what a result means. `--agent`, `--model`,
#: `--repeat` and `--affordances` are deliberately absent: a config file that
#: quietly changed which model served a task, or how many attempts a rate was
#: computed over, would make two runs incomparable for a reason nobody could
#: see in the command they typed.
RUN_KEYS = ("backend", "image", "cache_dir", "prices", "out", "junit", "workers")


class ConfigError(ValueError):
    """Raised when a config file is present but malformed."""


@dataclass(frozen=True)
class Config:
    run: dict = field(default_factory=dict)
    tasks: dict = field(default_factory=dict)
    source: str = ""

    def __bool__(self) -> bool:
        return bool(self.run or self.tasks)


def find_config(start: Path | None = None) -> Path | None:
    """Nearest `quickstarted.yaml` at or above `start`, like a linter config."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        candidate = directory / CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path | None = None) -> Config:
    path = path or find_config()
    if path is None:
        return Config()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    unknown = set(data) - {"run", "tasks"}
    if unknown:
        raise ConfigError(f"{path}: unknown keys: {sorted(unknown)}")
    run = data.get("run") or {}
    tasks = data.get("tasks") or {}
    if not isinstance(run, dict) or not isinstance(tasks, dict):
        raise ConfigError(f"{path}: 'run' and 'tasks' must be mappings")
    bad = set(run) - set(RUN_KEYS)
    if bad:
        raise ConfigError(
            f"{path}: 'run' does not accept {sorted(bad)}. Settings that change "
            f"what a result means stay on the command line."
        )
    return Config(run=run, tasks=tasks, source=str(path))


def merge_defaults(defaults: dict, data: dict) -> dict:
    """`data` wins. Mappings merge key by key; lists and scalars replace whole.

    A list that concatenated would be worse than useless: a config `setup` of
    `python3 -m venv .venv` plus a task's own `npm init -y` would run both, in
    an order nobody chose.
    """
    merged = dict(defaults)
    for key, value in data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_defaults(merged[key], value)
        else:
            merged[key] = value
    return merged
