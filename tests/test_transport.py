"""HTML to text, which decides what a documentation page looks like to an agent.

Every failure here was found by reading the bytes an agent was actually served
and noticing they were not the bytes a reader sees.
"""

from __future__ import annotations

from quickstarted.transport import html_to_text


def test_adjacent_code_blocks_do_not_run_together():
    """vite.dev offers npm/yarn/pnpm/bun as separate <pre> blocks.

    Joined with no separator they read as `npm create vite@latestbash$ yarn
    create vite`, and an agent cannot tell where one command ends.
    """
    html = (
        "<div><pre><code>npm create vite@latest</code></pre>"
        "<pre><code>yarn create vite</code></pre></div>"
    )
    text = html_to_text(html)
    assert "vite@latestyarn" not in text
    assert "npm create vite@latest" in text
    assert "yarn create vite" in text


def test_highlighter_line_spans_end_a_line():
    """Shiki, used by tailwindcss.com, wraps each line in <span class="line">.

    They are inline elements inside one <pre>, so without this the install page
    reads `npm create vite@latest my-projectcd my-project`.
    """
    html = (
        '<pre><code><span class="line"><span>npm</span><span> create'
        '</span><span> vite@latest my-project</span></span>'
        '<span class="line"><span>cd</span><span> my-project</span></span>'
        "</code></pre>"
    )
    text = html_to_text(html)
    assert "my-projectcd" not in text
    assert "npm create vite@latest my-project" in text
    assert "cd my-project" in text


def test_line_numbers_class_is_not_a_line_break():
    """Matched by class token, so a `line-numbers` wrapper does not qualify."""
    html = '<pre><code><span class="line-numbers">pip install httpx</span></code></pre>'
    assert "pip install httpx" in html_to_text(html)


def test_indentation_inside_pre_survives():
    """A Python sample whose indentation is collapsed is a sample that will not run."""
    html = "<pre><code>def main():\n    return 42\n</code></pre>"
    text = html_to_text(html)
    assert "    return 42" in text


def test_prose_whitespace_is_still_collapsed():
    """Source formatting outside a code sample means nothing and should not survive."""
    html = "<p>Install\n   the    package</p>"
    assert "Install the package" in html_to_text(html)


def test_inline_code_stays_in_its_sentence():
    """<code> is inline. Breaking on it would shred every prose paragraph."""
    html = "<p>Edit <code>vite.config.ts</code> and save it.</p>"
    assert "Edit vite.config.ts and save it." in html_to_text(html)


def test_list_items_are_separated():
    html = "<ul><li>first</li><li>second</li></ul>"
    assert "firstsecond" not in html_to_text(html)


def test_script_and_style_are_dropped():
    html = "<p>real</p><script>var x = 1;</script><style>p{color:red}</style>"
    text = html_to_text(html)
    assert "real" in text
    assert "var x" not in text
    assert "color:red" not in text


def test_table_cells_are_separated():
    html = "<table><tr><td>uv init</td><td>create a project</td></tr></table>"
    assert "uv initcreate" not in html_to_text(html)


def test_docusaurus_token_line_spans_end_a_line():
    """prism-react-renderer, which every Docusaurus site uses, emits
    `class="token-line"`. Matching only Shiki's `line` left the original bug
    reproducing on one of the most common documentation generators."""
    html = (
        '<pre><code><span class="token-line">npm i</span>'
        '<span class="token-line">cd app</span></code></pre>'
    )
    assert "npm icd" not in html_to_text(html)


def test_highlighted_lines_are_not_double_spaced():
    """Shiki writes a literal newline between its line spans, so the newline and
    the span each asked for a break and every sample came out double spaced."""
    html = (
        '<pre><code><span class="line">npm create vite@latest my-project</span>\n'
        '<span class="line">cd my-project</span></code></pre>'
    )
    assert html_to_text(html) == "npm create vite@latest my-project\ncd my-project"


def test_a_blank_line_in_a_sample_survives_as_a_blank_line():
    """Otherwise a blank line and a line ending read the same, and the original
    line structure of a heredoc or a YAML sample cannot be recovered."""
    html = (
        '<pre><code><span class="line">import x</span>\n'
        '<span class="line"></span>\n'
        '<span class="line">print(x)</span></code></pre>'
    )
    assert html_to_text(html) == "import x\n\nprint(x)"


def test_an_unbalanced_pre_inside_a_skipped_region_does_not_leak():
    """Tags inside script/style/svg used to still move the state machine, so one
    stray <pre> left every later paragraph emitted with its source whitespace."""
    html = "<svg><pre></svg><p>Prose   with    lots   of    space</p>"
    assert "Prose with lots of space" in html_to_text(html)


def test_adjacent_inline_code_elements_are_separated():
    html = "<p><code>npm i</code><code>cd app</code></p>"
    assert "npm icd" not in html_to_text(html)


def test_a_self_closing_br_is_one_break_not_two():
    assert html_to_text("<p>a<br/>b</p>") == "a\nb"
