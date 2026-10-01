"""Browser agent tests. Extraction is offline; fetch/search need network."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.browser.agent import BrowserAgent  # noqa: E402


HTML = """
<html><head><title>Test Page</title></head>
<body>
<script>var x = 1;</script>
<h1>Hello World</h1>
<p>See <a href="/docs">the docs</a> and <a href="https://example.com">example</a>.</p>
<form action="/search" method="post"><input name="q" type="text"></form>
</body></html>
"""


def test_extract_offline():
    page = BrowserAgent.extract("https://site.test/a", HTML)
    assert page.title == "Test Page"
    assert "Hello World" in page.text and "var x" not in page.text
    assert page.secure and page.words >= 5
    hrefs = [link["href"] for link in page.links]
    assert "https://site.test/docs" in hrefs and "https://example.com" in hrefs
    assert page.forms[0]["action"] == "/search"
    assert page.forms[0]["inputs"][0]["name"] == "q"


def test_verify_logic():
    agent = BrowserAgent()
    page = BrowserAgent.extract("https://site.test/", HTML)
    assert agent.verify(page, "hello")["ok"]
    assert not agent.verify(page, "zzz-no-such-word")["ok"]


def test_rejects_non_http():
    assert not BrowserAgent().fetch("ftp://x")["ok"]


def test_fetch_live():
    agent = BrowserAgent()
    result = agent.fetch("https://example.com", actor="test")
    if not result["ok"]:
        pytest.skip(f"no network: {result['error']}")
    page = result["page"]
    assert page["title"] == "Example Domain" and page["secure"]
    assert len(agent.audit_trail()) == 1
    assert agent.audit_trail()[0]["actor"] == "test"


def test_search_live():
    result = BrowserAgent().search("python programming language", count=3)
    if not result["ok"]:
        pytest.skip(f"no network: {result['error']}")
    assert isinstance(result["results"], list)
