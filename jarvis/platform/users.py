"""One JARVIS per person, with their conversations.

Every account gets its own home directory under the platform root:

    <root>/users/<user-id>/config.json      their settings
    <root>/users/<user-id>/jarvis.db         their memory
    <root>/users/<user-id>/events.db         their event log
    <root>/users/<user-id>/conversations.json  their conversation list
    <root>/users/<user-id>/chat/<id>.jsonl   one file per conversation
    <root>/users/<user-id>/logs/             their logs

That is the whole isolation story: JARVIS already keeps everything
under its home directory, so a separate home *is* a separate JARVIS.
One person's memory can never appear in another person's answers,
because they are different stores on disk.

The instance is created on first use and kept warm, so the second
message is as fast as the first.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any

#: A conversation turn.
MAX_MESSAGE_CHARS = 8000
#: How many turns are kept in one conversation file.
MAX_HISTORY_LINES = 2000
#: How many conversations one person keeps.
MAX_CONVERSATIONS = 100


def new_conversation_id() -> str:
    """An opaque conversation id."""
    return "c-" + secrets.token_hex(6)


class UserSpace:
    """One person's JARVIS."""

    def __init__(self, user_id: str, home: Path, template: Path | None = None
                 ) -> None:
        self.user_id = user_id
        self.home = Path(home)
        self.template = Path(template) if template else None
        self._jarvis: Any = None
        self._lock = threading.Lock()

    # -- files -------------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.home / "config.json"

    @property
    def conversations_path(self) -> Path:
        return self.home / "conversations.json"

    @property
    def chat_dir(self) -> Path:
        return self.home / "chat"

    def ensure_home(self) -> None:
        """Create the home and seed it from the template config."""
        self.home.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.home, 0o700)
        except OSError:
            pass
        if self.template and self.template.exists() and \
                not self.config_path.exists():
            try:
                self.config_path.write_text(
                    self.template.read_text(encoding="utf-8"),
                    encoding="utf-8")
            except OSError:
                pass

    # -- the instance ------------------------------------------------------
    def jarvis(self) -> Any:
        """The warm JARVIS for this person."""
        if self._jarvis is None:
            with self._lock:
                if self._jarvis is None:
                    self.ensure_home()
                    from ..core.config import JarvisConfig
                    from ..core.loop import Jarvis
                    config = JarvisConfig.load(self.home)
                    self._jarvis = Jarvis(config, home=str(self.home))
        return self._jarvis

    def close(self) -> None:
        """Let go of the instance (its files are already on disk)."""
        with self._lock:
            jarvis, self._jarvis = self._jarvis, None
        if jarvis is not None:
            try:
                jarvis.close()
            except Exception:
                pass

    # -- conversations -----------------------------------------------------
    def _load_index(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.conversations_path.read_text(
                encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return data if isinstance(data, list) else []

    def _save_index(self, items: list[dict[str, Any]]) -> None:
        try:
            self.home.mkdir(parents=True, exist_ok=True)
            self.conversations_path.write_text(
                json.dumps(items, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass

    def conversations(self) -> list[dict[str, Any]]:
        """Every conversation, newest first."""
        items = self._load_index()
        items.sort(key=lambda item: float(item.get("updated_at", 0)),
                   reverse=True)
        return items

    def conversation(self, conversation_id: str) -> dict[str, Any] | None:
        for item in self._load_index():
            if item.get("id") == conversation_id:
                return item
        return None

    def new_conversation(self, title: str = "") -> dict[str, Any]:
        """Start a conversation."""
        now = time.time()
        item = {"id": new_conversation_id(), "title": str(title)[:120],
                "created_at": now, "updated_at": now}
        items = self._load_index()
        items.append(item)
        # Keep the list bounded: the oldest ones go first.
        items.sort(key=lambda entry: float(entry.get("updated_at", 0)))
        while len(items) > MAX_CONVERSATIONS:
            old = items.pop(0)
            try:
                (self.chat_dir / f"{old.get('id')}.jsonl").unlink(
                    missing_ok=True)
            except OSError:
                pass
        self._save_index(items)
        return item

    def rename_conversation(self, conversation_id: str, title: str) -> bool:
        items = self._load_index()
        found = False
        for item in items:
            if item.get("id") == conversation_id:
                item["title"] = str(title)[:120]
                item["updated_at"] = time.time()
                found = True
        if found:
            self._save_index(items)
        return found

    def delete_conversation(self, conversation_id: str) -> bool:
        items = self._load_index()
        keep = [item for item in items if item.get("id") != conversation_id]
        if len(keep) == len(items):
            return False
        self._save_index(keep)
        try:
            (self.chat_dir / f"{conversation_id}.jsonl").unlink(missing_ok=True)
        except OSError:
            pass
        return True

    def _chat_file(self, conversation_id: str) -> Path:
        return self.chat_dir / f"{conversation_id}.jsonl"

    # -- turns -------------------------------------------------------------
    def record(self, conversation_id: str, role: str, text: str,
               **extra: Any) -> dict[str, Any]:
        """Append one turn to a conversation."""
        entry = {"role": role, "text": str(text)[:MAX_MESSAGE_CHARS],
                 "at": time.time()}
        entry.update(extra)
        try:
            self.chat_dir.mkdir(parents=True, exist_ok=True)
            path = self._chat_file(conversation_id)
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
            self._trim(conversation_id)
            self.rename_conversation(conversation_id, entry.get("title", ""))
        except OSError:
            pass
        return entry

    def _trim(self, conversation_id: str) -> None:
        """Keep the conversation file bounded."""
        path = self._chat_file(conversation_id)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        if len(lines) <= MAX_HISTORY_LINES:
            return
        keep = lines[-MAX_HISTORY_LINES:]
        try:
            path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except OSError:
            pass

    def history(self, conversation_id: str, limit: int = 100) -> list[dict]:
        """The turns of one conversation."""
        try:
            lines = self._chat_file(conversation_id).read_text(
                encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[dict[str, Any]] = []
        for line in lines[-max(1, int(limit)):]:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                out.append(entry)
        return out

    def clear_history(self, conversation_id: str) -> None:
        """Empty a conversation."""
        try:
            self._chat_file(conversation_id).unlink(missing_ok=True)
        except OSError:
            pass


class UserRegistry:
    """Every account's space, warm or cold."""

    def __init__(self, root: str | Path, template_config: Path | None = None
                 ) -> None:
        self.root = Path(root)
        self.template_config = template_config
        self._spaces: dict[str, UserSpace] = {}
        self._lock = threading.Lock()

    def space(self, user_id: str) -> UserSpace:
        """The space for a user id."""
        with self._lock:
            space = self._spaces.get(user_id)
            if space is None:
                space = UserSpace(user_id,
                                  self.root / "users" / user_id,
                                  self.template_config)
                self._spaces[user_id] = space
            return space

    def known(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._spaces

    def close_all(self) -> None:
        with self._lock:
            spaces = list(self._spaces.values())
            self._spaces.clear()
        for space in spaces:
            space.close()


__all__ = ["UserSpace", "UserRegistry", "MAX_MESSAGE_CHARS",
           "MAX_HISTORY_LINES", "MAX_CONVERSATIONS", "new_conversation_id"]
