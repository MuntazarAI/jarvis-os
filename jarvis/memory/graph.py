"""Personal knowledge graph: nodes, typed relations, traversal, versioning."""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..core.types import new_id, now


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'entity',
    attributes TEXT NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    history TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    src TEXT NOT NULL,
    rel TEXT NOT NULL,
    dst TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.6,
    since REAL NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    attrs TEXT NOT NULL DEFAULT '{}',
    UNIQUE(src, rel, dst)
);
CREATE INDEX IF NOT EXISTS idx_edge_src ON edges(src);
CREATE INDEX IF NOT EXISTS idx_edge_dst ON edges(dst);
CREATE TABLE IF NOT EXISTS identity (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    aliases TEXT NOT NULL DEFAULT '[]',
    confidence REAL NOT NULL DEFAULT 0.5,
    linked TEXT NOT NULL DEFAULT '[]'
);
"""


@dataclass
class Node:
    name: str
    kind: str = "entity"
    attributes: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    version: int = 1
    first_seen: float = field(default_factory=now)
    last_seen: float = field(default_factory=now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "attributes": self.attributes,
            "confidence": self.confidence,
            "version": self.version,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
        }


@dataclass
class Edge:
    src: str
    rel: str
    dst: str
    confidence: float = 0.6
    attrs: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    since: float = field(default_factory=now)


class KnowledgeGraph:
    """Nodes for User/People/Projects/Places/Devices; typed relationships."""

    def __init__(self, path: str = ":memory:") -> None:
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- nodes -----------------------------------------------------------
    def upsert_node(
        self,
        name: str,
        kind: str = "entity",
        attributes: dict[str, Any] | None = None,
        confidence: float = 0.5,
    ) -> Node:
        attributes = attributes or {}
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM nodes WHERE name = ?", (name,)
            ).fetchone()
            ts = now()
            if row is None:
                node = Node(name=name, kind=kind, attributes=attributes, confidence=confidence)
                self._conn.execute(
                    "INSERT INTO nodes (name, kind, attributes, confidence, first_seen, last_seen,"
                    " version, history) VALUES (?,?,?,?,?,?,1,?)",
                    (
                        name, kind, json.dumps(attributes, default=str), confidence,
                        ts, ts, json.dumps([{"version": 1, "at": ts, "kind": kind}]),
                    ),
                )
            else:
                merged = {**json.loads(row["attributes"] or "{}"), **attributes}
                history = json.loads(row["history"] or "[]")
                version = row["version"] + 1
                history.append({"version": version, "at": ts, "kind": kind, "attributes": attributes})
                self._conn.execute(
                    "UPDATE nodes SET kind = ?, attributes = ?, confidence = MAX(confidence, ?),"
                    " last_seen = ?, version = ?, history = ? WHERE name = ?",
                    (kind, json.dumps(merged, default=str), confidence, ts, version,
                     json.dumps(history), name),
                )
                node = Node(name=name, kind=kind, attributes=merged,
                            confidence=max(row["confidence"], confidence), version=version)
            self._conn.commit()
        return node

    def ensure_node(self, name: str, kind: str = "entity") -> Node:
        """Create the node only if missing. Never alters an existing node."""
        existing = self.get_node(name)
        if existing is not None:
            return existing
        return self.upsert_node(name, kind=kind)

    def get_node(self, name: str) -> Node | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM nodes WHERE name = ?", (name,)).fetchone()
        if not row:
            return None
        return Node(
            name=row["name"], kind=row["kind"], attributes=json.loads(row["attributes"] or "{}"),
            confidence=row["confidence"], version=row["version"],
            first_seen=row["first_seen"], last_seen=row["last_seen"],
        )

    def nodes(self, kind: str | None = None) -> list[Node]:
        sql = "SELECT name FROM nodes"
        args: list[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            args.append(kind)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [n for n in (self.get_node(r["name"]) for r in rows) if n]

    def node_versions(self, name: str) -> list[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT history FROM nodes WHERE name = ?", (name,)).fetchone()
        return json.loads(row["history"]) if row else []

    # -- edges -----------------------------------------------------------
    def relate(
        self, src: str, rel: str, dst: str, confidence: float = 0.6, attrs: dict[str, Any] | None = None
    ) -> Edge:
        attrs = attrs or {}
        with self._lock:
            # ensure endpoints exist without altering their kinds/attributes
            if self.get_node(src) is None:
                self.upsert_node(src)
            if self.get_node(dst) is None:
                self.upsert_node(dst)
            row = self._conn.execute(
                "SELECT * FROM edges WHERE src = ? AND rel = ? AND dst = ?", (src, rel, dst)
            ).fetchone()
            ts = now()
            if row is None:
                edge = Edge(src=src, rel=rel, dst=dst, confidence=confidence, attrs=attrs)
                self._conn.execute(
                    "INSERT INTO edges (src, rel, dst, confidence, since, version, attrs)"
                    " VALUES (?,?,?,?,?,1,?)",
                    (src, rel, dst, confidence, ts, json.dumps(attrs, default=str)),
                )
            else:
                merged = {**json.loads(row["attrs"] or "{}"), **attrs}
                version = row["version"] + 1
                self._conn.execute(
                    "UPDATE edges SET confidence = MAX(confidence, ?), version = ?, attrs = ?"
                    " WHERE id = ?",
                    (confidence, version, json.dumps(merged, default=str), row["id"]),
                )
                edge = Edge(src=src, rel=rel, dst=dst,
                            confidence=max(row["confidence"], confidence), attrs=merged,
                            version=version, since=row["since"])
            self._conn.commit()
        return edge

    def unrelate(self, src: str, rel: str, dst: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM edges WHERE src = ? AND rel = ? AND dst = ?", (src, rel, dst)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def neighbors(self, name: str, rel: str | None = None, direction: str = "both") -> list[tuple[str, str, float]]:
        """Return (other, relation, confidence) triples adjacent to name."""
        out: list[tuple[str, str, float]] = []
        sql = "SELECT src, rel, dst, confidence FROM edges WHERE (src = ? OR dst = ?)"
        args: list[Any] = [name, name]
        if rel:
            sql += " AND rel = ?"
            args.append(rel)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        for row in rows:
            if direction in ("both", "out") and row["src"] == name:
                out.append((row["dst"], row["rel"], row["confidence"]))
            if direction in ("both", "in") and row["dst"] == name:
                out.append((row["src"], row["rel"], row["confidence"]))
        return out

    def traverse(self, name: str, depth: int = 2, min_confidence: float = 0.0) -> dict[str, list[str]]:
        """Breadth-first traversal returning reachable nodes by hop count."""
        levels: dict[str, list[str]] = {name: [name]}
        frontier = [name]
        seen = {name}
        for hop in range(1, depth + 1):
            nxt: list[str] = []
            for node in frontier:
                for other, _rel, conf in self.neighbors(node):
                    if conf < min_confidence or other in seen:
                        continue
                    seen.add(other)
                    nxt.append(other)
                    levels.setdefault(f"hop{hop}", []).append(other)
            frontier = nxt
            if not frontier:
                break
        return levels

    def paths(self, src: str, dst: str, max_depth: int = 4) -> list[list[str]]:
        """Shortest relationship chains between two entities."""
        found: list[list[str]] = []
        queue: list[list[str]] = [[src]]
        visited = {src}
        while queue:
            path = queue.pop(0)
            if len(path) > max_depth:
                continue
            node = path[-1]
            if node == dst and len(path) > 1:
                found.append(list(path))
                continue
            for other, _rel, _conf in self.neighbors(node):
                if other not in visited:
                    visited.add(other)
                    queue.append(path + [other])
        return found

    def edge_list(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM edges").fetchall()
        return [
            {"src": r["src"], "rel": r["rel"], "dst": r["dst"],
             "confidence": r["confidence"], "version": r["version"]}
            for r in rows
        ]

    def related_entities(self, name: str, limit: int = 10) -> list[str]:
        scored = sorted(self.neighbors(name), key=lambda t: -t[2])
        return [n for n, _r, _c in scored[:limit]]

    # -- identity --------------------------------------------------------
    def register_identity(
        self, kind: str, label: str, aliases: list[str] | None = None,
        confidence: float = 0.6, linked: list[str] | None = None,
    ) -> str:
        ident = new_id("idn")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO identity (id, kind, label, aliases, confidence, linked)"
                " VALUES (?,?,?,?,?,?)",
                (ident, kind, label, json.dumps(aliases or []), confidence,
                 json.dumps(linked or [])),
            )
            self._conn.commit()
        return ident

    def resolve_identity(self, label: str) -> dict[str, Any] | None:
        target = label.strip().lower()
        with self._lock:
            rows = self._conn.execute("SELECT * FROM identity").fetchall()
        for row in rows:
            names = {row["label"].lower(), *[a.lower() for a in json.loads(row["aliases"])]}
            if target in names:
                return {
                    "id": row["id"], "kind": row["kind"], "label": row["label"],
                    "confidence": row["confidence"], "linked": json.loads(row["linked"]),
                }
        return None

    def stats(self) -> dict[str, Any]:
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
            e = self._conn.execute("SELECT COUNT(*) AS c FROM edges").fetchone()["c"]
            i = self._conn.execute("SELECT COUNT(*) AS c FROM identity").fetchone()["c"]
        return {"nodes": n, "edges": e, "identities": i}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def extract_entities(text: str) -> list[str]:
    """Lightweight proper-noun and identifier extraction."""
    import re

    names = re.findall(r"\b(?:[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})*)\b", text)
    idents = re.findall(r"\b[A-Za-z][\w.-]*[-_/][\w./-]+\b", text)
    quoted = re.findall(r"[\"“']([^\"”']{3,40})[\"”']", text)
    seen: dict[str, None] = {}
    for item in [*names, *idents, *quoted]:
        seen.setdefault(item.strip(), None)
    return list(seen)
