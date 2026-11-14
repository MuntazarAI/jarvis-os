"""Archiving: a memory moves out of the live set but is not destroyed.

Archiving is the reversible half of forgetting: the memory stops being
returned by default queries and stays recoverable.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.memory.palace import MemoryPalace  # noqa: E402


@pytest.fixture
def palace():
    return MemoryPalace(":memory:")


def test_archive_hides_a_memory_from_the_live_set(palace):
    mem = palace.remember("a memory to archive")
    assert palace.archive(mem.id, reason="no longer relevant") is True
    live = {m.id for m in palace.all()}
    assert mem.id not in live
    everything = {m.id for m in palace.all(include_archived=True)}
    assert mem.id in everything


def test_archived_memory_is_still_readable(palace):
    mem = palace.remember("still here")
    palace.archive(mem.id, reason="test")
    assert palace.get(mem.id) is not None


def test_archive_unknown_memory_is_false(palace):
    assert palace.archive("mem-does-not-exist") is False


def test_restore_brings_a_memory_back(palace):
    mem = palace.remember("temporarily archived")
    palace.archive(mem.id, reason="test")
    assert palace.restore(mem.id) is True
    assert mem.id in {m.id for m in palace.all()}


def test_archiving_twice_stays_archived(palace):
    mem = palace.remember("archived once")
    assert palace.archive(mem.id, reason="first") is True
    # Archiving is idempotent: a second call is harmless.
    assert palace.archive(mem.id, reason="second") is True
    assert mem.id not in {m.id for m in palace.all()}
    assert mem.id in {m.id for m in palace.all(include_archived=True)}


def test_archive_records_the_reason(palace):
    mem = palace.remember("why it was archived")
    palace.archive(mem.id, reason="superseded by the new policy")
    row = palace._conn.execute(
        "SELECT metadata FROM memories WHERE id = ?", (mem.id,)).fetchone()
    assert row is not None
    assert "superseded" in str(row["metadata"])
