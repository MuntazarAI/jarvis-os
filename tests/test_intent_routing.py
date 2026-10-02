"""Regression tests for conversational intent routing.

Covers: greeting variants, identity queries, explicit memory writes,
memory queries, knowledge questions, action requests, and — critically —
that normal conversation is never presented as, nor silently becomes,
a memory-write operation.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.cognition.cognition import Understander  # noqa: E402
from jarvis.core.loop import Jarvis  # noqa: E402


def _jarvis():
    return Jarvis(home=tempfile.mkdtemp())


def test_greeting_variants_classify_as_greeting():
    understand = Understander().understand
    for text in ("hii", "hi", "hello", "hellooo", "heyy", "yo"):
        assert understand(text).intent == "greeting", text


def test_identity_queries_classify_as_identity():
    understand = Understander().understand
    for text in ("who are you", "who are you?", "what are you",
                 "what is your name", "tell me about yourself"):
        assert understand(text).intent == "identity", text


def test_hii_gets_greeting_not_memory():
    jarvis = _jarvis()
    try:
        result = jarvis.cycle_once("hii")
        assert result.intent == "greeting"
        assert "I recall:" not in result.response
        assert "What would you like me to do" not in result.response
    finally:
        jarvis.close()


def test_identity_gets_identity_response():
    jarvis = _jarvis()
    try:
        for text in ("who are you", "what are you"):
            result = jarvis.cycle_once(text)
            assert result.intent == "identity", text
            assert "JARVIS" in result.response
            assert "I recall:" not in result.response
            assert result.actions_taken == ["identified"]
    finally:
        jarvis.close()


def test_explicit_remember_writes_clean_fact():
    jarvis = _jarvis()
    try:
        result = jarvis.cycle_once("remember that I am working on JARVIS")
        assert any("stored fact" in a for a in result.actions_taken)
        facts = [m.content for m in jarvis.palace.all(tier="semantic")
                 if "JARVIS" in m.content]
        assert facts, "explicit remember must store a fact"
        assert not any(f.lower().startswith("that ") for f in facts), facts
    finally:
        jarvis.close()


def test_memory_query_lists_what_was_stored():
    jarvis = _jarvis()
    try:
        jarvis.cycle_once("remember that I am working on JARVIS")
        result = jarvis.cycle_once("what do you remember?")
        assert "I am working on JARVIS" in result.response, result.response
        assert result.actions_taken == ["daily_memory"]
    finally:
        jarvis.close()


def test_memory_query_empty_store_says_so():
    jarvis = _jarvis()
    try:
        result = jarvis.cycle_once("what do you remember?")
        assert "don't have anything stored" in result.response, result.response
    finally:
        jarvis.close()


def test_knowledge_question_answered_without_memory_prefix():
    jarvis = _jarvis()
    try:
        with patch.object(jarvis, "_ask_model", return_value="Paris is the capital of France."):
            result = jarvis.cycle_once("what is the capital of France?")
        assert result.intent == "question"
        assert "I recall:" not in result.response
        assert "paris" in result.response.lower(), result.response
    finally:
        jarvis.close()


def test_action_request_executes_tool():
    jarvis = _jarvis()
    try:
        result = jarvis.cycle_once("calculate 2 + 3 * 4")
        assert "python_run" in result.tools_used
        assert "14" in result.response
    finally:
        jarvis.close()


def test_normal_conversation_never_becomes_memory_write():
    jarvis = _jarvis()
    try:
        before = {m.id for m in jarvis.palace.all(tier="semantic")}
        result = jarvis.cycle_once("the sky is blue today")
        assert result.intent == "statement"
        assert "I recall:" not in result.response
        assert "What would you like me to do" not in result.response
        after = {m.id for m in jarvis.palace.all(tier="semantic")}
        leaked = [jarvis.palace.get(mid).content for mid in after - before
                  if "sky is blue" in jarvis.palace.get(mid).content]
        assert not leaked, f"conversation leaked into facts: {leaked}"
    finally:
        jarvis.close()
