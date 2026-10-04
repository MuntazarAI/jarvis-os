"""Conversational voice loop tests (5.3). Deterministic, no mic/net.

Fakes stand in for mic/STT/speech; the loop, session linkage,
turn-taking bounds, interruption, and latency accounting are real.
"""

from __future__ import annotations

import threading

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.core.loop import Jarvis
from jarvis.voice.runtime import VoiceLoop


class _FakeJarvis:
    def __init__(self):
        self.turns = 0

    def cycle_once(self, text, source="voice", session_id=""):
        self.turns += 1
        from types import SimpleNamespace
        return SimpleNamespace(response=f"heard {text}",
                               intent="conversed")

    def close(self):
        pass


def _loop(**kw):
    kw.setdefault("jarvis_voice", True)
    kw.setdefault("voice_config", {"tts_provider": "fake"})
    kw.setdefault("workdir", "/tmp/jarvis-voice-test-53")
    loop = VoiceLoop(**kw)
    loop.listen_once = lambda addressed=True: {
        "ok": True, "text": "hello jarvis"}
    return loop


def test_conversational_turn_uses_jarvis_voice(tmp_path):
    loop = _loop(workdir=str(tmp_path))
    fake = _FakeJarvis()
    turn = loop.converse_once(fake)
    assert turn["ok"] is True
    assert turn["voice_session_id"] == loop.session.session_id
    assert turn["spoken"]["ok"] is True
    assert "think_ms" in turn and turn["think_ms"] >= 0.0


def test_session_links_turns(tmp_path):
    loop = _loop(workdir=str(tmp_path))
    fake = _FakeJarvis()
    first = loop.converse_once(fake)
    second = loop.converse_once(fake)
    assert first["voice_session_id"] == second["voice_session_id"]
    assert (first["turn"]["transcript_id"]
            != second["turn"]["transcript_id"])
    assert loop.session.interaction_count == 2


def test_max_turns_bounds_run(tmp_path):
    loop = _loop(workdir=str(tmp_path), max_turns=3)
    summary = loop.run(_FakeJarvis())
    assert summary == {"ok": True, "turns": 3, "turn_ms": summary["turn_ms"]}
    assert summary["turn_ms"]["avg"] >= 0.0


def test_stop_signals_exit(tmp_path):
    loop = _loop(workdir=str(tmp_path))
    stop = threading.Event()
    stop.set()
    summary = loop.run(_FakeJarvis(), stop=stop)
    assert summary["turns"] == 0
    assert loop.stop() is False  # nothing speaking, no crash


def test_legacy_speaker_path_untouched(tmp_path):
    loop = VoiceLoop(workdir=str(tmp_path))
    assert loop.jarvis_voice is False
    assert loop.max_turns == 0


def test_run_summary_latencies(tmp_path):
    loop = _loop(workdir=str(tmp_path), max_turns=2)
    summary = loop.run(_FakeJarvis())
    stats = summary["turn_ms"]
    assert stats["max"] >= stats["avg"] >= 0.0
    assert stats["p95"] <= stats["max"]
