"""Caching, politeness, and affordance policy."""

import urllib.error

import pytest

from quickstarted import transport
from quickstarted.docs import DocsClient, affordance_summary, is_affordance_url


@pytest.fixture
def fake_http(monkeypatch):
    """Records calls so we can assert on what actually left the machine."""
    calls = []
    pages = {}

    def fake_get(url, timeout=30, method="GET"):
        calls.append(url)
        if url in pages:
            status, ctype, body = pages[url]
            if status >= 400:
                raise urllib.error.HTTPError(url, status, "err", {}, None)
            return transport.HttpResponse(status, ctype, body, url)
        raise urllib.error.HTTPError(url, 404, "not found", {}, None)

    monkeypatch.setattr(transport, "http_get", fake_get)
    return calls, pages


def test_affordance_urls_are_recognised():
    assert is_affordance_url("https://x.dev/llms.txt")
    assert is_affordance_url("https://x.dev/docs/page.md")
    assert is_affordance_url("https://x.dev/llms-full.txt")
    assert not is_affordance_url("https://x.dev/docs/page")


def test_affordances_none_withholds_the_file(fake_http):
    calls, pages = fake_http
    pages["https://x.dev/llms.txt"] = (200, "text/plain", "index")
    client = DocsClient(affordances="none", rate_limit_seconds=0, respect_robots=False)
    result = client.get("https://x.dev/llms.txt")
    assert result.blocked_reason == "affordance_withheld"
    assert calls == [], "withheld affordances must not be fetched at all"


def test_affordances_all_permits_the_file(fake_http):
    calls, pages = fake_http
    pages["https://x.dev/llms.txt"] = (200, "text/plain", "index")
    client = DocsClient(affordances="all", rate_limit_seconds=0, respect_robots=False)
    assert client.get("https://x.dev/llms.txt").text == "index"
    assert calls == ["https://x.dev/llms.txt"]


def test_ordinary_pages_are_unaffected_by_the_ablation(fake_http):
    _, pages = fake_http
    pages["https://x.dev/guide"] = (200, "text/plain", "hello")
    client = DocsClient(affordances="none", rate_limit_seconds=0, respect_robots=False)
    assert client.get("https://x.dev/guide").text == "hello"


def test_cache_makes_a_rerun_read_the_same_bytes(tmp_path, fake_http):
    calls, pages = fake_http
    pages["https://x.dev/a"] = (200, "text/plain", "v1")
    client = DocsClient(
        cache_dir=str(tmp_path), rate_limit_seconds=0, respect_robots=False
    )
    first = client.get("https://x.dev/a")
    pages["https://x.dev/a"] = (200, "text/plain", "v2")  # upstream changed
    second = client.get("https://x.dev/a")
    assert second.from_cache is True
    assert second.text == first.text == "v1"
    assert len(calls) == 1


def test_refresh_detects_that_the_docs_changed(tmp_path, fake_http):
    _, pages = fake_http
    pages["https://x.dev/a"] = (200, "text/plain", "v1")
    warm = DocsClient(cache_dir=str(tmp_path), rate_limit_seconds=0, respect_robots=False)
    warm.get("https://x.dev/a")
    pages["https://x.dev/a"] = (200, "text/plain", "v2")
    fresh = DocsClient(
        cache_dir=str(tmp_path), rate_limit_seconds=0, respect_robots=False, refresh=True
    )
    result = fresh.get("https://x.dev/a")
    assert result.changed is True
    assert result.text == "v2"


def test_offline_never_touches_the_network(tmp_path, fake_http):
    calls, _ = fake_http
    client = DocsClient(
        cache_dir=str(tmp_path), offline=True, rate_limit_seconds=0, respect_robots=False
    )
    assert client.get("https://x.dev/a").blocked_reason == "offline_cache_miss"
    assert calls == []


def test_robots_disallow_is_honoured(fake_http):
    _, pages = fake_http
    pages["https://x.dev/robots.txt"] = (
        200, "text/plain", "User-agent: *\nDisallow: /private\n"
    )
    pages["https://x.dev/private/secret"] = (200, "text/plain", "nope")
    pages["https://x.dev/public"] = (200, "text/plain", "yes")
    client = DocsClient(rate_limit_seconds=0)
    assert client.get("https://x.dev/private/secret").blocked_reason == "robots_disallowed"
    assert client.get("https://x.dev/public").text == "yes"


def test_robots_can_be_overridden(fake_http):
    _, pages = fake_http
    pages["https://x.dev/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /\n")
    pages["https://x.dev/p"] = (200, "text/plain", "content")
    client = DocsClient(rate_limit_seconds=0, respect_robots=False)
    assert client.get("https://x.dev/p").text == "content"


def test_user_agent_identifies_the_tool():
    assert "quickstarted/" in transport.USER_AGENT
    assert "http" in transport.USER_AGENT


