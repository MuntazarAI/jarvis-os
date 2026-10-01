"""Memory Palace: typed tiers, spatial rooms, metadata and retrieval."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

from ..core.config import JarvisConfig
from ..core.types import content_hash, new_id, now


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    tier TEXT NOT NULL,
    room TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT DEFAULT '',
    source TEXT DEFAULT '',
    modality TEXT DEFAULT 'text',
    confidence REAL DEFAULT 0.6,
    importance REAL DEFAULT 0.5,
    sensitivity TEXT DEFAULT 'normal',
    privacy TEXT DEFAULT 'private',
    provenance TEXT DEFAULT '',
    related_entities TEXT DEFAULT '[]',
    related_memories TEXT DEFAULT '[]',
    related_events TEXT DEFAULT '[]',
    valid_from REAL NOT NULL,
    valid_until REAL,
    created_at REAL NOT NULL,
    last_accessed REAL NOT NULL,
    access_count INTEGER DEFAULT 0,
    archived INTEGER DEFAULT 0,
    expired INTEGER DEFAULT 0,
    fingerprint TEXT NOT NULL,
    vector TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_mem_tier ON memories(tier, archived, expired);
CREATE INDEX IF NOT EXISTS idx_mem_room ON memories(room);
CREATE INDEX IF NOT EXISTS idx_mem_time ON memories(valid_from);
CREATE INDEX IF NOT EXISTS idx_mem_fp ON memories(fingerprint);
CREATE TABLE IF NOT EXISTS entities (
    name TEXT PRIMARY KEY,
    kind TEXT DEFAULT 'unknown',
    attributes TEXT DEFAULT '{}',
    confidence REAL DEFAULT 0.5,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    version INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    relation TEXT NOT NULL,
    target TEXT NOT NULL,
    confidence REAL DEFAULT 0.6,
    since REAL NOT NULL,
    version INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source);
CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target);
CREATE TABLE IF NOT EXISTS links (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    kind TEXT DEFAULT 'related',
    PRIMARY KEY (from_id, to_id, kind)
);
"""

TIERS = (
    "working",
    "short_term",
    "long_term",
    "episodic",
    "semantic",
    "procedural",
    "spatial",
    "observation",
    "evidence",
    "hypothesis",
    "conversation",
    "project",
    "relationship",
)


@dataclass
class Memory:
    content: str
    tier: str = "short_term"
    room: str = "Home"
    kind: str = "note"
    source: str = ""
    modality: str = "text"
    confidence: float = 0.6
    importance: float = 0.5
    sensitivity: str = "normal"
    privacy: str = "private"
    provenance: str = ""
    related_entities: list[str] = field(default_factory=list)
    related_memories: list[str] = field(default_factory=list)
    related_events: list[str] = field(default_factory=list)
    valid_from: float = field(default_factory=now)
    valid_until: float | None = None
    vector: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: new_id("mem"))
    created_at: float = field(default_factory=now)
    last_accessed: float = field(default_factory=now)
    access_count: int = 0
    archived: bool = False
    expired: bool = False

    def fingerprint(self) -> str:
        base = f"{self.tier}|{self.kind}|{content_hash(self.content)}"
        if self.related_entities:
            base += "|" + "|".join(sorted(self.related_entities))
        return base

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2]


def embed(text: str, dim: int = 64) -> list[float]:
    """Deterministic hashed bag-of-tokens embedding. No external model needed."""
    vec = [0.0] * dim
    for token in tokenize(text):
        h = int(content_hash(token)[:12], 16)
        vec[h % dim] += 1.0
        second = (h >> 7) % dim
        vec[second] -= 0.5
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(size))
    na = math.sqrt(sum(v * v for v in a[:size]))
    nb = math.sqrt(sum(v * v for v in b[:size]))
    return dot / (na * nb) if na and nb else 0.0


