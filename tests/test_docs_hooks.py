"""The docs site's build hooks.

`docs_hooks.py` lives at the repository root because MkDocs loads it by path,
so it is imported here by path too.
"""

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent

_spec = importlib.util.spec_from_file_location("docs_hooks", ROOT / "docs_hooks.py")
docs_hooks = importlib.util.module_from_spec(_spec)
sys.modules["docs_hooks"] = docs_hooks
_spec.loader.exec_module(docs_hooks)


def test_the_site_colours_every_label_the_cli_prints():
    """A new verdict label would otherwise render as plain text on the site,
    which is the sort of drift nobody notices until a screenshot looks wrong."""
    from quickstarted.report import _LABELS

    assert set(_LABELS.values()) == set(docs_hooks.VERDICTS)


def test_a_verdict_inside_a_console_sample_is_coloured():
    html = (
        '<div class="language-text highlight"><pre><code>'
        "[PASS] httpx-quickstart (replay)\n[FAIL] fastapi-quickstart\n"
        "[INCONCLUSIVE] some-task\n[SKIP] agent-only\n"
        "</code></pre></div>"
    )
    out = docs_hooks._colour_verdicts(html)
    assert '<span class="qs-verdict qs-verdict--pass">[PASS]</span>' in out
    assert '<span class="qs-verdict qs-verdict--fail">[FAIL]</span>' in out
    assert out.count("qs-verdict--none") == 2


def test_prose_and_other_languages_are_left_alone():
    """`[PASS]` in a YAML sample or a sentence is text, not a verdict."""
    html = (
        '<div class="language-yaml highlight"><pre><code>x: "[PASS]"</code></pre></div>'
        "<p>A run that prints [PASS] passed.</p>"
    )
    assert docs_hooks._colour_verdicts(html) == html
