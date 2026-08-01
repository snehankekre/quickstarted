"""Build hooks that make this site readable by the thing it tests.

Two outputs, both generated at build time so they cannot drift from the nav:

* `llms.txt`, an index of every page with its one-line summary.
* a raw `.md` alongside every rendered page, so an agent that appends `.md` to
  a URL gets the source instead of a parsed HTML shell.

Practising what the tool measures. The project's own task reads these docs
through `read_docs`, so a regression here fails our CI like anyone else's.

Plus one presentational hook: the console samples on this site are real CLI
output, and the CLI colours its verdict labels. Reproducing that here costs a
regex and makes a page of samples scan the way the terminal does.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

#: A page summary is the blockquote under its title, which may wrap over
#: several lines. Capturing only the first line cuts sentences in half.
SUMMARY = re.compile(r"^(>[^\n]*(?:\n>[^\n]*)*)", re.M)


def _summary(source: Path) -> str:
    """The leading blockquote of a page, used as its llms.txt description."""
    try:
        text = source.read_text(encoding="utf-8")
    except OSError:
        return ""
    match = SUMMARY.search(text)
    if not match:
        return ""
    lines = [line.lstrip(">").strip() for line in match.group(1).splitlines()]
    return " ".join(line for line in lines if line)


#: The labels `quickstarted run` prints, and how each one reads. Kept in step
#: with `report.py`'s `_LABELS` by `tests/test_docs_hooks.py`.
VERDICTS = {
    "PASS": "pass",
    "FAIL": "fail",
    "INCONCLUSIVE": "none",
    "SKIP": "none",
}

#: Only inside a `language-text` block, which is this site's convention for
#: output the tool printed. A `[PASS]` in prose or in a YAML sample is left
#: alone, and so is anything that happens to sit inside a tag.
_READOUT = re.compile(
    r'(<div class="language-text highlight">)(.*?)(</div>)', re.S
)
_VERDICT = re.compile(r"\[(" + "|".join(VERDICTS) + r")\]")


def _colour_verdicts(html: str) -> str:
    def in_block(block):
        def wrap(match):
            word = match.group(1)
            return (
                f'<span class="qs-verdict qs-verdict--{VERDICTS[word]}">'
                f"[{word}]</span>"
            )

        return block.group(1) + _VERDICT.sub(wrap, block.group(2)) + block.group(3)

    return _READOUT.sub(in_block, html)


def on_post_page(output: str, **kwargs) -> str:
    return _colour_verdicts(output)


def _walk_nav(items, docs_dir: Path, out):
    for item in items:
        if not isinstance(item, dict):
            continue
        for title, value in item.items():
            if isinstance(value, list):
                out.append((title, None, ""))
                _walk_nav(value, docs_dir, out)
            else:
                out.append((title, value, _summary(docs_dir / value)))


def on_post_build(config, **kwargs):
    site_dir = Path(config["site_dir"])
    docs_dir = Path(config["docs_dir"])
    site_url = (config.get("site_url") or "").rstrip("/")

    # 1. Raw Markdown next to every rendered page.
    for source in docs_dir.rglob("*.md"):
        relative = source.relative_to(docs_dir)
        target = site_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    # 2. llms.txt, generated from the nav so it stays in step with the site.
    entries: list = []
    _walk_nav(config.get("nav") or [], docs_dir, entries)

    lines = [
        f"# {config.get('site_name', 'quickstarted')}",
        "",
        f"> {config.get('site_description', '')}",
        "",
        "Every page below is also available as raw Markdown: append `.md` to any",
        "URL, or use the links here, which already point at the Markdown.",
        "",
    ]
    for title, path, summary in entries:
        if path is None:
            lines.append(f"\n## {title}\n")
            continue
        url = f"{site_url}/{path}" if site_url else path
        lines.append(f"- [{title}]({url}){f': {summary}' if summary else ''}")

    (site_dir / "llms.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
