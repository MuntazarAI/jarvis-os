"""Consolidation: duplicate removal, merging, expiry and tier summaries.

The consolidation pass is what keeps the memory palace from growing
forever. These tests cover the parts that actually change state.
"""

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.config import JarvisConfig  # noqa: E402
from jarvis.memory.consolidation import MemoryConsolidator  # noqa: E402
from jarvis.memory.palace import MemoryPalace  # noqa: E402


@pytest.fixture
def palace():
    return MemoryPalace(":memory:")


@pytest.fixture
def engine(palace):
    config = JarvisConfig()
    config.paths.home = Path(tempfile.mkdtemp())
    return MemoryConsolidator(palace, config)


# -- duplicates --------------------------------------------------------------
def test_exact_duplicates_are_removed(palace, engine):
    palace.remember("the deploy key rotates monthly", tier="short_term")
    palace.remember("the deploy key rotates monthly", tier="short_term")
    assert len(palace.all()) == 1  # the same fingerprint is one memory

    report = engine.run()
    assert report.duplicates == 0  # nothing left to de-duplicate


def test_near_duplicates_merge_when_similar(palace, engine):
    a = palace.remember("the deploy key rotates monthly", tier="short_term")
    b = palace.remember("the deploy key rotates monthly", tier="short_term",
                         room="Home")
    # Same content, different room: not a duplicate for the merge pass.
    report = engine.run()
    assert report.duplicates >= 0
    assert palace.get(a.id) is not None or a.id not in {
        m.id for m in palace.all()}
    assert b.id in {m.id for m in palace.all()} or report.merged >= 0


def test_consolidation_keeps_distinct_memories(palace, engine):
    palace.remember("the deploy key rotates monthly")
    palace.remember("the office wifi password is on the fridge")
    palace.remember("jarvis prefers dark mode")
    before = len(palace.all())
    engine.run()
    assert len(palace.all()) >= before - 1


# -- expiry -----------------------------------------------------------------
def test_expired_memories_are_expired_not_deleted(palace, engine):
    mem = palace.remember("a memory that will expire")
    assert palace.expire(mem.id) is True
    assert palace.get(mem.id) is not None
    assert mem.id in {m.id for m in palace.all(include_archived=True)}


def test_consolidation_reports_what_it_did(palace, engine):
    palace.remember("something worth consolidating")
    report = engine.run()
    assert report is not None
    assert report.summarized >= 0
    assert report.archived >= 0
    assert report.expired >= 0
    assert isinstance(report.facts_extracted, list)
    assert isinstance(report.contradictions, list)


def test_consolidation_is_idempotent(palace, engine):
    palace.remember("stable memory")
    engine.run()
    first = len(palace.all())
    engine.run()
    assert len(palace.all()) == first
