"""The documentation client: caching, politeness, and affordance policy.

Three things live here that a benchmark cannot do without.

**Reproducibility.** Responses are cached by content hash, so a rerun reads
the same bytes the first run did. When a refresh sees different bytes, that is
recorded: "the docs changed under us" is a finding, not an inconvenience.

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

        cached = self._read_cache(url)
        if cached and not self.refresh:
            return FetchResult(
                url=url,
                status=cached["status"],
                content_type=cached["content_type"],
                text=cached["text"],
                from_cache=True,
                content_hash=cached["content_hash"],
            )

        if self.offline:
            return FetchResult(url, 0, "", "", blocked_reason="offline_cache_miss")

        if not self.robots_allows(url):
            return FetchResult(url, 0, "", "", blocked_reason="robots_disallowed")

        host = urlparse(url).hostname or ""
        self._throttle(host)
        response = transport.http_get(url, timeout=self.timeout)
        text = response.text
        if "html" in (response.content_type or "").lower():
            text = transport.html_to_text(text)
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        changed = bool(cached and cached.get("content_hash") != content_hash)
        self._write_cache(
            url,
            {
                "url": url,
                "status": response.status,
                "content_type": response.content_type,
                "text": text,
                "content_hash": content_hash,
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
        )

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
                note="served HTML, not a machine-readable file" if looks_like_html else "",
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
