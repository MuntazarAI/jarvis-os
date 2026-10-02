"""Conversational Intelligence 2.0: dialogue acts, context, safety invariants."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.cognition.dialogue import (  # noqa: E402
    NON_ACTING,
    DialogueAct,
    DialogueContext,
    DialogueRouter,
)
from jarvis.core.loop import Jarvis  # noqa: E402


def _route(text, coarse="", context=None):
    return DialogueRouter().route(text, coarse, context or DialogueContext())


def test_mission_examples():
    assert _route("remember that I use Linux", "command").act == DialogueAct.MEMORY_WRITE
    assert _route("what do you remember about my computer?", "question").act == DialogueAct.MEMORY_QUERY
    assert _route("who are you?", "question").act == DialogueAct.IDENTITY
    assert _route("what can you do").act == DialogueAct.CAPABILITY
    assert _route("open Firefox", "command").act == DialogueAct.COMPUTER_ACTION
    assert _route("what is Python?", "question").act == DialogueAct.KNOWLEDGE
    assert _route("continue my JARVIS project", "statement").act == DialogueAct.PROJECT
    assert _route("do it", "statement").act == DialogueAct.CLARIFICATION
    assert _route("hii", "greeting").act == DialogueAct.GREETING
    assert _route("calculate 2+2", "command").act == DialogueAct.TOOL_ACTION
    assert _route("remind me at 5pm", "command").act == DialogueAct.TASK


def test_cancellation_always_maps_to_cancellation_act():
    # "stop" is a cancellation request whether or not a task is running;
    # the loop decides what to say. CONFIRMATION is reserved for yes/no.
    assert _route("stop", "confirmation").act == DialogueAct.CANCELLATION
    ctx = DialogueContext(active_task="deploy site")
    assert _route("stop", "confirmation", ctx).act == DialogueAct.CANCELLATION
    assert _route("yes", "confirmation").act == DialogueAct.CONFIRMATION


def test_bare_action_resolves_to_task_or_project_only():
    assert _route("do it", "statement",
                  DialogueContext(active_task="deploy")).resolved_text == "deploy"
    assert _route("do it", "statement",
                  DialogueContext(active_project="jarvis")).resolved_text == "jarvis"
    # Informational topic must NOT satisfy a bare action.
    assert _route("do it", "statement",
                  DialogueContext(active_topic="what is Python?")).act == DialogueAct.CLARIFICATION


def test_pronoun_resolution_and_dangling():
    ctx = DialogueContext(last_entities=["Firefox"])
    resolved = _route("open it", "command", ctx)
    assert resolved.act == DialogueAct.COMPUTER_ACTION
    assert resolved.resolved_text == "open Firefox"
    assert _route("open it", "command").act == DialogueAct.CLARIFICATION
    assert _route("delete that file", "command").act == DialogueAct.CLARIFICATION
    # Complementizer "that" in remember-statements is not a reference.
    assert _route("remember that I use Linux", "command").act == DialogueAct.MEMORY_WRITE


def test_non_acting_acts_cover_readonly_paths():
    for act in (DialogueAct.GREETING, DialogueAct.IDENTITY,
                DialogueAct.KNOWLEDGE, DialogueAct.MEMORY_QUERY,
                DialogueAct.CONVERSATION):
        assert act in NON_ACTING
    assert DialogueAct.TOOL_ACTION not in NON_ACTING
    assert DialogueAct.COMPUTER_ACTION not in NON_ACTING


def test_loop_capability_and_cancellation():
    jarvis = Jarvis(home=tempfile.mkdtemp())
    try:
        cap = jarvis.cycle_once("what can you do")
        assert cap.intent == "capability" and cap.tools_used == []
        assert "remember" in cap.response.lower()
        cancel = jarvis.cycle_once("stop")
        assert cancel.tools_used == []
        assert "nothing" in cancel.response.lower()
    finally:
        jarvis.close()


def test_loop_cancels_single_open_task():
    jarvis = Jarvis(home=tempfile.mkdtemp())
    try:
        task = jarvis.tasks.register("deploy the site")
        jarvis.tasks.next_ready()
        assert task.state.value == "running"
        # Route directly with the active-task context the loop would build.
        route = jarvis.dialogue.route(
            "stop", "confirmation",
            DialogueContext(active_task="deploy the site"))
        assert route.act == DialogueAct.CANCELLATION
    finally:
        jarvis.close()


def test_question_never_executes_action_tools():
    """Read-only acts may use the LLM but must never touch a real tool.

    'llm' is the generative model, not an action surface; every other tool
    (filesystem, terminal, computer, network) must stay untouched.
    """
    jarvis = Jarvis(home=tempfile.mkdtemp())
    try:
        for question in ("what is Python?",
                         "what do you remember?",
                         "who are you",
                         "what can you do"):
            result = jarvis.cycle_once(question)
            action_tools = [t for t in result.tools_used if t != "llm"]
            assert action_tools == [], (question, action_tools)
    finally:
        jarvis.close()


def test_knowledge_prefers_model_over_weak_recall():
    jarvis = Jarvis(home=tempfile.mkdtemp())
    try:
        jarvis.cycle_once("remember the deploy key is rotated monthly")
        with patch.object(jarvis, "_ask_model", return_value="Paris is the capital of France."):
            result = jarvis.cycle_once("what is the capital of France?")
        assert "paris" in result.response.lower()
        assert "I recall:" not in result.response
        relevant = jarvis.cycle_once("what is the deploy key schedule?")
        assert "deploy key is rotated monthly" in relevant.response
    finally:
        jarvis.close()


def test_pronoun_turn_uses_session_entity():
    from jarvis.cognition.dialogue import DialogueRouter
    context = DialogueRouter.build_context(
        recent_turns=[{"input": "open Firefox to check mail"}])
    assert "Firefox" in context.last_entities
    assert context.active_topic.startswith("open Firefox")
