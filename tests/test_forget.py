"""Forgetting: a memory the operator asks to be gone is gone.

The vault, the approval store and the device state are protected
elsewhere; this is about the operator's own memories.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.memory.palace import MemoryPalace  # noqa: E402


@pytest.fixture
def palace():
    return MemoryPalace(":memory:")


def test_forget_removes_a_memory(palace):
    mem = palace.remember("something to forget")
    assert palace.forget(mem.id) is True
    assert palace.get(mem.id) is None
    assert mem.id not in {m.id for m in palace.all(include_archived=True)}


def test_forget_unknown_memory_is_false(palace):
    assert palace.forget("mem-does-not-exist") is False


def test_forget_does_not_touch_the_others(palace):
    keep = palace.remember("keep this one")
    drop = palace.remember("drop this one")
    assert palace.forget(drop.id) is True
    assert palace.get(keep.id) is not None


def test_forgetting_twice_is_false_the_second_time(palace):
    mem = palace.remember("gone once")
    assert palace.forget(mem.id) is True
    assert palace.forget(mem.id) is False


def test_forget_returns_true_for_an_archived_memory(palace):
    mem = palace.remember("archived then forgotten")
    palace.archive(mem.id, reason="test")
    assert palace.forget(mem.id) is True
    assert palace.get(mem.id) is None
