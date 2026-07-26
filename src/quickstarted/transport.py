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
    _SKIP: ClassVar[frozenset] = frozenset({"script", "style", "noscript", "svg"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", raw)).strip()


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
