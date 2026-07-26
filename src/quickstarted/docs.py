"""The documentation client: caching, politeness, and affordance policy.

Three things live here that a benchmark cannot do without.

**Reproducibility.** Responses are cached by content hash, so a rerun reads
the same bytes the first run did. When a refresh sees different bytes, that is
recorded, because "the docs changed under us" is itself a finding.

**Politeness.** Benchmarking fifty projects means fetching from fifty
companies who did not ask to be measured. A truthful User-Agent, one request
per host at a time, and robots.txt honoured by default are the minimum for
doing this at scale without being a nuisance.

**Affordance policy.** Whether a project ships `llms.txt` is a checklist item
anybody can curl, and scoring it would be exactly the proxy metric this tool
exists to replace. What nobody can currently answer is whether the file
*helps*. So affordances are never scored, only recorded, and they can be
withheld from the agent: run the same task with `all` and with `none`, and
the difference in pass rate is a measurement of the affordance itself.

The prompt is identical under both conditions. Only availability changes,
which is what keeps the comparison honest.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

from . import transport

#: URL shapes that exist for the benefit of language models rather than people.
AFFORDANCE_FILES = ("llms.txt", "llms-full.txt")
AFFORDANCE_POLICIES = ("all", "none")


_META_REFRESH = re.compile(r"""<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]*>""", re.I)
_REFRESH_URL = re.compile(r"""url\s*=\s*["']?([^"'>\s]+)""", re.I)


def _meta_refresh_target(html: str, base: str) -> str:
    """The URL a <meta http-equiv="refresh"> points at, resolved against base."""
    tag = _META_REFRESH.search(html or "")
    if not tag:
        return ""
    found = _REFRESH_URL.search(tag.group(0))
    return urljoin(base, found.group(1)) if found else ""


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content_type: str
    text: str
    from_cache: bool = False
    content_hash: str = ""
    changed: bool = False
    blocked_reason: str = ""
    #: Set when this page was reached by following a client-side redirect, and
    #: holds the URL that was asked for. The agent asked for that one; the trace
    #: has to say which page it actually got.
    followed_from: str = ""

    @property
    def ok(self) -> bool:
        return not self.blocked_reason and 200 <= self.status < 300


@dataclass
class Affordance:
    url: str
    present: bool
    status: int = 0
    bytes: int = 0
    note: str = ""


def is_affordance_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    name = path.rsplit("/", 1)[-1]
    return name in AFFORDANCE_FILES or path.endswith(".md")


class DocsClient:
    def __init__(
        self,
        cache_dir: str | None = None,
        rate_limit_seconds: float = 1.0,
        respect_robots: bool = True,
        affordances: str = "all",
        refresh: bool = False,
        offline: bool = False,
        timeout: int = 30,
    ):
        if affordances not in AFFORDANCE_POLICIES:
            raise ValueError(
                f"affordances must be one of {AFFORDANCE_POLICIES}, got {affordances!r}"
            )
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.rate_limit_seconds = rate_limit_seconds
        self.respect_robots = respect_robots
        self.affordances = affordances
        self.refresh = refresh
        self.offline = offline
        self.timeout = timeout
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._lock = threading.Lock()

    # -- cache ----------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / digest[:2] / f"{digest}.json"

    def _read_cache(self, url: str) -> dict | None:
        path = self._cache_path(url)
        if not path or not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def _write_cache(self, url: str, payload: dict) -> None:
        path = self._cache_path(url)
        if not path:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    # -- politeness -----------------------------------------------------
    def _throttle(self, host: str) -> None:
        if self.rate_limit_seconds <= 0:
            return
        with self._lock:
            last = self._last_request.get(host, 0.0)
            wait = self.rate_limit_seconds - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()

    def robots_allows(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            known = origin in self._robots
            parser = self._robots.get(origin)
        if not known:
            parser = urllib.robotparser.RobotFileParser()
            try:
                response = transport.http_get(
                    urljoin(origin, "/robots.txt"), timeout=self.timeout
                )
                if 200 <= response.status < 300:
                    parser.parse(response.text.splitlines())
                else:
                    parser = None
            except Exception:
                # No robots.txt, or unreachable: nothing to disallow.
                parser = None
            with self._lock:
                self._robots[origin] = parser
        if parser is None:
            return True
        return parser.can_fetch(transport.USER_AGENT, url)

    # -- fetching -------------------------------------------------------
    def get(self, url: str) -> FetchResult:
        if self.affordances == "none" and is_affordance_url(url):
            return FetchResult(
                url, 0, "", "", blocked_reason="affordance_withheld"
            )

        # What the agent asked for. `url` may be reassigned below if the page
        # turns out to be a client-side redirect, but the cache stays keyed on
        # the request so a rerun is a hit rather than another two round trips.
        requested = url

        cached = self._read_cache(requested)
        if cached and not self.refresh:
            return FetchResult(
                url=cached.get("url") or requested,
                status=cached["status"],
                content_type=cached["content_type"],
                text=cached["text"],
                from_cache=True,
                content_hash=cached["content_hash"],
                followed_from=cached.get("followed_from", ""),
            )

        if self.offline:
            return FetchResult(url, 0, "", "", blocked_reason="offline_cache_miss")

        if not self.robots_allows(url):
            return FetchResult(url, 0, "", "", blocked_reason="robots_disallowed")

        host = urlparse(url).hostname or ""
        self._throttle(host)
        response = transport.http_get(url, timeout=self.timeout)
        text = response.text
        followed_from = ""
        if "html" in (response.content_type or "").lower():
            # Some documentation sites answer a versioned URL with a stub whose
            # only content is a client-side redirect. duckdb.org does this: the
            # entrypoint returns 938 bytes of HTML that render as "Redirecting…",
            # 73 characters of text, and the real page is named in a
            # <meta http-equiv="refresh">. A browser follows it, so an agent with
            # one gets the docs and an agent without gets nothing. Following it
            # here keeps the two comparable, and stops the harness from handing
            # over an empty page and then recording a documentation gap.
            target = _meta_refresh_target(text, url)
            if target and target != url and self._host_allows_hop(url, target):
                self._throttle(urlparse(target).hostname or "")
                hop = transport.http_get(target, timeout=self.timeout)
                if hop.status and 200 <= hop.status < 300:
                    followed_from, url, response = url, target, hop
                    text = hop.text
            text = transport.html_to_text(text)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        changed = bool(cached and cached.get("content_hash") != content_hash)
        self._write_cache(
            requested,
            {
                "url": url,
                "status": response.status,
                "content_type": response.content_type,
                "text": text,
                "content_hash": content_hash,
                "followed_from": followed_from,
                "fetched_at": time.time(),
            },
        )
        return FetchResult(
            url=url,
            status=response.status,
            content_type=response.content_type,
            text=text,
            content_hash=content_hash,
            changed=changed,
            followed_from=followed_from,
        )

    def _host_allows_hop(self, source: str, target: str) -> bool:
        """Only follow a client-side redirect within the same registrable host.

        A stub that points somewhere else entirely would take the agent off the
        documentation allowlist, and a page read that the task never sanctioned
        is exactly the attribution hole the proxy exists to close.
        """
        a = (urlparse(source).hostname or "").lower().strip(".")
        b = (urlparse(target).hostname or "").lower().strip(".")
        return bool(a) and bool(b) and (a == b or b.endswith("." + a) or a.endswith("." + b))

    # -- affordance probing ---------------------------------------------
    def probe(self, entrypoint: str) -> dict[str, Affordance]:
        """Record which machine-facing affordances exist. Never scored.

        Presence is context for a human reading a failure, and a variable for
        the ablation. It is not a grade: a 1.8 MB llms-full.txt is 'present'
        and may still be useless to an agent with a context window.
        """
        parsed = urlparse(entrypoint)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        found: dict[str, Affordance] = {}
        candidates = {name: urljoin(origin + "/", name) for name in AFFORDANCE_FILES}
        page = entrypoint.split("?")[0].rstrip("/")
        if page and not page.endswith(".md"):
            candidates["page.md"] = page + ".md"
        for label, url in candidates.items():
            try:
                self._throttle(urlparse(url).hostname or "")
                response = transport.http_get(url, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                found[label] = Affordance(url, False, status=exc.code)
                continue
            except Exception as exc:
                found[label] = Affordance(url, False, note=str(exc)[:120])
                continue
            body = response.text or ""
            # A soft 200 that serves the site's HTML shell is not an affordance.
            looks_like_html = "html" in (response.content_type or "").lower()
            present = 200 <= response.status < 300 and bool(body) and not looks_like_html
            found[label] = Affordance(
                url=url,
                present=present,
                status=response.status,
                bytes=len(body.encode("utf-8")),
                note="served HTML where a machine-readable file was expected"
                if looks_like_html
                else "",
            )
        return found


def affordance_summary(found: dict[str, Affordance]) -> dict[str, dict]:
    return {
        label: {
            "url": a.url,
            "present": a.present,
            "status": a.status,
            "bytes": a.bytes,
            "note": a.note,
        }
        for label, a in found.items()
    }
