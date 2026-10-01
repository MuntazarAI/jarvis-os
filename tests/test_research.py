"""Research engine tests. Web-dependent parts skip cleanly offline."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.research.engine import ResearchEngine  # noqa: E402


def test_plan_kinds():
    assert ResearchEngine.plan("how do I fix pip")["kind"] == "howto"
    assert ResearchEngine.plan("X vs Y")["kind"] == "comparison"
    assert ResearchEngine.plan("what is photosynthesis")["kind"] == "factual"
    assert len(ResearchEngine._query_backoffs("aaa bbb cccc dddd eeeee")) == 3
    assert ResearchEngine._query_backoffs("hi you") == ["hi you"]


def test_credibility_rules():
    assert ResearchEngine.credibility("https://docs.python.org/3/", 500)[0] > 0.7
    assert ResearchEngine.credibility("https://en.wikipedia.org/wiki/X", 500)[0] > 0.7
    assert ResearchEngine.credibility("http://x.tk/", 10)[0] < 0.4
    assert "not https" in ResearchEngine.credibility("http://x.com/", 500)[1]


def test_wiki_backoff_finds_something():
    hits = ResearchEngine().wiki_search("python virtual environments venv")
    if not hits:
        import pytest
        pytest.skip("wikipedia unreachable")
    assert hits[0]["url"].startswith("https://en.wikipedia.org/wiki/")


def test_research_end_to_end():
    report = ResearchEngine().research("python virtual environments venv")
    if not report.sources:
        import pytest
        pytest.skip("no research sources reachable (search throttled, wiki down)")
    assert report.citations and report.confidence > 0
    assert report.to_dict()["query"].startswith("python")
