"""Topic subscriptions (World Intel 1.1).

User-managed watch list persisted as bounded atomic JSON
(`worldintel-topics.json` in home). Separate from code-side
`WorldConfig.topics`: the store is runtime-mutable via CLI, the
config holds operator defaults. Research merges both.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

TOPICS_FILENAME = "worldintel-topics.json"
MAX_TOPICS = 50
MAX_TOPIC_CHARS = 120


class TopicStore:
    def __init__(self, home: str | Path | None) -> None:
        self.home = Path(home) if home else None
        self._topics: dict[str, float] = {}
        self.load()

    @property
    def path(self) -> Path | None:
        if self.home is None:
            return None
        return self.home / TOPICS_FILENAME

    def load(self) -> None:
        path = self.path
        self._topics = {}
        if path is None or not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(raw, dict):
            for name, added in (raw.get("topics") or {}).items():
                if isinstance(name, str) and name.strip():
                    self._topics[name.strip()[:MAX_TOPIC_CHARS]] = \
                        float(added or 0.0)

    def save(self) -> None:
        path = self.path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".worldintel-topics-",
                                       dir=str(path.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"version": 1, "topics": self._topics},
                              handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except OSError:
            pass

    def add(self, topic: str) -> bool:
        topic = str(topic or "").strip()[:MAX_TOPIC_CHARS]
        if not topic or topic in self._topics:
            return False
        if len(self._topics) >= MAX_TOPICS:
            return False
        self._topics[topic] = time.time()
        self.save()
        return True

    def remove(self, topic: str) -> bool:
        topic = str(topic or "").strip()
        for name in list(self._topics):
            if name.lower() == topic.lower():
                del self._topics[name]
                self.save()
                return True
        return False

    def list(self) -> list[dict[str, Any]]:
        return [{"topic": name, "since": added}
                for name, added in sorted(self._topics.items())]

    def names(self) -> list[str]:
        return sorted(self._topics)


__all__ = ["TopicStore", "TOPICS_FILENAME", "MAX_TOPICS"]