class MemoryPalace:
    """Rooms + tiers + metadata + retrieval over SQLite."""

    def __init__(self, path: str = ":memory:", config: JarvisConfig | None = None) -> None:
        self.config = config or JarvisConfig()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        self.dim = self.config.models.embedding_dim

    # -- write -----------------------------------------------------------
    def remember(
        self,
        content: str,
        tier: str = "short_term",
        room: str = "Home",
        **kwargs: Any,
    ) -> Memory:
        if tier not in TIERS:
            raise ValueError(f"unknown tier: {tier}")
        kwargs.setdefault("vector", embed(content, self.dim))
        mem = Memory(content=content, tier=tier, room=room, **kwargs)
        fp = mem.fingerprint()
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM memories WHERE fingerprint = ? AND archived = 0", (fp,)
            ).fetchone()
            if existing:
                self._conn.execute(
                    "UPDATE memories SET access_count = access_count + 1, last_accessed = ?"
                    " WHERE id = ?",
                    (now(), existing["id"]),
                )
                self._conn.commit()
                found = self.get(existing["id"])
                assert found is not None
                return found
            self._conn.execute(
                "INSERT INTO memories (id, tier, room, kind, content, summary, source, modality,"
                " confidence, importance, sensitivity, privacy, provenance, related_entities,"
                " related_memories, related_events, valid_from, valid_until, created_at,"
                " last_accessed, access_count, archived, expired, fingerprint, vector, metadata)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mem.id, mem.tier, mem.room, mem.kind, mem.content,
                    kwargs.get("summary", ""), mem.source, mem.modality, mem.confidence,
                    mem.importance, mem.sensitivity, mem.privacy, mem.provenance,
                    json.dumps(mem.related_entities), json.dumps(mem.related_memories),
                    json.dumps(mem.related_events), mem.valid_from, mem.valid_until,
                    mem.created_at, mem.last_accessed, mem.access_count,
                    int(mem.archived), int(mem.expired), fp,
                    json.dumps(mem.vector), json.dumps(mem.metadata),
                ),
            )
            for rid in mem.related_memories:
                self._link(mem.id, rid)
            self._conn.commit()
        return mem

    def store_observation(self, content: str, **kw: Any) -> Memory:
        return self.remember(content, tier="observation", **kw)

    def store_episode(self, content: str, **kw: Any) -> Memory:
        return self.remember(content, tier="episodic", **kw)

    def store_fact(self, content: str, **kw: Any) -> Memory:
        return self.remember(content, tier="semantic", **kw)

    def store_procedure(self, content: str, **kw: Any) -> Memory:
        return self.remember(content, tier="procedural", **kw)

    def store_conversation(self, role: str, text: str, session_id: str, **kw: Any) -> Memory:
        return self.remember(
            f"{role}: {text}",
            tier="conversation",
            kind="utterance",
            source=role,
            metadata={"session_id": session_id, **kw.pop("metadata", {})},
            **kw,
        )

    # -- read ------------------------------------------------------------
    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            tier=row["tier"],
            room=row["room"],
            kind=row["kind"],
            content=row["content"],
            source=row["source"],
            modality=row["modality"],
            confidence=row["confidence"],
            importance=row["importance"],
            sensitivity=row["sensitivity"],
            privacy=row["privacy"],
            provenance=row["provenance"],
            related_entities=json.loads(row["related_entities"]),
            related_memories=json.loads(row["related_memories"]),
            related_events=json.loads(row["related_events"]),
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            created_at=row["created_at"],
            last_accessed=row["last_accessed"],
            access_count=row["access_count"],
            archived=bool(row["archived"]),
            expired=bool(row["expired"]),
            vector=json.loads(row["vector"]),
            metadata=json.loads(row["metadata"]),
        )

    def get(self, memory_id: str) -> Memory | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        return self._row_to_memory(row) if row else None

    def all(
        self,
        tier: str | None = None,
        room: str | None = None,
        include_archived: bool = False,
        limit: int = 500,
    ) -> list[Memory]:
        sql = "SELECT * FROM memories WHERE 1=1"
        args: list[Any] = []
        if tier:
            sql += " AND tier = ?"
            args.append(tier)
        if room:
            sql += " AND room = ?"
            args.append(room)
        if not include_archived:
            sql += " AND archived = 0 AND expired = 0"
        sql += " ORDER BY importance DESC, last_accessed DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def rooms(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT room, COUNT(*) AS c FROM memories WHERE archived = 0"
                " GROUP BY room ORDER BY c DESC"
            ).fetchall()
        return {r["room"]: r["c"] for r in rows}

    def tiers(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT tier, COUNT(*) AS c FROM memories WHERE archived = 0 GROUP BY tier"
            ).fetchall()
        return {r["tier"]: r["c"] for r in rows}

    # -- operations ------------------------------------------------------
    def update(self, memory_id: str, **changes: Any) -> Memory | None:
        allowed = {
            "content", "room", "tier", "kind", "confidence", "importance",
            "sensitivity", "privacy", "summary_note",
        }
        fields = {k: v for k, v in changes.items() if k in allowed}
        if "content" in fields:
            fields["vector"] = json.dumps(embed(str(fields["content"]), self.dim))
        if not fields:
            return self.get(memory_id)
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._conn.execute(
                f"UPDATE memories SET {assignments} WHERE id = ?",
                (*fields.values(), memory_id),
            )
            self._conn.commit()
        return self.get(memory_id)

    def merge(self, memory_ids: list[str], into: str | None = None) -> Memory | None:
        """Merge several memories into one record."""
        mems = [m for m in (self.get(mid) for mid in memory_ids) if m]
        if not mems:
            return None
        if len(mems) == 1 and not into:
            return mems[0]
        if into:
            base = self.get(into)
            if base:
                mems = mems + [base]
        merged_text = "\n".join(m.content for m in mems)
        entities: list[str] = []
        for m in mems:
            for e in m.related_entities:
                if e not in entities:
                    entities.append(e)
        target = mems[0]
        new_mem = self.remember(
            merged_text,
            tier=target.tier,
            room=target.room,
            kind=target.kind,
            source="merge",
            confidence=max(m.confidence for m in mems),
            importance=max(m.importance for m in mems),
            related_entities=entities,
            metadata={"merged_from": [m.id for m in mems]},
        )
        for m in mems:
            if m.id != new_mem.id:
                self.archive(m.id, reason="merged")
        return new_mem

    def forget(self, memory_id: str) -> bool:
        """Hard delete — respects explicit deletion requests."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def archive(self, memory_id: str, reason: str = "") -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT metadata FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if not row:
                return False
            meta = json.loads(row["metadata"] or "{}")
            if reason:
                meta["archive_reason"] = reason
            cur = self._conn.execute(
                "UPDATE memories SET archived = 1, metadata = ? WHERE id = ?",
                (json.dumps(meta, default=str), memory_id),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def expire(self, memory_id: str) -> bool:
        """Mark a memory expired without deleting it (reversible)."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET expired = 1 WHERE id = ?", (memory_id,)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def restore(self, memory_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE memories SET archived = 0, expired = 0 WHERE id = ?", (memory_id,)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def decay_score(self, mem: Memory) -> float:
        """Recency + frequency + importance, with exponential time decay."""
        half_life = self.config.memory.decay_half_life_days * 86400.0
        age = max(0.0, now() - mem.created_at)
        recency = math.exp(-age / half_life) if half_life > 0 else 0.0
        frequency = min(1.0, mem.access_count / 10.0)
        return round(0.5 * recency + 0.2 * frequency + 0.3 * mem.importance, 6)

    def compress(self, memory_ids: list[str], summary: str) -> Memory | None:
        """Compress several memories into a summary, archiving the originals."""
        if not memory_ids:
            return None
        out = self.remember(summary, tier="episodic", kind="summary", source="compress",
                            metadata={"compressed_from": list(memory_ids)})
        for mid in memory_ids:
            self.archive(mid, reason="compressed")
        return out

    def _link(self, from_id: str, to_id: str, kind: str = "related") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO links (from_id, to_id, kind) VALUES (?,?,?)",
                (from_id, to_id, kind),
            )
            self._conn.commit()

    def linked(self, memory_id: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT to_id FROM links WHERE from_id = ?"
                " UNION SELECT from_id FROM links WHERE to_id = ?",
                (memory_id, memory_id),
            ).fetchall()
        return [r[0] for r in rows]

    # -- retrieval -------------------------------------------------------
    def search(
        self,
        query: str,
        limit: int = 10,
        tier: str | None = None,
        room: str | None = None,
        semantic: bool = True,
    ) -> list[tuple[Memory, float]]:
        """Hybrid retrieval: keyword overlap + vector similarity + decay."""
        candidates = self.all(tier=tier, room=room, limit=2000)
        qvec = embed(query, self.dim)
        qtokens = set(tokenize(query))
        scored: list[tuple[Memory, float]] = []
        for mem in candidates:
            mtokens = set(tokenize(mem.content))
            keyword = len(qtokens & mtokens) / len(qtokens) if qtokens else 0.0
            vector = cosine(qvec, mem.vector) if semantic else 0.0
            score = 0.45 * keyword + 0.35 * max(0.0, vector) + 0.20 * self.decay_score(mem)
            if score > 0.01:
                scored.append((mem, round(score, 6)))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        top = scored[:limit]
        self._touch([m.id for m, _ in top])
        return top

    def temporal_search(self, start: float, end: float, limit: int = 50) -> list[Memory]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE valid_from >= ? AND valid_from <= ?"
                " ORDER BY valid_from LIMIT ?",
                (start, end, limit),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def expired_since(self, ts: float) -> list[Memory]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE valid_until IS NOT NULL AND valid_until <= ?"
                " AND expired = 0",
                (ts,),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def stale(self, days: float) -> list[Memory]:
        cutoff = now() - days * 86400
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memories WHERE archived = 0 AND last_accessed < ?"
                " ORDER BY last_accessed",
                (cutoff,),
            ).fetchall()
        return [self._row_to_memory(r) for r in rows]

    def contradictions_candidates(self) -> list[tuple[Memory, Memory]]:
        """Pairs of memories that assert the same subject with differing polarity."""
        pairs: list[tuple[Memory, Memory]] = []
        by_subject: dict[str, list[Memory]] = {}
        for mem in self.all(tier="semantic", limit=1000):
            for ent in mem.related_entities:
                by_subject.setdefault(ent, []).append(mem)
        neg = re.compile(r"\b(not|no longer|never|stopped|disabled|removed)\b", re.I)
        for subject, mems in by_subject.items():
            if len(mems) < 2:
                continue
            for i, a in enumerate(mems):
                for b in mems[i + 1:]:
                    if bool(neg.search(a.content)) != bool(neg.search(b.content)):
                        pairs.append((a, b))
        return pairs

    def _touch(self, ids: Iterable[str]) -> None:
        ids = list(ids)
        if not ids:
            return
        with self._lock:
            self._conn.executemany(
                "UPDATE memories SET access_count = access_count + 1, last_accessed = ?"
                " WHERE id = ?",
                [(now(), mid) for mid in ids],
            )
            self._conn.commit()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()["c"]
            archived = self._conn.execute(
                "SELECT COUNT(*) AS c FROM memories WHERE archived = 1"
            ).fetchone()["c"]
            entities = self._conn.execute("SELECT COUNT(*) AS c FROM entities").fetchone()["c"]
            relations = self._conn.execute("SELECT COUNT(*) AS c FROM relations").fetchone()["c"]
        return {
            "total": total,
            "archived": archived,
            "live": total - archived,
            "entities": entities,
            "relations": relations,
            "tiers": self.tiers(),
            "rooms": self.rooms(),
        }

    def export(self, path: str) -> str:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM memories").fetchall()
        payload = [self._row_to_memory(r).to_dict() for r in rows]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)
        return path

    def close(self) -> None:
        with self._lock:
            self._conn.close()
