"""Service + conversation runtime tests."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.conversation import ConversationManager, ConversationSession  # noqa: E402
from jarvis.core.loop import Jarvis  # noqa: E402


def test_session_turns_timeout_reset():
    session = ConversationSession(timeout_s=60)
    session.add("hi", "hello", "greeting")
    assert len(session.turns) == 1 and not session.expired
    assert session.context()["recent"][0]["input"] == "hi"
    session.reset()
    assert session.turns == [] and session.summary == ""
    old = ConversationSession(timeout_s=-1)
    assert old.expired


def test_session_compression():
    session = ConversationSession()
    for i in range(5):
        session.add(f"question {i}", f"answer {i}", "statement")
    summary = session.compress(keep=2)
    assert len(session.turns) == 2 and len(summary) > 0
    assert session.compress(keep=10) == summary


def test_manager_lifecycle():
    manager = ConversationManager(timeout_s=60)
    first = manager.get_or_create()
    assert manager.get_or_create(first.session_id).session_id == first.session_id
    assert manager.get("missing") is None
    assert manager.reset(first.session_id) and not manager.reset("missing")
    stale = manager.get_or_create()
    stale.last_active = 0
    stale.timeout_s = -1
    assert manager.prune() >= 1
    assert manager.get(stale.session_id) is None


def test_manager_turn_and_clarification(tmp_path):
    jarvis = Jarvis(home=str(tmp_path))
    try:
        manager = ConversationManager()
        first = manager.turn(jarvis, "", "remember my editor is helix")
        sid = first["session"]
        assert first["context"]["turns"] == 1
        second = manager.turn(jarvis, sid, "which editor do i use?")
        assert "helix" in second["response"].lower()
        assert manager.needs_clarification(
            "statement", 0.3,
            "I don't have a verified answer yet. Could you tell me more?")
        assert not manager.needs_clarification("command", 0.8, "Working.")
        assert not manager.needs_clarification("statement", 0.8, "Noted.")
        question = manager.clarify("do the task", "the target", ["context"])
        assert "target" in question
    finally:
        jarvis.close()


def test_long_conversation_auto_compresses(tmp_path):
    jarvis = Jarvis(home=str(tmp_path))
    try:
        manager = ConversationManager()
        session_id = ""
        for i in range(12):
            turn = manager.turn(jarvis, session_id, f"note number {i}")
            session_id = turn["session"]
        session = manager.get(session_id)
        assert session is not None and len(session.turns) <= 100
    finally:
        jarvis.close()
