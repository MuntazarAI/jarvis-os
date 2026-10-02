"""Memory 3.0: provenance taxonomy, new tiers, correct/reinforce."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.memory.palace import (  # noqa: E402
    ORIGINS,
    TIERS,
    MemoryPalace,
    infer_origin,
    origin_of,
)


def test_provenance_taxonomy():
    assert set(ORIGINS) == {"told", "inferred", "observed", "hypothesis", "system"}
    assert infer_origin("user") == "told"
    assert infer_origin("cli") == "told"
    assert infer_origin("voice") == "told"
    assert infer_origin("camera") == "observed"
    assert infer_origin("sensor") == "observed"
    assert infer_origin("consolidation") == "inferred"
    assert infer_origin("hypothesis") == "hypothesis"
    assert infer_origin("anything-else") == "system"


def test_new_tiers_accepted():
    assert {"goal", "temporal", "environmental", "decision"} <= set(TIERS)
    palace = MemoryPalace()
    for tier in ("goal", "temporal", "environmental", "decision"):
        mem = palace.remember(f"content for {tier}", tier=tier)
        assert mem.tier == tier
    try:
        palace.remember("x", tier="nope")
        raise AssertionError("unknown tier must fail")
    except ValueError:
        pass


def test_origin_stored_and_explained():
    palace = MemoryPalace()
    told = palace.remember("my editor is helix", tier="semantic", source="user")
    assert told.origin == "told"
    assert origin_of(told).startswith("I remember this because you explicitly told me")
    seen = palace.remember("motion detected", tier="observation", source="sensor")
    assert "observation" in origin_of(seen).lower()
    guess = palace.remember("maybe disk full", tier="hypothesis", source="hypothesis")
    assert "hypothesis" in origin_of(guess).lower()
    derived = palace.remember("merged note", tier="semantic", source="merge")
    assert "inferred" in origin_of(derived).lower()
    try:
        palace.remember("x", origin="bogus")
        raise AssertionError("unknown origin must fail")
    except ValueError:
        pass


def test_origin_filter_and_update():
    palace = MemoryPalace()
    palace.remember("told fact", tier="semantic", source="user")
    palace.remember("seen thing", tier="observation", source="camera")
    assert len(palace.all(origin="told")) == 1
    assert len(palace.all(origin="observed")) == 1
    assert palace.all(origin="hypothesis") == []
    try:
        palace.all(origin="bogus")
        raise AssertionError("unknown origin filter must fail")
    except ValueError:
        pass
    mem = palace.remember("adjust me", tier="semantic", source="user")
    updated = palace.update(mem.id, origin="inferred")
    assert updated is not None and updated.origin == "inferred"
    try:
        palace.update(mem.id, origin="bogus")
        raise AssertionError("bad origin update must fail")
    except ValueError:
        pass


def test_correct_supersedes_with_link():
    palace = MemoryPalace()
    old = palace.remember("the sky is green", tier="semantic", source="user")
    new = palace.correct(old.id, "the sky is blue", reason="user corrected me")
    assert new is not None and new.content == "the sky is blue"
    assert new.metadata["corrects"] == old.id
    assert palace.get(old.id).archived
    assert palace.correct("missing-id", "x") is None


def test_reinforce_strengthens():
    palace = MemoryPalace()
    mem = palace.remember("useful fact", tier="semantic", source="user",
                          confidence=0.5, importance=0.5)
    stronger = palace.reinforce(mem.id)
    assert stronger is not None
    assert stronger.confidence > 0.5 and stronger.importance > 0.5
    capped = palace.reinforce(mem.id, amount=5.0)
    assert capped is not None
    assert capped.confidence <= 1.0 and capped.importance <= 1.0
    assert palace.reinforce("missing-id") is None


def test_store_goal_and_legacy_migration(tmp_path):
    import sqlite3
    import time

    palace = MemoryPalace()
    goal = palace.store_goal("ship v1.5")
    assert goal.tier == "goal" and goal.kind == "goal"

    path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, tier TEXT NOT NULL,"
                 " room TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL,"
                 " summary TEXT DEFAULT '', source TEXT DEFAULT '',"
                 " modality TEXT DEFAULT 'text', confidence REAL DEFAULT 0.6,"
                 " importance REAL DEFAULT 0.5, sensitivity TEXT DEFAULT 'normal',"
                 " privacy TEXT DEFAULT 'private', provenance TEXT DEFAULT '',"
                 " related_entities TEXT DEFAULT '[]', related_memories TEXT DEFAULT '[]',"
                 " related_events TEXT DEFAULT '[]', valid_from REAL NOT NULL,"
                 " valid_until REAL, created_at REAL NOT NULL, last_accessed REAL NOT NULL,"
                 " access_count INTEGER DEFAULT 0, archived INTEGER DEFAULT 0,"
                 " expired INTEGER DEFAULT 0, fingerprint TEXT NOT NULL,"
                 " vector TEXT DEFAULT '[]', metadata TEXT DEFAULT '{}')")
    stamp = time.time()
    conn.execute("INSERT INTO memories (id,tier,room,kind,content,source,valid_from,"
                 "created_at,last_accessed,fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 ("mem-old", "semantic", "Home", "fact", "legacy fact",
                  "user", stamp, stamp, stamp, "fp1"))
    conn.commit()
    conn.close()
    migrated = MemoryPalace(path)
    rows = migrated.all()
    assert len(rows) == 1 and rows[0].origin == "told"