def test_probe_records_presence_without_scoring(fake_http):
    _, pages = fake_http
    pages["https://x.dev/llms.txt"] = (200, "text/plain", "a" * 100)
    pages["https://x.dev/get-started"] = (200, "text/html", "<p>hi</p>")
    client = DocsClient(rate_limit_seconds=0, respect_robots=False)
    found = client.probe("https://x.dev/get-started")
    summary = affordance_summary(found)
    assert summary["llms.txt"]["present"] is True
    assert summary["llms.txt"]["bytes"] == 100
    assert summary["llms-full.txt"]["present"] is False
    assert summary["llms-full.txt"]["status"] == 404
    # No score, no grade, no total: presence is context only.
    assert not any(k in summary for k in ("score", "grade", "total"))


def test_probe_treats_an_html_shell_as_absent(fake_http):
    _, pages = fake_http
    # Soft 200: SPA routers serve the app shell for any unknown path.
    pages["https://x.dev/llms.txt"] = (200, "text/html", "<html>app</html>")
    client = DocsClient(rate_limit_seconds=0, respect_robots=False)
    found = client.probe("https://x.dev/docs")
    assert found["llms.txt"].present is False
    assert "HTML" in found["llms.txt"].note


@pytest.mark.parametrize(
    "html, expected",
    [
        (
            '<meta http-equiv="refresh" content="0; url=https://d.org/real.html">',
            "https://d.org/real.html",
        ),
        # Unquoted attribute, single quotes, and a relative target all appear in
        # the wild; duckdb.org uses the first form.
        ("<meta http-equiv=refresh content='0;URL=/docs/real'>", "https://d.org/docs/real"),
        # A bare filename resolves against the directory, not the host root.
        (
            "<meta HTTP-EQUIV='REFRESH' CONTENT='0; url=other.html'>",
            "https://d.org/docs/other.html",
        ),
        ('<meta name="description" content="0; url=/nope">', ""),
        ("<html><body>no redirect here</body></html>", ""),
    ],
)
def test_meta_refresh_target(html, expected):
    from quickstarted.docs import _meta_refresh_target

    assert _meta_refresh_target(html, "https://d.org/docs/page") == expected


def test_client_side_redirect_is_followed(fake_http):
    """A stub page must not be handed to the agent as if it were documentation.

    duckdb.org answers its own versioned URLs with 938 bytes of HTML that render
    as 73 characters of "Redirecting...". A browser follows the meta refresh, so
    an agent with one reads the docs and an agent without reads nothing.
    """
    calls, pages = fake_http
    stub = '<html><head><meta http-equiv="refresh" content="0; url=https://d.org/real.html">' \
           "</head><body>Redirecting&hellip;</body></html>"
    pages["https://d.org/docs/page"] = (200, "text/html", stub)
    pages["https://d.org/real.html"] = (200, "text/html", "<p>duckdb.connect() opens a database</p>")

    client = DocsClient(rate_limit_seconds=0, respect_robots=False)
    result = client.get("https://d.org/docs/page")

    assert "duckdb.connect" in result.text
    assert result.url == "https://d.org/real.html"
    assert result.followed_from == "https://d.org/docs/page"
    assert calls == ["https://d.org/docs/page", "https://d.org/real.html"]


def test_client_side_redirect_off_host_is_not_followed(fake_http):
    """Following a stub off-host would read a page the task never allowlisted."""
    calls, pages = fake_http
    stub = '<meta http-equiv="refresh" content="0; url=https://elsewhere.test/x.html">'
    pages["https://d.org/docs/page"] = (200, "text/html", stub)
    pages["https://elsewhere.test/x.html"] = (200, "text/html", "<p>off host</p>")

    client = DocsClient(rate_limit_seconds=0, respect_robots=False)
    result = client.get("https://d.org/docs/page")

    assert result.url == "https://d.org/docs/page"
    assert result.followed_from == ""
    assert calls == ["https://d.org/docs/page"]


def test_followed_redirect_survives_the_cache(fake_http, tmp_path):
    """The cache is keyed on what was asked for, so a rerun is one hit."""
    calls, pages = fake_http
    pages["https://d.org/docs/page"] = (
        200, "text/html",
        '<meta http-equiv="refresh" content="0; url=https://d.org/real.html">',
    )
    pages["https://d.org/real.html"] = (200, "text/html", "<p>real content</p>")

    first = DocsClient(cache_dir=str(tmp_path), rate_limit_seconds=0, respect_robots=False)
    first.get("https://d.org/docs/page")
    assert len(calls) == 2

    second = DocsClient(cache_dir=str(tmp_path), rate_limit_seconds=0, respect_robots=False)
    result = second.get("https://d.org/docs/page")
    assert result.from_cache
    assert "real content" in result.text
    assert result.url == "https://d.org/real.html"
    assert result.followed_from == "https://d.org/docs/page"
    assert len(calls) == 2, "a rerun must not re-fetch or re-follow"
