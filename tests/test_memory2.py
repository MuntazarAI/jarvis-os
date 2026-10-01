"""Memory 2.0 + World expectations tests."""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.core.loop import Jarvis  # noqa: E402
from jarvis.memory.decisions import DecisionLog, PreferenceStore  # noqa: E402
from jarvis.memory.palace import MemoryPalace  # noqa: E402
from jarvis.world.model import WorldModel  # noqa: E402


def test_decisions_recorded_and_recalled():
    palace = MemoryPalace()
    log = DecisionLog(palace)
    log.decide("use ollama locally", reasons=["privacy"], alternatives=["cloud"])
    assert len(log.decisions()) == 1
    assert "rejected" in log.decisions()[0].content
    assert log.recall("ollama")[0].kind == "decision"


def test_preferences_strengthen_flip_correct():
    palace = MemoryPalace()
    store = PreferenceStore(palace)
    first = store.prefer("concise answers")
    assert first.metadata["polarity"] == "like"
    second = store.prefer("concise answers")
    assert second.id == first.id and second.importance > first.importance
    flipped = store.prefer("concise answers", polarity="dislike")
    assert flipped.metadata["polarity"] == "dislike" and len(store.all()) == 1
    assert store.correct("verbose logs", "quiet logs").metadata["polarity"] == "like"
    assert store.find("something entirely unrelated xyz") is None


def test_world_expectations():
    world = WorldModel()
    world.expect("disk_percent_used", maximum=95.0)
    assert world.check_expectations() == []
    world.expect("load_1", maximum=-1.0)
    violations = world.check_expectations()
    assert violations and violations[0]["status"] == "unexpected"
    world.expect("nope_metric", maximum=1.0)
    assert any(v["status"] == "unknown" for v in world.check_expectations())


def test_loop_preferences_and_decisions():
    jarvis = Jarvis(home=tempfile.mkdtemp())
    try:
        reply = jarvis.cycle_once("i prefer concise answers").response
        assert "like" in reply.lower(), reply
        assert len(PreferenceStore(jarvis.palace).all()) == 1
        assert "Recorded decision" in jarvis.cycle_once("decide ship friday").response
        assert len(DecisionLog(jarvis.palace).decisions()) == 1
    finally:
        jarvis.close()
