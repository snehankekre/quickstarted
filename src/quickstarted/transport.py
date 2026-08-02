"""Low-level HTTP for documentation reads, and HTML to text.

Separated from the docs client so that caching, rate limiting, robots, and
affordance policy can be tested without a network, and so tests have one
obvious place to intercept.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import ClassVar

from ._version import __version__ as _version

USER_AGENT = (
    f"quickstarted/{_version} (+https://github.com/snehankekre/quickstarted; "
    "documentation agent-readiness testing)"
)
MAX_BODY_BYTES = 4_000_000


@dataclass(frozen=True)
class HttpResponse:
    status: int
    content_type: str
    text: str
    url: str = ""


class _TextExtractor(HTMLParser):
    _SKIP: ClassVar[frozenset] = frozenset(
        {"script", "style", "noscript", "svg", "template"}
    )

    #: Tags that end a line. Without them every block runs into the next one,
    #: and the damage lands hardest exactly where it matters: a docs page that
    #: offers npm/yarn/pnpm/bun in tabs rendered as
    #: `npm create vite@latestbash$ yarn create vite`, and Tailwind's install
    #: page as `npm create vite@latest my-projectcd my-project`. An agent
    #: reading that cannot tell where one command stops and the next begins,
    #: so the harness was scoring its own HTML handling as a documentation gap.
    _BLOCK: ClassVar[frozenset] = frozenset(
        {
            "address", "article", "aside", "blockquote", "br", "button",
            "dd", "details", "div", "dl", "dt", "fieldset", "figcaption",
            "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
            "header", "hr", "li", "main", "nav", "ol", "option", "p", "pre",
            "section", "summary", "table", "tbody", "td", "tfoot", "th",
            "thead", "tr", "ul",
        }
    )

    #: Syntax highlighters wrap each line of a code sample in an inline span
    #: rather than a block element: Shiki, which tailwindcss.com uses, emits
    #: `<span class="line">`, and prism-react-renderer, which every Docusaurus
    #: site uses, emits `<span class="token-line">`. Nothing in the markup says
    #: where the line ends, so `npm create vite@latest my-project` and
    #: `cd my-project` arrived as one string. Matched per class token and
    #: anchored, so `line-numbers` does not qualify.
    _LINE_CLASS = re.compile(r"^(?:[A-Za-z0-9]+-)?line$")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        #: (text, verbatim). Verbatim chunks are `<pre>` content and the line
        #: breaks inserted below; everything else gets its whitespace collapsed.
        self._chunks: list[tuple[str, bool]] = []
        self._skip_depth = 0
        self._pre_depth = 0
        #: True when the last thing closed was an inline <code>, so two
        #: adjacent ones can be told apart from one interrupted by prose.
        self._after_code = False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        # Nothing inside a skipped region may touch the state machine. An
        # unbalanced <pre> inside a <script> used to leave _pre_depth stuck
        # above zero, and every remaining paragraph on the page was then
        # emitted with its source whitespace intact.
        if self._skip_depth:
            return
        if tag == "pre":
            self._pre_depth += 1
        if tag in self._BLOCK or (self._pre_depth and self._is_line(attrs)):
            self._break()
        elif tag == "code" and not self._pre_depth and self._after_code:
            # Two inline <code> elements with nothing between them are two
            # things, not one word.
            self._chunks.append((" ", True))
        self._after_code = False

    def _is_line(self, attrs) -> bool:
        classes = next((v for k, v in attrs if k == "class" and v), "")
        return any(self._LINE_CLASS.match(token) for token in classes.split())

    def _break(self) -> None:
        """Add a line boundary, unless the text already ends at one.

        Shiki writes a literal newline between its line spans, so the newline
        and the following span each asked for a break and every highlighted
        line came out double spaced. Worse, a genuinely blank line in a sample
        then read the same as a line ending, so the original could not be
        recovered.
        """
        for chunk, verbatim in reversed(self._chunks):
            if not chunk:
                continue
            if verbatim and chunk.endswith("\n"):
                return
            if chunk.strip(" \t"):
                break
        self._chunks.append(("\n", True))

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == "pre" and self._pre_depth:
            self._pre_depth -= 1
        if tag in self._BLOCK:
            self._break()
        self._after_code = tag == "code" and not self._pre_depth

    def handle_data(self, data):
        if not self._skip_depth:
            # Indentation inside a code sample is part of the sample. Outside
            # one it is HTML source formatting and means nothing.
            self._chunks.append((data, self._pre_depth > 0))
            if data.strip():
                self._after_code = False

    def text(self) -> str:
        """Collapse prose, leave code alone.

        Normalising the joined string cannot do both: the same pass that tidies
        `\\n   ` between two paragraphs also eats the four spaces that make a
        Python sample run. So each chunk is normalised on its own terms and the
        line breaks are trimmed as they are laid down.
        """
        out: list[str] = []

        def rstrip_tail() -> None:
            while out:
                trimmed = out[-1].rstrip(" \t")
                if trimmed:
                    out[-1] = trimmed
                    return
                out.pop()

        for chunk, verbatim in self._chunks:
            if verbatim and chunk == "\n":  # a block boundary
                rstrip_tail()
                if out:
                    out.append("\n")
                continue
            if verbatim:  # inside <pre>: indentation is the content
                out.append(chunk)
                continue
            collapsed = re.sub(r"\s+", " ", chunk)
            if not collapsed:
                continue
            if out and out[-1].endswith("\n"):
                collapsed = collapsed.lstrip(" ")
                if not collapsed:
                    continue
            elif not out and collapsed == " ":
                continue
            out.append(collapsed)
        return re.sub(r"\n{3,}", "\n\n", "".join(out)).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        return parser.text()
    except Exception:
        return html


def http_get(url: str, timeout: int = 30, method: str = "GET") -> HttpResponse:
    """Fetch a URL. Raises the urllib.error family on transport failure."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")
        body = response.read(MAX_BODY_BYTES) if method != "HEAD" else b""
        if response.headers.get("Content-Encoding") == "gzip" and body:
            with contextlib.suppress(OSError):
                body = gzip.GzipFile(fileobj=io.BytesIO(body)).read()
        return HttpResponse(
            status=getattr(response, "status", 200),
            content_type=content_type,
            text=body.decode("utf-8", errors="replace"),
            url=response.geturl(),
        )
