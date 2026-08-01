"""Runnable example tasks, shipped inside the package.

`tasks/` in the repository is the benchmark corpus and lives in the sdist only,
so a `pip install quickstarted` user did not have the file the documentation
told them to start with. These three travel with the wheel instead:

* `httpx`, the smallest complete task, one documentation page and a four-line
  check.
* `streamlit`, which boots the app and polls its health endpoint through the
  declarative `serve` and `wait_http` form.
* `vite`, a Node task, which needs its own image and proves a build really ran.

`tests/test_examples.py` fails if any of them drifts from the copy in `tasks/`
that CI actually runs, so an example cannot rot into something that no longer
passes.
"""

from __future__ import annotations

from pathlib import Path

DIR = Path(__file__).parent


def names() -> list[str]:
    return sorted(p.stem for p in DIR.glob("*.yaml"))


def path_for(name: str) -> Path:
    """Resolve an `--example` name, or say what there is."""
    candidate = DIR / f"{name}.yaml"
    if not candidate.is_file():
        raise FileNotFoundError(
            f"no example named {name!r}; available: {', '.join(names())}"
        )
    return candidate
