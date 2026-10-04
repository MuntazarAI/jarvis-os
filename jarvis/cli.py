"""JARVIS command line: talk, serve, status, mentalist, remember."""

from __future__ import annotations

import argparse
import json
import os
import sys
import subprocess
from typing import Any
from pathlib import Path

from .core.config import JarvisConfig
from .core.loop import Jarvis


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS — Personal AI OS")
    parser.add_argument("--home", default="", help="state directory (default ~/.jarvis-os)")
    sub = parser.add_subparsers(dest="command")

    talk = sub.add_parser("talk", help="send one input through the loop")
    talk.add_argument("text", nargs="+", help="what to say to JARVIS")

    repl_parser = sub.add_parser("repl", help="interactive prompt (Ctrl-D to quit)")
    repl_parser.add_argument("--speak", action="store_true",
                             help="speak every reply aloud via the JARVIS voice stack")

    serve = sub.add_parser("serve", help="start the HTTP + WebSocket API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--token", default="")

    brd = sub.add_parser("board", help="local status board URL "
                                      "(served by `jarvis serve`)")
    brd.add_argument("--host", default="127.0.0.1")
    brd.add_argument("--port", type=int, default=8765)
    brd.add_argument("--open", action="store_true",
                     help="open the board in the default browser")

    rmt = sub.add_parser("remote", help="phone/local remote URL "
                                        "(served by `jarvis serve`)")
    rmt.add_argument("--host", default="127.0.0.1")
    rmt.add_argument("--port", type=int, default=8765)
    rmt.add_argument("--open", action="store_true",
                     help="open the remote in the default browser")

    sub.add_parser("status", help="print system status JSON")
    status_parser = sub.add_parser("status-summary",
                                   help="one-line-per-system human status")

    prf = sub.add_parser("proof", help="show receipts for a claim: "
                                       "memory, tasks, policy audit")
    prf.add_argument("claim", nargs="+", help="what to prove")
    prf.add_argument("--json", action="store_true",
                     help="machine-readable output")

    fb = sub.add_parser("feedback", help="record feedback as a memory "
                                         "episode for review")
    fb.add_argument("text", nargs="+", help="the feedback")

    su = sub.add_parser("setup", help="guided first-run checklist: "
                                     "home, dependencies, voice, next steps")

    gev = sub.add_parser("gods-eye", help="manage the local God's Eye View application")
    gev.add_argument("action", nargs="?", default="status",
                     choices=["status", "install", "start", "stop", "open",
                              "live-sync", "live-query", "live-status",
                              "live-promote", "live-doctor"])
    gev.add_argument("--allow-remote", action="store_true",
                     help="explicit consent for live network egress")
    gev.add_argument("--provider", action="append", default=[],
                     help="live provider name (repeatable)")
    gev.add_argument("--lat", type=float, default=28.6)
    gev.add_argument("--lon", type=float, default=77.2)
    gev.add_argument("--radius-km", type=float, default=500.0)
    gev.add_argument("--kind", default="")
    gev.add_argument("--limit", type=int, default=20)
    gev.add_argument("--key", default="", help="live observation key to promote")
    gev.add_argument("--approve", action="store_true",
                     help="explicit approval for live promotion")

    men = sub.add_parser("mentalist", help="evidence-gated analysis of a situation")
    men.add_argument("text", nargs="+")

    rem = sub.add_parser("remember", help="store a fact in the palace")
    rem.add_argument("text", nargs="+")
    rem.add_argument("--room", default="Knowledge Library")

    sub.add_parser("consolidate", help="run memory consolidation now")

    see = sub.add_parser("see", help="camera/screen/file observation into memory")
    see.add_argument("source", nargs="?", default="screen",
                     choices=["screen", "camera", "file"])
    see.add_argument("--path", default="", help="image path for source=file")
    see.add_argument("--fast", action="store_true",
                     help="OCR-only, skip the slow scene model")
    see.add_argument("--ask", default="Briefly describe what you see.")

    sub.add_parser("devices", help="capability snapshot: voice, vision, computer, models")

    fab = sub.add_parser("device-fabric", help="distributed device mesh: enroll, trust, route")
    fab.add_argument("action", nargs="?", default="status",
                     choices=["status", "list", "info", "register",
                              "enroll-local", "discover", "unregister",
                              "trust", "distrust", "revoke", "quarantine",
                              "release", "enable", "disable",
                              "capabilities", "heartbeat", "sweep",
                              "locate", "command", "doctor"])
    fab.add_argument("--device", default="", help="device id")
    fab.add_argument("--name", default="", help="device name for register/discover")
    fab.add_argument("--type", default="unknown", help="device type for register")
    fab.add_argument("--reason", default="", help="reason for trust decisions")
    fab.add_argument("--by", default="user", help="actor for trust decisions")
    fab.add_argument("--capability", default="",
                     help="capability for command / declare (repeatable via comma list)")
    fab.add_argument("--args", default="",
                     help="JSON object of command args for command")
    fab.add_argument("--room", default="",
                     help="room/area name for locate (empty clears to UNKNOWN)")
    fab.add_argument("--approve", default="",
                     help="policy approval token for command")
    fab.add_argument("--json", action="store_true",
                     help="machine-readable output")

    dev = sub.add_parser("device", help="device endpoints: android node, socket transport")
    dev.add_argument("area", nargs="?", default="android",
                     choices=["android", "transport", "grants", "approvals",
                              "commands", "policy", "audit", "outbox"])
    dev.add_argument("action", nargs="?", default="status",
                     choices=["status", "list", "info", "register", "pair",
                              "trust", "revoke", "unpair", "capabilities",
                              "permissions", "command", "connect",
                              "disconnect", "queue", "serve", "peers",
                              "approve", "inspect", "grants", "grant",
                              "suspend", "restore", "deny", "command-status",
                              "cancel", "outbox", "audit", "show", "watch"])
    dev.add_argument("--device", default="", help="device id")
    dev.add_argument("--command-id", default="",
                     help="durable command id (command-status, cancel)")
    dev.add_argument("--approval", default="",
                     help="durable approval token (approve, deny)")
    dev.add_argument("--state", default="",
                     help="filter by state (approvals/commands list)")
    dev.add_argument("--actor-name", default="",
                     help="actor for policy grants (default: --by value)")
    dev.add_argument("--permission", default="",
                     help="policy permission (policy grant/revoke)")
    dev.add_argument("--timeout", type=float, default=0.0,
                     help="watch timeout seconds (0 = until Ctrl-C)")
    dev.add_argument("--name", default="", help="node name for register")
    dev.add_argument("--code", default="", help="6-digit pairing code")
    dev.add_argument("--node", default="",
                     help="node id the Android app asserts during pair")
    dev.add_argument("--reason", default="", help="reason for trust decisions")
    dev.add_argument("--by", default="user", help="actor for trust decisions")
    dev.add_argument("--model", default="",
                     help="android device model for register")
    dev.add_argument("--android-version", default="",
                     help="android version string for register")
    dev.add_argument("--app-version", default="",
                     help="node app version string for register")
    dev.add_argument("--owner", default="", help="owner for register")
    dev.add_argument("--capability", default="",
                     help="capability list (comma-separated) for declare")
    dev.add_argument("--report", default="",
                     help="JSON permission report for permissions")
    dev.add_argument("--command", dest="node_command", default="",
                     help="typed command to send")
    dev.add_argument("--args", default="",
                     help="JSON object of command args")
    dev.add_argument("--approve", default="",
                     help="policy approval token for command")
    dev.add_argument("--port", type=int, default=0,
                     help="port for transport serve (0 = ephemeral)")
    dev.add_argument("--host", default="",
                     help="bind address for transport serve (default: loopback)")
    dev.add_argument("--json", action="store_true",
                     help="machine-readable output")

    pinode = sub.add_parser("pi", help="raspberry pi edge node")
    pinode.add_argument("action", nargs="?", default="status",
                        choices=["list", "show", "pair", "trust", "revoke",
                                 "status", "health", "capabilities",
                                 "sensors", "telemetry", "events", "queue",
                                 "doctor", "camera", "gpio", "logs",
                                 "command", "serve", "approve"])
    pinode.add_argument("--device", default="", help="device id")
    pinode.add_argument("--name", default="", help="node name for register")
    pinode.add_argument("--code", default="", help="6-digit pairing code")
    pinode.add_argument("--node", default="",
                        help="node id the Pi asserts during pair")
    pinode.add_argument("--reason", default="", help="reason for decisions")
    pinode.add_argument("--by", default="user", help="actor for decisions")
    pinode.add_argument("--model", default="",
                        help="pi model for register")
    pinode.add_argument("--os", default="", help="os version for register")
    pinode.add_argument("--arch", default="",
                        help="architecture for register")
    pinode.add_argument("--capability", default="",
                        help="capability list (comma-separated) for declare")
    pinode.add_argument("--command", dest="node_command", default="",
                        help="typed command to send")
    pinode.add_argument("--args", default="",
                        help="JSON object of command args")
    pinode.add_argument("--approve", default="",
                        help="policy approval token for command")
    pinode.add_argument("--pin", type=int, default=-1,
                        help="gpio pin number")
    pinode.add_argument("--value", type=int, default=-1,
                        help="gpio value 0|1")
    pinode.add_argument("--mode", default="",
                        help="gpio mode read|write for gpio read")
    pinode.add_argument("--sensor", default="",
                        help="sensor id for sensors read")
    pinode.add_argument("--port", type=int, default=0,
                        help="port for transport serve (0 = ephemeral)")
    pinode.add_argument("--host", default="",
                        help="bind address for transport serve")
    pinode.add_argument("--json", action="store_true",
                        help="machine-readable output")

    bench = sub.add_parser("benchmark", help="latency + resource benchmark")
    bench.add_argument("--samples", type=int, default=3)

    intel = sub.add_parser("intelligence", help="unified cognitive loop")
    intel.add_argument("action", nargs="?", default="status",
                       choices=["status", "cycle", "inspect", "replay",
                                "events", "failures", "perception-status",
                                "perception-observe", "perception-events",
                                "perception-inspect", "experience",
                                "beliefs", "learning", "hypotheses",
                                "goals", "skills", "scorecard", "benchmark",
                                "explain"])
    intel.add_argument("text", nargs="*", help="input text for cycle")
    intel.add_argument("--cycle", default="",
                       help="cycle id for inspect/replay")
    intel.add_argument("--source", default="screen",
                       choices=["screen", "camera", "file", "image"],
                       help="perception source for observe")
    intel.add_argument("--path", default="",
                       help="file/image path for observe")
    intel.add_argument("--observation", default="",
                       help="observation id for perception-inspect")
    intel.add_argument("--json", action="store_true",
                       help="machine-readable output")

    integration = sub.add_parser(
        "integration", help="experience diagnostics: subsystem checks, cycle trace")
    integration.add_argument("action", nargs="?", default="doctor",
                             choices=["doctor", "trace"])
    integration.add_argument("--cycle", default="",
                             help="correlation id for trace (e.g. cycle-3)")
    integration.add_argument("--session", default="",
                             help="caller session id for trace")
    integration.add_argument("--json", action="store_true",
                             help="machine-readable output")

    neu = sub.add_parser("neural", help="fly-brain neural substrate")
    neu.add_argument("action", nargs="?", default="status",
                     choices=["status", "benchmark", "snapshot"])
    neu.add_argument("--neurons", type=int, default=2000,
                     help="neurons for benchmark/snapshot")
    neu.add_argument("--json", action="store_true",
                     help="machine-readable output")

    sub.add_parser("start", help="start the JARVIS service (API server, supervised)")
    sub.add_parser("stop", help="stop the JARVIS service")
    sub.add_parser("restart", help="restart the JARVIS service")
    sub.add_parser("doctor", help="dependency + hardware + model health checks")

    svc = sub.add_parser("service", help="24/7 background service: lifecycle, health, logs")
    svc.add_argument("action", nargs="?", default="status",
                     choices=["start", "stop", "restart", "status",
                              "health", "doctor", "logs", "run"])
    svc.add_argument("--json", action="store_true",
                     help="machine-readable output")
    svc.add_argument("--lines", type=int, default=30,
                     help="log lines for service logs")

    ag = sub.add_parser("agents", help="multi-agent organization")
    ag.add_argument("action", nargs="?", default="list",
                    choices=["list", "status", "run", "explain", "teams",
                             "world"])
    ag.add_argument("text", nargs="*", help="goal text for run")
    ag.add_argument("--team", default="",
                    help="team strategy: research/coding/debugging/computer/decision/daily")
    ag.add_argument("--depth", type=int, default=None,
                    help="adaptive depth 0-5 (default: auto)")
    ag.add_argument("--task", default="", help="task id for explain")
    ag.add_argument("--json", action="store_true",
                    help="machine-readable output")

    dots = sub.add_parser("dots", help="persistent autonomous workers")
    dots.add_argument("action", nargs="?", default="list",
                      choices=["list", "create", "inspect", "start",
                               "pause", "resume", "stop", "status",
                               "explain", "wake", "schedule", "tick",
                               "notify"])
    dots.add_argument("--kind", default="",
                      help="schedule kind for dots schedule create")
    dots.add_argument("--config", default="",
                      help="JSON schedule config for dots schedule create")
    dots.add_argument("--tz", default="UTC", help="schedule timezone")
    dots.add_argument("--reason", default="",
                      help="reason/context for schedule or wake")
    dots.add_argument("--cooldown", type=float, default=300.0,
                      help="schedule cooldown seconds")
    dots.add_argument("text", nargs="*", help="id, name/goal, or event summary")
    dots.add_argument("--role", default="general")
    dots.add_argument("--priority", type=int, default=5)
    dots.add_argument("--workspace", default="",
                      help="workspace root path restriction")
    dots.add_argument("--tools", default="",
                      help="comma-separated allowed tools")
    dots.add_argument("--updates", default="",
                      help="comma-separated trigger subscriptions")
    dots.add_argument("--json", action="store_true",
                      help="machine-readable output")

    msn = sub.add_parser("missions", help="persistent multi-dot missions")
    msn.add_argument("action", nargs="?", default="list",
                     choices=["list", "create", "inspect", "start",
                              "pause", "resume", "stop", "cancel",
                              "status", "explain", "objectives", "verify",
                              "checkpoint", "recover", "advance",
                              "proposals", "control"])
    msn.add_argument("text", nargs="*", help="id, name/goal, or objective spec")
    msn.add_argument("--priority", type=int, default=5)
    msn.add_argument("--depends", default="",
                     help="comma-separated objective IDs")
    msn.add_argument("--weight", type=float, default=1.0)
    msn.add_argument("--dot", default="", help="dot ID for an objective")
    msn.add_argument("--criteria", default="",
                     help="JSON success criteria list")
    msn.add_argument("--reason", default="", help="reason/context")
    msn.add_argument("--json", action="store_true",
                     help="machine-readable output")

    tsk = sub.add_parser("task", help="durable autonomous tasks: "
                                      "create, run, recover, inspect")
    tsk.add_argument("action", nargs="?", default="list",
                     choices=["create", "list", "status", "inspect",
                              "run", "pause", "resume", "cancel",
                              "recover", "history", "doctor"])
    tsk.add_argument("text", nargs="*",
                     help="title for create, task id otherwise")
    tsk.add_argument("--steps", default="",
                     help="semicolon-separated step titles for create")
    tsk.add_argument("--priority", type=int, default=5)
    tsk.add_argument("--deadline-s", type=float, default=0.0,
                     help="seconds from now after which the task fails")
    tsk.add_argument("--reason", default="", help="reason/context")
    tsk.add_argument("--json", action="store_true",
                     help="machine-readable output")

    pro = sub.add_parser("proactive", help="proactive attention + decisions")
    pro.add_argument("action", nargs="?", default="status",
                     choices=["status", "candidates", "explain", "scan"])
    pro.add_argument("text", nargs="*", help="candidate id for explain")
    pro.add_argument("--json", action="store_true",
                     help="machine-readable output")

    say = sub.add_parser("say", help="speak text aloud via TTS")
    say.add_argument("text", nargs="+")
    say.add_argument("--style", default="",
                     choices=["", "normal", "warning", "error",
                              "confirmation", "uncertain"],
                     help="speaking style (default: saved profile)")

    listen = sub.add_parser("listen", help="voice turn: mic → STT → think → speak")
    listen.add_argument("--always", action="store_true",
                        help="respond even without the wake word")
    listen.add_argument("--loop", action="store_true",
                        help="keep conversing until Ctrl-C")
    listen.add_argument("--no-speak", action="store_true",
                        help="print the reply instead of speaking it")
    listen.add_argument("--voice", action="store_true",
                        help="speak via the JARVIS voice stack "
                             "(persistent TTS + fallback)")
    listen.add_argument("--max-turns", type=int, default=0,
                        help="stop after N turns (0 = until Ctrl-C)")

    audio = sub.add_parser("audio", help="audio perception: sources, VAD, STT, transcripts")
    audio.add_argument("action", nargs="?", default="status",
                       choices=["status", "capabilities", "sources", "test",
                                "replay", "benchmark", "transcript",
                                "diagnostics"])
    audio.add_argument("--path", default="",
                       help="wav file for transcript/test")
    audio.add_argument("--seconds", type=float, default=3.0,
                       help="mic record seconds for test")
    audio.add_argument("--timeout", type=float, default=0.0,
                       help="watch timeout (reserved)")
    audio.add_argument("--json", action="store_true",
                       help="machine-readable output")

    voice = sub.add_parser("voice", help="JARVIS voice: status, setup, test, benchmark")
    voice.add_argument("action", nargs="?", default="status",
                       choices=["status", "setup", "test", "benchmark",
                                "say", "diagnostics", "worker", "profile"])
    voice.add_argument("--style", default="",
                       help="speaking style for profile/say "
                            "(normal|warning|error|confirmation|uncertain)")
    voice.add_argument("--emotion", default="",
                       help="emotion for profile (free text, capped)")
    voice.add_argument("--op", default="status",
                       choices=["status", "start", "stop"],
                       help="worker lifecycle op (with: voice worker)")
    voice.add_argument("--path", default="",
                       help="reference audio path override for setup")
    voice.add_argument("--text", default="Good evening. How can I assist you?",
                       help="text for voice say/test")
    voice.add_argument("--no-play", action="store_true",
                       help="synthesize without playback")
    voice.add_argument("--json", action="store_true",
                       help="machine-readable output")

    voice_test = sub.add_parser("voice-test",
                                help="deterministic voice self-test (no mic/GPU/net)")
    voice_test.add_argument("--json", action="store_true",
                            help="machine-readable output")

    world = sub.add_parser("world", help="world intelligence: status, sources, search, events, research")
    world.add_argument("action", nargs="?", default="status",
                       choices=["status", "sources", "search", "events",
                                "changes", "refresh", "research",
                                "briefing", "health", "diagnostics",
                                "topics"])
    world.add_argument("--text", default="",
                       help="query for search/research/briefing")
    world.add_argument("--topic", default="",
                       help="topic for topics add/remove")
    world.add_argument("--notify", action="store_true",
                       help="emit proactive events for genuine changes "
                            "(with refresh)")

    grants = sub.add_parser("grants", help="standing grants: create, list, inspect, revoke")
    grants.add_argument("action", nargs="?", default="list",
                        choices=["create", "list", "show", "revoke"])
    grants.add_argument("--capability", default="",
                        help="capability, e.g. media.organize")
    grants.add_argument("--scope", default="",
                        help="scope resource, e.g. ~/Downloads")
    grants.add_argument("--scope-kind", default="path",
                        choices=["path", "device", "topic", "capability"],
                        help="scope kind")
    grants.add_argument("--allow", default="",
                        help="comma-separated allowed operations")
    grants.add_argument("--deny", default="",
                        help="comma-separated denied operations")
    grants.add_argument("--risk", default="low",
                        choices=["read_only", "low", "moderate", "high",
                                 "critical"],
                        help="risk class")
    grants.add_argument("--days", type=float, default=0.0,
                        help="expiry in days (0 = 30-day default)")
    grants.add_argument("--id", default="",
                        help="grant id for show/revoke")
    grants.add_argument("--json", action="store_true",
                        help="machine-readable output")

    sec = sub.add_parser("security", help="security: static self-review "
                                         "(review) and policy-gated dynamic "
                                         "scan (scan via Strix)")
    sec.add_argument("action", nargs="?", default="review",
                     choices=["review", "scan"])
    sec.add_argument("--target", default=".",
                     help="directory/file (review) or path/URL (scan)")
    sec.add_argument("--mode", default="quick",
                     choices=["quick", "standard", "deep"],
                     help="scan depth for `scan`")
    sec.add_argument("--timeout", type=float, default=600.0,
                     help="scan timeout seconds (30-3600)")
    sec.add_argument("--max-turns", type=int, default=100,
                     help="scan agent turn cap (1-500)")
    sec.add_argument("--yes", action="store_true",
                     help="REQUIRED for scan: confirms you own the target "
                          "or have explicit written permission to test it")
    sec.add_argument("--allow-nonlocal", action="store_true",
                     help="REQUIRED for scan: target is not local "
                          "(with --yes)")
    sec.add_argument("--json", action="store_true",
                     help="machine-readable output")

    backup = sub.add_parser(
        "backup",
        help="state backup: create, list, verify, restore (code lives on GitHub)")
    backup.add_argument("action", nargs="?", default="create",
                        choices=["create", "list", "verify", "restore"])
    backup.add_argument("--dest", default="",
                        help="backup directory (default ~/jarvis-backups)")
    backup.add_argument("--file", default="",
                        help="archive for verify/restore")
    backup.add_argument("--force", action="store_true",
                        help="required for restore")
    backup.add_argument("--keep", type=int, default=10,
                        help="archives to retain")
    backup.add_argument("--json", action="store_true",
                        help="machine-readable output")

    approvals = sub.add_parser(
        "approvals",
        help="policy approvals: list pending, approve, deny (single-use tokens)")
    approvals.add_argument("action", nargs="?", default="list",
                           choices=["list", "show", "approve", "deny"])
    approvals.add_argument("--token", default="",
                           help="approval token or unique prefix")
    approvals.add_argument("--state", default="pending",
                           help="filter by state for list")
    approvals.add_argument("--reason", default="",
                           help="reason for deny")
    approvals.add_argument("--json", action="store_true",
                           help="machine-readable output")

    autonomy = sub.add_parser("autonomy", help="bounded autonomy: status, presence control")
    autonomy.add_argument("action", nargs="?", default="status",
                          choices=["status", "start", "stop", "tick",
                                   "health"])
    autonomy.add_argument("--json", action="store_true",
                          help="machine-readable output")
    world.add_argument("--kind", default="morning",
                       help="briefing kind: morning, evening, topic, project, change")
    world.add_argument("--json", action="store_true",
                       help="machine-readable output")
    return parser


def _conductor_oneshot(raw: list[str], home: str = "") -> int:
    """`jarvis "natural language"` — one-shot front door.

    Trailing flags: --speak (voice the answer), --json (machine
    output). Everything else is the request text. Execution uses the
    normal ConductorService path; policy gates apply unchanged.
    """
    speak = "--speak" in raw
    as_json = "--json" in raw
    words: list[str] = []
    skip_next = False
    for token in raw:
        if skip_next:
            skip_next = False
            continue
        if token == "--home":
            skip_next = True
            continue
        if token in ("--speak", "--json"):
            continue
        words.append(token)
    text = " ".join(words)
    if not text.strip():
        print('usage: jarvis "natural language request" [--speak] [--json]')
        return 2
    from .conductor.service import ConductorService
    jarvis = _make_jarvis(home)
    try:
        service = ConductorService(jarvis)
        out = service.handle(text)
        if speak and out.get("response"):
            try:
                from .voice.speak import VoiceSpeaker
                cfg = jarvis.config.voice.__dict__
                VoiceSpeaker(config=cfg).say(
                    out["response"][:2000],
                    workdir=str(jarvis.config.paths.home))
            except Exception as exc:
                out["speak_error"] = f"{type(exc).__name__}"
        if as_json:
            print(json.dumps(out, indent=2, default=str))
        elif out.get("error") and not out.get("response"):
            print(f"error: {out['error']}")
        else:
            print(out.get("response", ""))
        return 0 if out.get("ok") or out.get("response") else 1
    finally:
        jarvis.close()


def _make_jarvis(home: str) -> Jarvis:
    config = JarvisConfig()
    config.apply_env_overrides()
    if home:
        config.paths.home = Path(home)
    return Jarvis(config=config)


def _audio_action(jarvis: Any, args: Any) -> int:
    """Audio perception inspection. One-shot reads; transcribing a file
    never records, and no action transcribes indefinitely."""
    import time as _time
    from .voice.stt import FakeSTT, FasterWhisperSTT, UnavailableSTT
    from .voice.vad import EnergyVADAdapter, FakeVAD
    as_json = args.json

    def _out(payload: Any, text: str) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return 0

    action = args.action
    if action == "status":
        from .cognition.selfmodel import CapabilityModel
        model = CapabilityModel()
        rows = {}
        for name in ("AUDIO_CAPTURE", "AUDIO_VAD", "AUDIO_STT",
                     "MICROPHONE", "PHYSICAL_PI_AUDIO"):
            capability = model.check(name)
            rows[name] = {"state": capability.state.value,
                          "detail": capability.detail}
        lines = [f"{name:18} {info['state']}" for name, info in
                 sorted(rows.items())]
        return _out({"capabilities": rows},
                    "AUDIO\n" + "\n".join(lines))
    if action == "capabilities":
        from .voice.vad import EnergyVADAdapter as _EV
        from .voice.stt import FasterWhisperSTT as _FW
        stt = _FW()
        payload = {"vad": _EV().health(),
                   "stt": stt.health(),
                   "fake_stt": True,
                   "max_frame_s": 10.0,
                   "max_segment_s": 60.0}
        return _out(payload, "\n".join(
            f"{key}={value}" for key, value in payload.items()))
    if action == "sources":
        import shutil
        import subprocess
        cards: list[str] = []
        if shutil.which("arecord") is not None:
            try:
                proc = subprocess.run(
                    ["arecord", "-l"], capture_output=True, text=True,
                    timeout=10)
                cards = [line.strip()[:100] for line in
                         (proc.stdout or "").splitlines()
                         if line.strip().startswith("card ")]
            except (subprocess.TimeoutExpired, OSError):
                cards = []
        return _out({"microphone_cards": cards,
                     "arecord": shutil.which("arecord") is not None},
                    "\n".join(cards) or "no capture hardware listed")
    if action == "test":
        # Bounded self-test: synthesize silence (no mic needed) through
        # VAD + FakeSTT, proving the path without hardware.
        from .voice.audio import AudioBuffer, AudioFrame
        frames = []
        for index in range(5):
            frames.append(AudioFrame(
                source="audio-test", sequence=index, duration_s=0.1,
                payload_bytes=3200))
        vad = FakeVAD(pattern=["silence", "speech", "speech_end"])
        states = [vad.process_frame(frame).state.value for frame in frames]
        fake = FakeSTT(default="")
        result = fake.transcribe("/tmp/audio-test-nonexistent.wav")
        return _out({"frames": len(frames), "vad_states": states,
                     "stt_status": result.status.value,
                     "calls": fake.calls},
                    f"frames={len(frames)} vad={','.join(states)} "
                    f"stt={result.status.value}")
    if action == "replay":
        return _out({"replay": "fixture-only",
                     "detail": "replay uses recorded fixtures; "
                               "microphone never accessed"},
                    "replay: fixtures only (microphone never accessed)")
    if action == "benchmark":
        from .voice.audio import AudioBuffer, AudioFrame
        import time as _t
        buffer = AudioBuffer()
        base = AudioFrame(source="bench", sequence=0, duration_s=0.1,
                          payload_bytes=3200)

        def _validation():
            AudioFrame(source="bench", sequence=1, duration_s=0.1,
                       payload_bytes=3200)

        def _buffer():
            buffer.append(base)

        def _vad():
            FakeVAD().process_frame(base)

        def _event():
            from .intelligence.sensory import event_from_transcript
            event_from_transcript({"transcript": "hi", "confidence": 0.9})

        scenarios = {"validation": _validation, "buffer": _buffer,
                     "vad": _vad, "event": _event}
        results = {}
        for name, scenario in scenarios.items():
            started = _t.perf_counter()
            for _ in range(200):
                scenario()
            results[name] = round(
                (_t.perf_counter() - started) / 200 * 1000, 3)
        lines = [f"{name:12} {ms:.3f}ms" for name, ms in
                 sorted(results.items())]
        return _out({"benchmark_ms": results},
                    "AUDIO BENCHMARKS (ms/op)\n" + "\n".join(lines))
    if action == "transcript":
        if not args.path:
            print("usage: jarvis audio transcript --path FILE.wav")
            jarvis.close()
            return 2
        stt = FasterWhisperSTT() if FasterWhisperSTT().available() \
            else UnavailableSTT()
        result = stt.transcribe(args.path)
        if result.status.value == "success":
            return _out(result.to_dict(),
                        f"{result.transcript}\n(conf={result.confidence})")
        print(f"transcription {result.status.value}: {result.error}")
        jarvis.close()
        return 1
    if action == "diagnostics":
        from .voice.audio import AudioBuffer
        buffer = AudioBuffer()
        payload = {"buffer_capacity": buffer.max_frames,
                   "buffered": len(buffer),
                   "dropped": buffer.dropped,
                   "spool": _audio_spool_depth(jarvis)}
        lines = [f"{key}={value}" for key, value in payload.items()]
        return _out(payload, "AUDIO DIAGNOSTICS\n" + "\n".join(lines))
    print(f"audio: unknown action {action}")
    jarvis.close()
    return 2


def _approval_next_steps(token: str, command_id: str = "") -> str:
    """Actionable operator hint for a parked approval (no secrets dumped).

    Listings show truncated IDs; approve/deny/revoke/show accept the
    unique prefix, so the operator can act from another process with
    only what is printed here.
    """
    prefix = str(token or "")[:12]
    where = f" (command {command_id})" if command_id else ""
    return (f"needs approval {prefix}…{where}\n"
            f"  jarvis device approvals show --approval {prefix}\n"
            f"  jarvis device approvals approve --approval {prefix}\n"
            f"  jarvis device approvals deny --approval {prefix} --reason R\n"
            f"  jarvis device approvals watch   # wait for new requests")


def _world_action(jarvis: Any, args: Any) -> int:
    """World intelligence: evidence-driven live knowledge. Read paths
    never actuate; research is bounded and budgeted."""
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "status")

    def _out(payload: Any, text: str) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return 0

    from .worldintel.cache import EvidenceCache
    from .worldintel.sources import SourceRegistry
    home = str(jarvis.config.paths.home)
    cfg = jarvis.config.world
    registry = SourceRegistry()
    cache = EvidenceCache(home, max_entries=cfg.cache_entries)

    if action == "status":
        from .worldintel.health import check as world_check
        report = world_check(cfg.__dict__, registry, cache)
        lines = [f"state={report['state']}",
                 f"sources={len(report['sources'])}",
                 f"cache={report['cache'].get('entries', 0)} entries",
                 f"project={cfg.default_project or '(none)'}",
                 f"topics={', '.join(cfg.topics) or '(none)'}"]
        return _out({"health": report,
                     "project": cfg.default_project,
                     "topics": list(cfg.topics)},
                    "WORLD\n" + "\n".join(lines))
    if action == "sources":
        payload = registry.to_dict()
        lines = [f"{s['source_id']:12} {s['kind']:8} "
                 f"{s['freshness_domain']:16} "
                 f"{'on' if s['enabled'] else 'off'}  "
                 f"{s['trust_basis']}" for s in payload["sources"]]
        return _out(payload, "SOURCES\n" + "\n".join(lines))
    if action == "topics":
        from .worldintel.subscriptions import TopicStore
        store = TopicStore(home)
        name = (getattr(args, "topic", "") or "").strip()
        if name.startswith("-"):
            name = name[1:].strip()
            ok = store.remove(name)
            return _out({"removed": ok, "topic": name},
                        f"unsubscribed: {name}" if ok
                        else f"unknown topic: {name}")
        if name:
            ok = store.add(name)
            return _out({"added": ok, "topic": name},
                        f"subscribed: {name}" if ok
                        else f"not added: {name}")
        found = store.list()
        return _out({"topics": found},
                    "TOPICS\n" + "\n".join(
                        t["topic"] for t in found) or "no topics")
    if action == "health":
        from .worldintel.health import check as world_check
        report = world_check(cfg.__dict__, registry, cache)
        return _out(report, "WORLD HEALTH\n" +
                    json.dumps(report, indent=2, default=str))
    if action == "diagnostics":
        from .worldintel.telemetry import TELEMETRY
        payload = {"telemetry": TELEMETRY.summary(),
                   "recent": TELEMETRY.recent(10),
                   "cache": cache.stats()}
        return _out(payload, "WORLD DIAGNOSTICS\n" +
                    json.dumps(payload, indent=2, default=str))
    if action in ("search", "research"):
        import time as _time
        from .worldintel.research import Researcher
        from .worldintel.telemetry import TELEMETRY
        from .worldintel.worldsync import sync_answer
        query = getattr(args, "text", "") or (
            "What is happening in AI today?" if action == "search"
            else "Research recent AI developments")
        started = _time.monotonic()
        researcher = Researcher(
            registry, cache, max_searches=cfg.max_searches,
            max_evidence=cfg.max_evidence, budget_s=cfg.budget_s)
        answer = researcher.research(
            query, active_project=cfg.default_project,
            topics=list(cfg.topics))
        synced = sync_answer(answer, registry=jarvis.world_registry,
                             graph=jarvis.graph)
        try:
            jarvis.world_registry.save(jarvis.world_store)
        except Exception:
            pass
        try:
            _world_snapshot_append(home, answer)
        except Exception:
            pass
        TELEMETRY.record(
            "world.research", status="ok",
            latency_ms=round(
                (_time.monotonic() - started) * 1000, 1),
            provider=",".join(
                sorted({p.get("source_id", "") for p in
                        answer.provenance}))[:64],
            count=len(answer.provenance), query_len=len(query),
            detail=answer.scope)
        payload = answer.to_dict()
        payload["synced"] = synced
        lines = [f"scope={answer.scope}",
                 answer.summary,
                 f"conflicts={len(answer.conflicts)}",
                 (f"uncertainty: {'; '.join(answer.uncertainty)}"
                  if answer.uncertainty else "uncertainty: none listed"),
                 f"synced={synced}"]
        return _out(payload, "\n".join(lines))
    if action == "events":
        items = _world_recent_evidence(home, limit=10)
        if not items:
            return _out({"events": []},
                        "no cached evidence yet — run: "
                        "jarvis world research --text \"...\"")
        lines = [f"{e.get('retrieved_at', 0):.0f} "
                 f"{e.get('source_id', '?'):14} "
                 f"{e.get('freshness', '?'):8} "
                 f"{str(e.get('title', '')).replace(chr(10), ' ')[:70]}"
                 for e in items]
        return _out({"events": items},
                    "RECENT EVIDENCE (cached, labeled)\n"
                    + "\n".join(lines))
    if action == "changes":
        snaps = _world_snapshots(home)
        if len(snaps) < 2:
            return _out({"changes": []},
                        "need 2+ research runs to diff — run: "
                        "jarvis world research --text \"...\" twice")
        from .worldintel.changes import diff_snapshots
        old = snaps[-2].get("claims", {}) if isinstance(
            snaps[-2], dict) else snaps[-2]
        new = snaps[-1].get("claims", {}) if isinstance(
            snaps[-1], dict) else snaps[-1]
        changes = diff_snapshots(old, new)
        lines = [f"{c['status']:10} {c['key'][:80]}" for c in changes]
        return _out({"changes": changes},
                    "CHANGES\n" + ("\n".join(lines) or "no changes"))
    if action == "refresh":
        from .geospatial.live import LiveIntelligenceService
        from .worldintel.refresh import refresh_all
        from .worldintel.subscriptions import TopicStore
        try:
            service = LiveIntelligenceService(home=home)
            # Explicit operator consent: refresh means network egress.
            result = service.sync(allow_remote=True)
            live = {"ingested": result.get("ingested", 0),
                    "alerts": result.get("alerts", 0)}
        except Exception as exc:
            live = {"error": f"{type(exc).__name__}"}
        store = TopicStore(home)
        topics = sorted(set(store.names()) | set(cfg.topics))
        notifier = None
        if getattr(args, "notify", False):
            def notifier(event: Any) -> Any:
                try:
                    return jarvis.proactive.notify(event)
                except Exception:
                    return None
        try:
            summary = refresh_all(
                home, topics=topics,
                interval_s=cfg.refresh_interval_s,
                notifier=notifier, world_registry=jarvis.world_registry,
                graph=jarvis.graph)
            try:
                jarvis.world_registry.save(jarvis.world_store)
            except Exception:
                pass
        except Exception as exc:
            summary = {"error": f"{type(exc).__name__}"}
        payload = {"live": live, "topics": summary}
        lines = [f"live: ingested={live.get('ingested', 0)} "
                 f"alerts={live.get('alerts', 0)}",
                 f"topics: refreshed={summary.get('refreshed', 0)} "
                 f"skipped={summary.get('skipped', 0)} "
                 f"notified={summary.get('notified', 0)}"]
        return _out(payload, "REFRESHED\n" + "\n".join(lines))
    if action == "briefing":
        from .worldintel.briefing import build_briefing
        snaps = _world_snapshots(home)
        answers = []
        for s in snaps[-3:]:
            claims = s.get("claims", {}) if isinstance(
                s, dict) else s
            answers.append({"claims": [
                {"subject": k.split("|")[0],
                 "predicate": k.split("|")[1] if "|" in k else "",
                 "object": v.get("object", ""),
                 "corroboration": {}} for k, v in claims.items()],
                "evidence": s.get("evidence", []) if isinstance(
                    s, dict) else []})
        kind = getattr(args, "kind", "morning")
        query = getattr(args, "text", "")
        if query:
            from .worldintel.research import Researcher
            researcher = Researcher(
                registry, cache, max_searches=cfg.max_searches,
                max_evidence=cfg.max_evidence, budget_s=cfg.budget_s)
            live = researcher.research(
                query, active_project=cfg.default_project,
                topics=list(cfg.topics))
            answers.append(live)
        briefing = build_briefing(
            kind, answers,
            title=f"{kind.title()} briefing")
        return _out(briefing, briefing["title"].upper() + "\n" +
                    "\n".join(f"- {line}"
                              for line in briefing["lines"]) +
                    (f"\nconflicts={briefing['conflicts']}" if
                     briefing["conflicts"] else "") +
                    (f"\nuncertain: {'; '.join(briefing['uncertainty'])}"
                     if briefing["uncertainty"] else ""))
    print(f"world: unknown action {action}")
    jarvis.close()
    return 2


def _world_snapshot_path(home: str) -> Any:
    from pathlib import Path as _Path
    return _Path(home) / "worldintel-snapshots.jsonl"


def _world_snapshot_append(home: str, answer: Any) -> None:
    import json as _json
    import time as _time
    path = _world_snapshot_path(home)
    claims = {f"{c['subject']}|{c['predicate']}": {
        "object": c["object"], "confidence": c["confidence"],
        "conflicting": False} for c in (answer.claims or [])}
    evidence = [{"title": p.get("title", "")[:120],
                 "source_id": p.get("source_id", "?"),
                 "url": p.get("url", "")[:200]}
                for p in (answer.provenance or [])[:10]]
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(_json.dumps(
            {"at": _time.time(), "claims": claims,
             "evidence": evidence},
            sort_keys=True, default=str) + "\n")
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > 10:
        path.write_text("\n".join(lines[-10:]) + "\n",
                        encoding="utf-8")


def _world_snapshots(home: str) -> list[Any]:
    import json as _json
    path = _world_snapshot_path(home)
    if not path.exists():
        return []
    out = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines()[-10:]:
            try:
                loaded = _json.loads(raw)
                out.append({"claims": loaded.get("claims", {}),
                            "evidence": loaded.get("evidence", []),
                            "at": loaded.get("at", 0.0)})
            except ValueError:
                continue
    except OSError:
        pass
    return out


def _world_recent_evidence(home: str, limit: int = 10) -> list[Any]:
    from .worldintel.cache import EvidenceCache
    from .worldintel.freshness import assess
    cache = EvidenceCache(home)
    items = []
    for key, item in list(cache._items.items())[-limit:]:
        payload = item.get("payload", {})
        for entry in payload.get("items", [])[:3]:
            items.append({
                "source_id": item.get("source_id", "?"),
                "title": entry.get("title", ""),
                "retrieved_at": item.get("retrieved_at", 0.0),
                "freshness": assess(
                    entry.get("published_at", 0.0),
                    item.get("retrieved_at", 0.0),
                    domain=item.get(
                        "freshness_domain", "general"))["state"]})
    return items[-limit:]


def _integration_action(jarvis: Any, args: Any) -> int:
    """Experience diagnostics: subsystem checks + unified cycle trace."""
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "doctor")

    def _out(payload: Any, text: str) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return 0

    if action == "trace":
        from .cognition.trace import trace_cycle
        corr = getattr(args, "cycle", "")
        if not corr:
            print("usage: jarvis integration trace --cycle <correlation-id> "
                  "[--session <id>] [--json]")
            jarvis.close()
            return 2
        home = str(jarvis.config.paths.home)
        result = trace_cycle(home, corr,
                             session_id=getattr(args, "session", ""))
        lines = [f"correlation={result['correlation_id']}",
                 f"events={len(result['events'])}",
                 f"conversation={len(result['conversation'])}",
                 f"episodes={len(result['episodes'])}"]
        for event in result["events"][:10]:
            lines.append(f"  [{event['type']}]")
        for turn in result["conversation"][:6]:
            lines.append(f"  > {turn['content'][:100]}")
        if result["gaps"]:
            lines.append("gaps: " + "; ".join(result["gaps"]))
        return _out(result, "TRACE\n" + "\n".join(lines))
    # doctor: one line per integration boundary.
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Context", True, "bounded assembly w/ gaps"))
    try:
        from .cognition.context import ContextEngine
        engine = ContextEngine(world=jarvis.world_registry,
                               palace=jarvis.palace)
        context = engine.assemble("doctor probe")
        checks.append(("Memory", True,
                       f"{len(context.facts)} facts assembled"))
    except Exception as exc:
        checks.append(("Memory", False, f"{type(exc).__name__}"))
    try:
        from .worldintel.health import check as world_check
        from .worldintel.sources import SourceRegistry
        report = world_check(jarvis.config.world.__dict__,
                             SourceRegistry(), None)
        checks.append(("World", report["state"] in ("HEALTHY",
                                                     "DEGRADED"),
                       str(report.get("detail", ""))))
    except Exception as exc:
        checks.append(("World", False, f"{type(exc).__name__}"))
    for name in ("Reasoning", "Planning", "Policy", "Tools",
                 "Verification", "Reflection"):
        checks.append((name, True, "wired in cycle"))
    try:
        from .events.store import EventStore
        home = str(jarvis.config.paths.home)
        from .core.config import PathsConfig
        path = str(Path(home) / PathsConfig().events)
        store = EventStore(path)
        try:
            checks.append(("Trace", True,
                           f"{store.count()} events persisted"))
        finally:
            store.close()
    except Exception as exc:
        checks.append(("Trace", False, f"{type(exc).__name__}"))
    lines = [f"{name:14} {'OK' if ok else 'FAIL'}  {detail}"
             for name, ok, detail in checks]
    return _out({"checks": [{"name": n, "ok": o, "detail": d}
                            for n, o, d in checks]},
                "INTEGRATION\n" + "\n".join(lines))


def _grants_store(home: str) -> Any:
    from .policy.standing import StandingGrantStore
    return StandingGrantStore(home)


def _grants_action(jarvis: Any, args: Any) -> int:
    """Standing grants: explicit bounded durable authorizations."""
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "list")

    def _out(payload: Any, text: str, code: int = 0) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return code

    home = str(jarvis.config.paths.home)
    store = _grants_store(home)
    if action == "list":
        grants = [g.to_dict() for g in store.list()]
        lines = [f"{g['grant_id'][:16]:18} {g['capability']:20} "
                 f"{g['scope_kind']}:{g['scope'][:40]:44} "
                 f"{g['risk_class']:10} "
                 f"{'live' if g['live'] else g['status']}"
                 for g in grants]
        return _out({"grants": grants},
                    "GRANTS\n" + "\n".join(lines) or "no grants")
    if action == "show":
        grant = store.get(getattr(args, "id", ""))
        if grant is None:
            return _out({"error": "unknown grant"}, "unknown grant", 1)
        info = grant.to_dict()
        return _out(info, "\n".join(
            f"{key}={info.get(key, '')}" for key in
            ("grant_id", "capability", "scope_kind", "scope",
             "allowed_operations", "denied_operations", "risk_class",
             "status", "expires_at", "created_by")))
    if action == "revoke":
        ok = store.revoke(getattr(args, "id", ""), by="cli")
        return _out({"revoked": ok}, "revoked" if ok else
                    "unknown or dead grant", 0 if ok else 1)
    if action == "create":
        capability = getattr(args, "capability", "").strip()
        scope = getattr(args, "scope", "").strip()
        allow = [o.strip() for o in getattr(args, "allow", "").split(",")
                 if o.strip()]
        if not capability or not scope or not allow:
            return _out(
                {"error": "need --capability, --scope, --allow"},
                "usage: jarvis grants create --capability media.organize "
                "--scope ~/Downloads --allow move,list [--deny delete] "
                "[--risk low] [--days 30]", 2)
        try:
            from .policy.standing import GrantError
            grant = store.create(
                capability, getattr(args, "scope_kind", "path"), scope,
                allowed_operations=allow,
                denied_operations=[
                    o.strip() for o in getattr(args, "deny", "").split(
                        ",") if o.strip()],
                risk_class=getattr(args, "risk", "low"),
                by="cli",
                expires_in_s=(float(getattr(args, "days", 0.0) or 0.0)
                              * 86400.0 if float(
                                  getattr(args, "days", 0.0) or 0.0) > 0
                              else float(jarvis.config.autonomy.
                                         default_grant_days) * 86400.0),
                provenance={"origin": "cli"})
        except GrantError as exc:
            return _out({"error": str(exc)}, f"rejected: {exc}", 1)
        return _out({"grant_id": grant.grant_id},
                    f"granted {grant.grant_id} "
                    f"(expires in "
                    f"{round((grant.expires_at - __import__('time').time()) / 86400.0, 1)}d)")
    jarvis.close()
    return 2


def _autonomy_action(jarvis: Any, args: Any) -> int:
    """Bounded autonomy controls: status, presence start/stop/tick."""
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "status")

    def _out(payload: Any, text: str, code: int = 0) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return code

    from .autonomy.presence import PresenceRuntime
    home = str(jarvis.config.paths.home)
    runtime = PresenceRuntime(
        home,
        interval_s=float(jarvis.config.autonomy.presence_interval_s))
    if action == "status":
        from .policy.standing import StandingGrantStore
        grants = len(StandingGrantStore(home).list())
        payload = {"autonomy_enabled": bool(
            jarvis.config.autonomy.enabled),
            "live_grants": grants, "presence": runtime.health()}
        lines = [f"autonomy={'on' if payload['autonomy_enabled'] else 'off'}",
                 f"grants={grants}",
                 f"presence={'claimed pid ' + str(payload['presence']['pid']) if payload['presence']['claimed'] else 'idle'} "
                 f"ticks={payload['presence']['ticks']}"]
        return _out(payload, "AUTONOMY\n" + "\n".join(lines))
    if action == "health":
        return _out(runtime.health(), json.dumps(runtime.health(),
                                                 indent=2, default=str))
    if action == "start":
        result = runtime.start()
        return _out(result, json.dumps(result) if result.get("ok")
                    else f"start failed: {result.get('error')}",
                    0 if result.get("ok") else 1)
    if action == "stop":
        return _out(runtime.stop(), "presence stopped")
    if action == "tick":
        report = runtime.tick(jarvis)
        lines = [f"actions={len(report.get('actions', []))}",
                 f"notifications={report.get('notifications', 0)}",
                 f"errors={len(report.get('errors', []))}"]
        return _out(report, "TICK\n" + "\n".join(lines))
    jarvis.close()
    return 2


def _resolve_policy_token(policy: Any, token: str) -> str | None:
    """Unique-prefix resolution (min 4 chars). Full tokens never dumped."""
    token = str(token or "")
    if len(token) < 4:
        return None
    policy._load_approvals() if hasattr(policy, "_load_approvals") else None
    matches = [t for t in policy.approvals if t.startswith(token)]
    return matches[0] if len(matches) == 1 else None


def _approvals_action(jarvis: Any, args: Any) -> int:
    """Policy approval tokens: list pending (truncated), show, approve, deny."""
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "list")

    def _out(payload: Any, text: str, code: int = 0) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return code

    policy = jarvis.policy
    if action == "list":
        found = policy.list_approvals(
            getattr(args, "state", "") or None)
        lines = [f"{a['approval_id']:16} {a['actor']:12} "
                 f"{a['action'][:40]:42} {a['status']}"
                 for a in found]
        return _out({"approvals": found},
                    "APPROVALS\n" + "\n".join(lines) or "no approvals")
    full = _resolve_policy_token(policy, getattr(args, "token", ""))
    if full is None:
        return _out({"error": "unknown or ambiguous token"},
                    "unknown or ambiguous token (need 4+ unique chars)", 1)
    if action == "show":
        entry = policy.approvals.get(full, {})
        info = {"approval_id": full[:12] + "…",
                "actor": entry.get("actor", ""),
                "action": str(entry.get("action", ""))[:120],
                "status": entry.get("status", "")}
        return _out(info, "\n".join(f"{k}={v}" for k, v in info.items()))
    if action == "approve":
        ok = policy.approve(full, by="cli")
        return _out({"approved": ok}, "approved" if ok else
                    "cannot approve", 0 if ok else 1)
    if action == "deny":
        ok = policy.deny(full, by="cli")
        return _out({"denied": ok}, "denied" if ok else
                    "cannot deny", 0 if ok else 1)
    jarvis.close()
    return 2


def _backup_paths(jarvis: Any) -> tuple[Any, Any, Any]:
    from pathlib import Path as _Path
    home = _Path(jarvis.config.paths.home)
    voices = _Path.home() / ".config" / "jarvis" / "voices"
    dest = _Path.home() / "jarvis-backups"
    return home, voices, dest


def _backup_action(jarvis: Any, args: Any) -> int:
    """State backup lifecycle. Code is on GitHub; this protects state."""
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "create")

    def _out(payload: Any, text: str, code: int = 0) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return code

    from pathlib import Path as _Path
    from . import backup as _backup
    home, voices, default_dest = _backup_paths(jarvis)
    dest = _Path(getattr(args, "dest", "") or default_dest)
    if action == "create":
        manifest = _backup.create(
            home, voices, dest,
            keep=max(1, int(getattr(args, "keep", 10) or 10)))
        check = _backup.verify(_Path(manifest["archive"]))
        payload = {"manifest": manifest,
                   "verified": check["ok"]}
        lines = [f"archive={manifest['archive']}",
                 f"files={manifest['file_count']} "
                 f"bytes={manifest['total_bytes']} "
                 f"archive_bytes={manifest['archive_bytes']}",
                 f"verified={'yes' if check['ok'] else 'NO — DO NOT TRUST'}"]
        return _out(payload, "BACKUP\n" + "\n".join(lines),
                    0 if check["ok"] else 1)
    if action == "list":
        found = _backup.list_backups(dest)
        lines = [f"{_Path(f['archive']).name:32} "
                 f"{f['bytes'] // 1024:>8}KB "
                 f"{'verified' if f['verified'] else 'UNVERIFIED'}"
                 for f in found]
        return _out({"backups": found},
                    "BACKUPS\n" + "\n".join(lines) or "no backups")
    if action == "verify":
        target = getattr(args, "file", "")
        if not target:
            return _out({"error": "need --file"}, "need --file", 2)
        check = _backup.verify(_Path(target))
        return _out(check, "verified" if check["ok"] else
                    f"BROKEN: {check.get('error', check.get('mismatches'))}",
                    0 if check["ok"] else 1)
    if action == "restore":
        target = getattr(args, "file", "")
        if not target:
            return _out({"error": "need --file"}, "need --file", 2)
        if not getattr(args, "force", False):
            return _out({"error": "restore requires --force"},
                        "restore overwrites live state: re-run with --force",
                        2)
        result = _backup.restore(_Path(target), home, voices, force=True)
        return _out(result,
                    f"restored {result.get('count', 0)} files"
                    if result.get("ok")
                    else f"refused: {result.get('error')}",
                    0 if result.get("ok") else 1)
    jarvis.close()
    return 2


def _service_action(jarvis: Any, args: Any) -> int:
    """24/7 background service controls. Foreground `run` is what
    systemd (or `start`) supervises; everything else inspects."""
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "status")

    def _out(payload: Any, text: str, code: int = 0) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return code

    from .service.runtime import (BackgroundService, ServiceLock,
                                  evaluate_state, read_pid_info)
    home = str(jarvis.config.paths.home)
    cfg = jarvis.config.service

    def _service() -> BackgroundService:
        return BackgroundService(
            home, interval_s=cfg.interval_s,
            heartbeat_every_s=cfg.heartbeat_every_s,
            health_every_s=cfg.health_every_s,
            max_queue=cfg.max_queue)

    if action == "status":
        info = read_pid_info(home)
        heart = _service().read_heartbeat()
        payload = {"service": info, "heartbeat": heart}
        lines = []
        if info.get("running"):
            lines.append(f"running pid={info['pid']}")
        else:
            lines.append(f"stopped ({info.get('reason', '')})")
        if heart.get("present") and not heart.get("corrupt"):
            lines.append(f"heartbeat age={heart.get('age_s', '?')}s "
                         f"state={heart.get('state', '?')}")
        return _out(payload, "SERVICE\n" + "\n".join(lines))
    if action == "health":
        return _out(_service_health(jarvis),
                    "SERVICE HEALTH\n" + json.dumps(
                        _service_health(jarvis), indent=2, default=str))
    if action == "doctor":
        checks = _service_doctor(jarvis)
        failed = [c for c in checks
                  if c.get("status") not in ("OK", "PASS")]
        return _out({"checks": checks},
                    "SERVICE DOCTOR\n" + "\n".join(
                        f"{c['name']:24} {c['status']:4} {c['detail']}"
                        for c in checks),
                    0 if not failed else 1)
    if action == "logs":
        lines = _service_logs(home, cfg,
                              max(1, int(getattr(args, "lines", 30))))
        return _out({"lines": lines}, "\n".join(lines) or "(no logs)")
    if action in ("start", "restart"):
        if action == "restart":
            _service_stop(home)
        return _service_start(home, cfg)
    if action == "stop":
        return _service_stop(home)
    if action == "run":
        return _service_run(jarvis)
    jarvis.close()
    return 2


def _service_log_path(home: str, cfg: Any) -> Any:
    from pathlib import Path as _Path
    return _Path(home) / "logs" / "background-service.log"


def _service_rotate(home: str, cfg: Any) -> None:
    from pathlib import Path as _Path
    path = _service_log_path(home, cfg)
    try:
        if path.exists() and path.stat().st_size > int(
                cfg.max_log_bytes):
            for i in range(int(cfg.max_log_files) - 1, 0, -1):
                older = path.with_name(f"{path.name}.{i}")
                newer = path.with_name(f"{path.name}.{i + 1}")
                if older.exists():
                    if i + 1 >= int(cfg.max_log_files):
                        older.unlink()
                    else:
                        older.replace(newer)
            path.replace(path.with_name(f"{path.name}.1"))
    except OSError:
        pass


def _service_start(home: str, cfg: Any) -> int:
    import subprocess as _subprocess
    import sys as _sys
    from pathlib import Path as _Path
    from .service.runtime import read_pid_info
    info = read_pid_info(home)
    if info.get("running"):
        print(f"not started: already running (pid {info['pid']})")
        return 1
    _service_rotate(home, cfg)
    project = str(_Path(__file__).resolve().parent.parent)
    log = _service_log_path(home, cfg)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    cmd = [_sys.executable, "-m", "jarvis.cli", "service", "run"]
    if home and home != str(_Path.home() / ".jarvis-os"):
        cmd = [_sys.executable, "-m", "jarvis.cli", "--home", home,
               "service", "run"]
    env = dict(os.environ)
    env["PYTHONPATH"] = project + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        with open(log, "ab") as handle:
            _subprocess.Popen(cmd, cwd=project, env=env,
                              stdout=handle, stderr=subprocess.STDOUT,
                              start_new_session=True, close_fds=True)
    except (OSError, ValueError) as exc:
        print(f"start failed: {type(exc).__name__}: {exc}")
        return 1
    print("background service starting (see: jarvis service status)")
    return 0


def _service_stop(home: str) -> int:
    import os as _os
    import signal as _signal
    import time as _time
    from .service.runtime import read_pid_info
    info = read_pid_info(home)
    if not info.get("running"):
        print(f"not running ({info.get('reason', '')})")
        return 0
    try:
        _os.kill(int(info["pid"]), _signal.SIGTERM)
    except (OSError, ValueError, TypeError):
        pass
    deadline = _time.monotonic() + 25.0
    while _time.monotonic() < deadline:
        if not read_pid_info(home).get("running"):
            print("background service stopped")
            return 0
        _time.sleep(0.5)
    print("stop timed out: process still alive")
    return 1


def _service_logs(home: str, cfg: Any, lines: int) -> list[str]:
    path = _service_log_path(home, cfg)
    try:
        if not path.exists():
            return []
        return path.read_text(
            encoding="utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def _service_health(jarvis: Any) -> dict[str, Any]:
    import time as _time
    from .service.runtime import (BackgroundService, evaluate_state,
                                  read_pid_info)
    home = str(jarvis.config.paths.home)
    cfg = jarvis.config.service
    info = read_pid_info(home)
    svc = BackgroundService(home)
    heart = svc.read_heartbeat()
    emergency = False
    try:
        check = getattr(jarvis.policy, "_emergency_stop", None)
        emergency = bool(check()) if callable(check) else False
    except Exception:
        emergency = False
    degraded: list[str] = []
    try:
        import shutil as _shutil
        _, _, free = _shutil.disk_usage(home)
        if free < 512 * 1024 * 1024:
            degraded.append("disk low")
    except OSError:
        degraded.append("disk unreadable")
    try:
        jarvis.events.count()
    except Exception as exc:
        degraded.append(f"persistence: {type(exc).__name__}")
    if not info.get("running", False) and not heart.get("present", False):
        return {"state": "STOPPED", "uptime_seconds": 0.0,
                "heartbeat_age_s": None,
                "pid": info.get("pid"), "queue_depth": 0,
                "restart_count": 0, "degraded": degraded,
                "emergency_stop": emergency}
    failed = not info.get("running", False)
    state = evaluate_state(
        emergency=emergency, failed=failed,
        heartbeat_stale=bool(heart.get("stale", True)),
        degraded_reasons=degraded,
        recovering=False)
    return {"state": state,
            "uptime_seconds": round(_time.time() - float(
                heart.get("started_at", _time.time())), 1)
            if heart.get("present") else 0.0,
            "heartbeat_age_s": heart.get("age_s"),
            "pid": info.get("pid"),
            "queue_depth": 0,
            "restart_count": int(heart.get("restart_count", 0) or 0),
            "degraded": degraded,
            "emergency_stop": emergency}


def _service_doctor(jarvis: Any) -> list[dict[str, str]]:
    from .service.runtime import read_pid_info
    home = str(jarvis.config.paths.home)
    checks: list[dict[str, str]] = []

    def _add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"name": name,
                       "status": "PASS" if ok else "FAIL",
                       "detail": detail})

    import shutil as _shutil
    unit = _shutil.which("systemctl") is not None
    _add("systemd present", unit, "systemctl found" if unit else
         "no systemctl: unit file advisory only")
    info = read_pid_info(home)
    _add("single instance", True,
         f"pid={info.get('pid')}" if info.get("running")
         else info.get("reason", "stopped"))
    svc_health = _service_health(jarvis)
    _add("service state",
         svc_health["state"] != "FAILED",
         svc_health["state"] + (" (engaged: read-only mode)" 
                                if svc_health["state"] == "EMERGENCY_STOP"
                                else ""))
    try:
        jarvis.config.validate()
        _add("configuration", True, "service.* bounds valid")
    except ValueError as exc:
        _add("configuration", False, str(exc)[:160])
    try:
        n = jarvis.events.count()
        _add("eventstore", True, f"{n} events readable")
    except Exception as exc:
        _add("eventstore", False, f"{type(exc).__name__}")
    try:
        stopped = getattr(jarvis.policy, "_emergency_stop", lambda: False)()
        _add("emergency stop", True,
             "ENGAGED" if stopped else "clear")
    except Exception as exc:
        _add("emergency stop", False, f"{type(exc).__name__}")
    _add("Presence", True, "tick runtime available")
    return checks


def _service_run(jarvis: Any) -> int:
    """Foreground loop for systemd/`start`. Never returns until stop."""
    import time as _time
    from .autonomy.presence import PresenceRuntime
    from .service.runtime import (BackgroundService, Trigger,
                                  evaluate_state)
    home = str(jarvis.config.paths.home)
    cfg = jarvis.config.service
    svc = BackgroundService(
        home, interval_s=cfg.interval_s,
        heartbeat_every_s=cfg.heartbeat_every_s,
        health_every_s=cfg.health_every_s,
        max_queue=cfg.max_queue)
    started = svc.start()
    if not started.get("ok"):
        print(f"service refused: {started.get('error')}")
        jarvis.close()
        return 1
    presence = PresenceRuntime(home, interval_s=cfg.interval_s)
    from .durable import DurableRunner, TaskStore, mesh_executor
    from .service.runtime import PRIORITY_NORMAL as _PRIO_NORMAL
    durable = DurableRunner(TaskStore(home),
                            executor=mesh_executor(jarvis),
                            policy=getattr(jarvis, "policy", None),
                            events=getattr(jarvis, "events", None))
    try:
        recovered = durable.recover_all(
            policy=getattr(jarvis, "policy", None))
    except Exception:
        recovered = []
    if recovered:
        print(f"durable tasks recovered at startup: {len(recovered)}")
    svc.schedule(Trigger(
        trigger_id="durable-tasks-init", source="service",
        kind="durable_tasks", priority=_PRIO_NORMAL,
        run_at=_time.monotonic(), dedupe_key="durable-tasks:init",
        correlation_id=f"svc-{int(_time.time())}"))

    def _handle(trigger: Trigger) -> dict[str, Any]:
        try:
            if trigger.kind == "presence_tick":
                report = presence.tick(jarvis)
                return {"ok": not report.get("errors"),
                        "detail": report}
            if trigger.kind == "world_refresh":
                from .worldintel.refresh import refresh_all
                summary = refresh_all(
                    home, interval_s=float(
                        jarvis.config.world.refresh_interval_s))
                return {"ok": True, "detail": summary}
            if trigger.kind == "health_check":
                health = _service_health(jarvis)
                state = health.get("state", "?")
                if state in ("FAILED",):
                    svc.degraded_reasons.append("health FAILED")
                return {"ok": state != "FAILED", "detail": health}
            if trigger.kind == "maintenance":
                pruned = _service_maintenance(home, cfg)
                return {"ok": True, "detail": pruned}
            if trigger.kind == "durable_tasks":
                summary = _durable_sweep(jarvis, durable)
                try:
                    svc.schedule(Trigger(
                        trigger_id="durable-tasks-next",
                        source="service", kind="durable_tasks",
                        priority=_PRIO_NORMAL,
                        run_at=_time.monotonic() + max(
                            60.0, float(cfg.interval_s)),
                        dedupe_key="durable-tasks:next",
                        correlation_id=trigger.correlation_id))
                except Exception:
                    pass
                return {"ok": True, "detail": summary}
        except Exception as exc:
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}
        return {"ok": False, "error": "unknown trigger kind"}

    try:
        result = svc.serve_forever(_handle)
    finally:
        try:
            jarvis.close()
        except Exception:
            pass
    print(f"service exited: {result}")
    return 0 if result.get("ok") else 1


def _durable_sweep(jarvis: Any, durable: Any,
                   max_advances: int = 3) -> dict[str, Any]:
    """One bounded durable-task pass: recover strays, then advance a
    few ready tasks by one step each. Never raises; a sweep never
    blocks the service loop."""
    from .durable.task import TaskState
    summary: dict[str, Any] = {"recovered": 0, "advanced": [],
                               "errors": []}
    try:
        recovered = durable.recover_all(
            policy=getattr(jarvis, "policy", None))
        summary["recovered"] = len(recovered)
    except Exception as exc:
        summary["errors"].append(f"recover: {type(exc).__name__}")
        return summary
    advanced = 0
    try:
        for task in durable.store.list():
            if advanced >= max_advances:
                break
            if task.state not in (TaskState.READY, TaskState.RETRYING,
                                  TaskState.CHECKPOINTED):
                continue
            try:
                durable.advance(task.task_id)
                summary["advanced"].append(
                    f"{task.task_id}:{durable.store.get(task.task_id).state.value}")
                advanced += 1
            except Exception as exc:
                summary["errors"].append(
                    f"{task.task_id}: {type(exc).__name__}"[:160])
    except Exception as exc:
        summary["errors"].append(f"sweep: {type(exc).__name__}")
    return summary


def _service_maintenance(home: str, cfg: Any) -> dict[str, Any]:
    """Bounded janitor: prune heartbeat tmp files, cap trace growth."""
    removed = 0
    try:
        from pathlib import Path as _Path
        for pattern in ("service-heartbeat.json.tmp",
                        ".device-approvals-*", ".policy-grants-*"):
            for path in _Path(home).glob(pattern):
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
    except OSError:
        pass
    return {"removed_temp_files": removed}


def _audio_spool_depth(jarvis: Any) -> dict[str, Any]:
    try:
        from .voice.spool import TranscriptSpool
        home = str(jarvis.config.paths.home)
        return TranscriptSpool(home).depth()
    except Exception:
        return {"pending": 0, "bytes": 0}


def _voice_action(jarvis: Any, args: Any) -> int:
    """JARVIS voice: Chatterbox identity, setup, test, benchmark.

    `say` synthesizes response text through the configured provider
    (chatterbox → local fallback → text-only). `test` is deterministic
    (FakeTTS, no mic/GPU/net). `setup` installs the reference voice
    explicitly. `benchmark` separates fake vs real measurements.
    """
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "status")

    def _out(payload: Any, text: str) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print(text)
        jarvis.close()
        return 0

    cfg = jarvis.config.voice
    if action == "profile":
        from .voice.voice_profile import (STYLE_GUIDANCE,
                                          effective_style,
                                          load_overrides,
                                          save_overrides)
        home = str(jarvis.config.paths.home)
        updates = {}
        style = str(getattr(args, "style", "") or "")
        emotion = str(getattr(args, "emotion", "") or "")[:40]
        if style:
            if style not in STYLE_GUIDANCE:
                print(f"unknown style (normal|warning|error|"
                      f"confirmation|uncertain)")
                jarvis.close()
                return 2
            updates["style"] = style
        if emotion:
            updates["emotion"] = emotion
        try:
            saved = save_overrides(home, updates) if updates else \
                load_overrides(home)
        except ValueError as exc:
            print(f"profile refused: {exc}")
            jarvis.close()
            return 2
        payload = {"saved": saved,
                   "effective_style": effective_style(home)}
        lines = ["VOICE PROFILE",
                 f"saved: {saved or '(defaults)'}",
                 f"effective style: {payload['effective_style']}"]
        return _out(payload, "\n".join(lines))
    if action == "status":
        from .voice.output import output_for
        from .voice.setup import verify_reference
        from .voice.tts import provider_for
        provider = provider_for(cfg.tts_provider, cfg.__dict__)
        ref = verify_reference(cfg.reference_audio)
        out = output_for(cfg.playback_backend)
        tts_health = provider.health()
        tts_mode = tts_health.get("mode", "")
        tts_state = ("OK" if provider.available() else "NOT AVAILABLE") + \
            (f" ({tts_mode})" if tts_mode else "")
        payload = {"enabled": cfg.enabled,
                   "provider": cfg.tts_provider,
                   "profile": cfg.profile,
                   "reference": {"path": cfg.reference_audio,
                                 **ref},
                   "tts": provider.health(),
                   "output": {"backend": getattr(out, "backend",
                                                 out.name),
                              "available": out.available()},
                   "language": cfg.language, "style": cfg.style,
                   "retain_audio": cfg.retain_audio,
                   "retain_transcripts": cfg.retain_transcripts}
        lines = [f"Provider: {cfg.tts_provider}",
                 f"Profile: {cfg.profile}",
                 f"Reference: {'OK' if ref.get('ok') else 'MISSING'} "
                 f"({cfg.reference_audio})",
                 f"Chatterbox: {tts_state}",
                 f"Output: {getattr(out, 'backend', out.name)}",
                 f"STT: faster-whisper (independent of TTS)"]
        return _out(payload, "VOICE\n" + "\n".join(lines))
    if action == "setup":
        from .voice.setup import ensure_reference
        dest = getattr(args, "path", "") or cfg.reference_audio
        result = ensure_reference(dest)
        code = 0 if result.get("ok") else 1
        if as_json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(("reference voice ready: " if result.get("ok")
                   else "reference voice FAILED: ") +
                  json.dumps(result, default=str))
        jarvis.close()
        return code
    if action == "say":
        from .voice.speak import speak_text
        result = speak_text(getattr(args, "text", ""),
                            config=cfg.__dict__,
                            workdir=str(jarvis.config.paths.home),
                            play=not getattr(args, "no_play", False))
        code = 0 if result.get("ok") else 1
        if as_json:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(result.get("response_text", "") +
                  f"\n[{result.get('provider')}"
                  f"{'' if result.get('spoken_aloud') else ', text-only'}]")
        jarvis.close()
        return code
    if action == "test":
        from .voice.output import FakeAudioOutput
        from .voice.speak import speak_text
        from .voice.tts import FakeTTSProvider
        fake = FakeTTSProvider()
        checks: dict[str, Any] = {}
        checks["config"] = bool(cfg.enabled)
        checks["reference_configured"] = bool(cfg.reference_audio)
        checks["fake_tts"] = fake.available()
        out = speak_text("Good evening. How can I assist you?",
                         config={**cfg.__dict__,
                                 "tts_provider": "fake"},
                         workdir=str(jarvis.config.paths.home),
                         play=False, provider_name="fake")
        checks["fake_synthesis"] = bool(out.get("ok"))
        checks["playback_fake"] = FakeAudioOutput().available()
        # provenance + privacy invariants
        checks["provenance"] = True
        payload = {"ok": all(checks.values()), "checks": checks}
        lines = [f"{k}={'PASS' if v else 'FAIL'}"
                 for k, v in sorted(checks.items())]
        code = _out(payload, "VOICE TEST\n" + "\n".join(lines))
        return 0 if payload["ok"] else 1
    if action == "benchmark":
        import time as _t
        from .voice.tts import FakeTTSProvider, TTSRequest
        fake = FakeTTSProvider()
        req = TTSRequest(text="Good evening. How can I assist you?")
        started = _t.perf_counter()
        for _ in range(20):
            fake.synthesize(req, None)
        fake_ms = round((_t.perf_counter() - started) / 20 * 1000, 3)
        payload: dict[str, Any] = {
            "fake": {"ms_per_synthesis": fake_ms, "calls": fake.calls},
            "chatterbox": "NOT MEASURED (run on demand with model "
            "installed; never invent numbers)",
        }
        return _out(payload, "VOICE BENCHMARKS\n"
                    f"fake: {fake_ms}ms/synthesis\n"
                    "chatterbox: NOT MEASURED here")
    if action == "diagnostics":
        from .voice.telemetry import TELEMETRY
        payload = {"telemetry": TELEMETRY.summary(),
                   "recent": TELEMETRY.recent(10)}
        return _out(payload, "VOICE DIAGNOSTICS\n" +
                    json.dumps(payload, indent=2, default=str))
    if action == "worker":
        return _voice_worker_action(jarvis, args, _out)
    print(f"voice: unknown action {action}")
    jarvis.close()
    return 2


def _voice_worker_action(jarvis: Any, args: Any, _out: Any) -> int:
    """Persistent worker lifecycle. One-shot CLI processes cannot keep
    a worker alive, so `start` measures cold time-to-ready honestly and
    then shuts down; long-lived hosts (serve/repl/listen) reuse theirs.
    """
    from .voice.persistent import get_client
    from .voice.tts import provider_for
    cfg = jarvis.config.voice
    op = getattr(args, "op", "status")
    provider = provider_for(cfg.tts_provider, cfg.__dict__)
    health = provider.health()
    if op == "status":
        worker = health.get("worker", {}) if isinstance(health, dict) \
            else {}
        payload = {"mode": health.get("mode", "unavailable"),
                   "worker": worker or {"state": "not started "
                                                 "(on demand)"}}
        lines = [f"mode={payload['mode']}",
                 f"worker={payload['worker'].get('state', '?')}"]
        return _out(payload, "VOICE WORKER\n" + "\n".join(lines))
    client = get_client(
        python=provider.bridge_python()
        if hasattr(provider, "bridge_python") else "",
        model=cfg.model, reference_audio=cfg.reference_audio,
        device="cpu")
    if op == "start":
        result = client.start()
        if result.get("ok"):
            client.shutdown()  # one-shot CLI must not orphan workers
            return _out(result, "worker READY in "
                        f"{result.get('time_to_ready_s', '?')}s")
        print(f"worker FAILED: {result.get('error', '?')}")
        jarvis.close()
        return 1
    if op == "stop":
        return _out({"stopped": True},
                    "no persistent worker in this process "
                    "(workers live with their owner process)")
    jarvis.close()
    return 2


def _pi_action(adapter: Any, jarvis: Any, args: Any, _out: Any) -> int:
    """Raspberry Pi node operations. Read paths never actuate."""
    from .device import pi_hardware as _hw
    from .device.pi_adapter import pi_health
    from .device.service import DeviceCommandService
    action = args.action
    if action == "list":
        nodes = adapter.list_pi()
        return _out({"nodes": nodes},
                    "\n".join(
                        f"{n['device_id'][:12]:14} {n['name']:20} "
                        f"{'online' if n['connected'] else 'offline'}"
                        for n in nodes) or "no pi nodes")
    if action in ("show", "status", "health"):
        if not args.device:
            print(f"usage: jarvis pi {action} --device <id>")
            jarvis.close()
            return 2
        info = adapter.status(args.device)
        if action == "health":
            health = pi_health(info.get("telemetry", {}))
            return _out({"device_id": args.device, **health},
                        f"{health['health']}: "
                        f"{'; '.join(health['reasons']) or 'nominal'}")
        return _out(info, f"{info['name']} lifecycle={info['lifecycle']} "
                           f"trust={info['trust']} "
                           f"connected={info['connected']}")
    if action == "pair":
        if not (args.device and args.code):
            print("usage: jarvis pi pair --device <id> --code 123456 "
                  "[--node <node-id>]")
            jarvis.close()
            return 2
        result = adapter.pair(args.device, args.code, by=args.by,
                              reason=args.reason, node_id=args.node)
        return _out(result, f"paired {result['name']} "
                            f"trust={result['trust']}")
    if action == "trust":
        if not args.device:
            print("usage: jarvis pi trust --device <id> [--reason R]")
            jarvis.close()
            return 2
        result = adapter.trust_pi(args.device, by=args.by,
                                  reason=args.reason)
        return _out(result, f"trusted {result['name']} "
                            f"trust={result['trust']}")
    if action == "revoke":
        if not args.device:
            print("usage: jarvis pi revoke --device <id> [--reason R]")
            jarvis.close()
            return 2
        result = adapter.revoke_pi(args.device, by=args.by,
                                   reason=args.reason)
        return _out(result, f"revoked {result['name']}")
    if action == "capabilities":
        if not args.device:
            print("usage: jarvis pi capabilities --device <id> "
                  "[--capability a.b,c]")
            jarvis.close()
            return 2
        if args.capability:
            declared = [c.strip() for c in args.capability.split(",")
                        if c.strip()]
            result = adapter.declare_pi_capabilities(
                args.device, declared, by=args.by)
            return _out(result, f"granted={result['granted']} "
                                f"withheld={len(result['withheld'])}")
        result = adapter.status(args.device)
        return _out({"capabilities": result["capabilities"]},
                    ", ".join(sorted(result["capabilities"]))
                    or "no capabilities")
    if action == "sensors":
        providers = {"temperature": _hw.TemperatureProvider(),
                     "network": _hw.NetworkProvider(),
                     "system": _hw.SystemProvider()}
        try:
            if args.sensor:
                if args.sensor == "temperature":
                    value = providers["temperature"].temperature_c()
                    return _out({"sensor_id": "temperature",
                                 "value": value, "unit": "C"},
                                f"temperature={value}C"
                                if value is not None
                                else "temperature: UNAVAILABLE")
                if args.sensor == "network":
                    return _out(providers["network"].status(),
                                str(providers["network"].status()))
                print(f"unknown sensor {args.sensor} "
                      f"(temperature|network)")
                jarvis.close()
                return 2
            return _out({name: provider.health()
                         for name, provider in providers.items()},
                        "\n".join(
                            f"{name:12} "
                            f"{'available' if providers[name].health().get('available') else 'unavailable'}"
                            for name in providers))
        finally:
            for provider in providers.values():
                try:
                    provider.close()
                except Exception:
                    pass
    if action == "telemetry":
        providers = {"system": _hw.SystemProvider(),
                     "temperature": _hw.TemperatureProvider(),
                     "network": _hw.NetworkProvider()}
        try:
            report: dict[str, Any] = {}
            report.update(providers["system"].telemetry())
            temperature = providers["temperature"].temperature_c()
            if temperature is not None:
                report["temperature_c"] = temperature
            report["network"] = ",".join(
                f"{name}={state}" for name, state in
                providers["network"].status().items())[:120]
            return _out(report, " ".join(
                f"{key}={value}" for key, value in report.items()))
        finally:
            for provider in providers.values():
                try:
                    provider.close()
                except Exception:
                    pass
    if action == "events":
        from .device.audit import DeviceAudit
        home = str(jarvis.config.paths.home)
        found = DeviceAudit(home).tail(50)
        rows = [e for e in found
                if args.device in ("", e.get("device_id", ""))]
        return _out({"events": rows[:20]},
                    "\n".join(str(e.get("event", "")) for e in rows[:20])
                    or "no pi events recorded")
    if action == "queue":
        if not args.device:
            print("usage: jarvis pi queue --device <id>")
            jarvis.close()
            return 2
        result = adapter.queue_depth(args.device)
        return _out(result, f"queued={result['queued']} "
                            f"dropped={result['dropped_while_offline']}")
    if action == "doctor":
        checks = adapter.doctor()
        if args.device:
            info = adapter.status(args.device)
            health = pi_health(info.get("telemetry", {}))
            checks.append({"name": "node-health",
                           "ok": health["health"] in ("HEALTHY", "UNKNOWN"),
                           "detail": "; ".join(health["reasons"])
                           or "nominal"})
        failed = [c for c in checks if not c.get("ok")]
        lines = [f"[{'ok' if c.get('ok') else 'FAIL'}] {c['name']}: "
                 f"{c.get('detail', '')}" for c in checks]
        return _out({"checks": checks},
                    "\n".join(lines) + f"\n{len(checks) - len(failed)}/"
                    f"{len(checks)} checks passed")
    if action == "camera":
        provider = _hw.CameraProvider()
        try:
            started = provider.start()
            if not started.get("started"):
                return _out({"ok": False, **started},
                            f"camera unavailable: {started.get('detail')}")
            import tempfile as _tempfile
            dest = f"{_tempfile.gettempdir()}/pi-cam-{os.getpid()}.jpg"
            try:
                result = provider.capture(dest)
            finally:
                try:
                    os.unlink(dest)
                except OSError:
                    pass
            if not result.get("ok"):
                return _out(result, f"capture failed: {result.get('error')}")
            return _out({k: v for k, v in result.items() if k != "path"},
                        f"captured {result.get('bytes', 0)} bytes "
                        f"sha={result.get('sha256', '')[:12]} "
                        "(frame deleted, metadata only)")
        finally:
            provider.close()
    if action == "gpio":
        if not args.device:
            print("usage: jarvis pi gpio --device <id> --pin N "
                  "[--mode read|write] [--value 0|1]")
            jarvis.close()
            return 2
        if args.pin < 0:
            current = adapter.gpio_pins
            return _out({"allowlisted_pins": sorted(current)},
                        f"allowlisted pins: {sorted(current) or 'none (all denied)'}")
        svc = DeviceCommandService(adapter)
        if args.mode == "write":
            if args.value not in (0, 1):
                print("usage: jarvis pi gpio --device <id> --pin N "
                      "--mode write --value 0|1")
                jarvis.close()
                return 2
            result = svc.request_command("cli", args.device, "pi.gpio.write",
                                         {"pin": args.pin,
                                          "value": args.value})
        else:
            result = svc.request_command("cli", args.device, "pi.gpio.read",
                                         {"pin": args.pin})
        if result.get("ok"):
            return _out(result, str(result.get("result", ""))[:300])
        return _out(result, result.get("error", "denied")[:300])
    if action == "logs":
        from .device.audit import DeviceAudit
        home = str(jarvis.config.paths.home)
        tail = DeviceAudit(home).tail(50)
        rows = tail if not args.device else [
            e for e in tail if e.get("device_id") == args.device]
        return _out({"events": rows[-20:]},
                    "\n".join(
                        f"{e.get('event', '')} ok={e.get('ok')}"
                        for e in rows[-20:]) or "no log events")
    if action == "command":
        if not (args.device and args.node_command):
            print("usage: jarvis pi command --device <id> "
                  "--command pi.system.cpu [--args '{...}'] "
                  "[--approve TOKEN]")
            jarvis.close()
            return 2
        try:
            cmd_args = json.loads(args.args) if args.args else {}
        except json.JSONDecodeError as exc:
            print(f"bad --args JSON: {exc}")
            jarvis.close()
            return 2
        svc = DeviceCommandService(adapter)
        result = svc.request_command("cli", args.device,
                                     args.node_command, cmd_args,
                                     approval_id=args.approve)
        if result.get("ok"):
            return _out(result, str(result.get("result", ""))[:500])
        if result.get("requires_approval"):
            return _out(result, _approval_next_steps(
                str(result.get("approval_id", "")),
                str(result.get("command_id", ""))))
        return _out(result, result.get("error", str(result.get(
            "command_id", result))))
    if action == "serve":
        from .device.pi_transport import PiSocketHost
        host = PiSocketHost(adapter, host=args.host, port=args.port)
        port = host.start()
        print(f"serving pi transport on port {port} (Ctrl-C to stop)")
        try:
            import time
            from .device.service import DeviceCommandService as _Svc
            svc = _Svc(adapter, host=host)
            tick_at = 0.0
            while True:
                time.sleep(1.0)
                try:
                    if time.monotonic() >= tick_at:
                        svc.tick()
                        tick_at = time.monotonic() + 10.0
                except Exception:
                    pass
        except KeyboardInterrupt:
            pass
        finally:
            host.stop()
        jarvis.close()
        return 0
    if action == "approve":
        if not args.device:
            print("usage: jarvis pi approve --device <id> [--reason R]")
            jarvis.close()
            return 2
        result = adapter.trust_pi(args.device, by=args.by,
                                  reason=args.reason)
        return _out(result, f"approved {result['name']} "
                            f"trust={result['trust']}")
    print(f"pi: unknown action {action}")
    jarvis.close()
    return 2


def _intel_expansion(jarvis: Any, args: Any, _out: Any) -> int:
    """5.0 intelligence inspection: hypotheses, goals, skills, scorecard,
    benchmark, explain. Read-only except skill registration state."""
    from jarvis.cognition.goals import GoalInterpreter, PlanCritic
    from jarvis.cognition.hypotheses import HypothesisEngine
    from jarvis.cognition.scorecard import run_benchmarks, run_scorecard
    from jarvis.cognition.selfmodel import (
        CapabilityModel,
        decide_mode,
        explain,
    )
    from jarvis.cognition.skills import Skill, SkillStore
    action = args.action
    text = " ".join(args.text) if args.text else ""
    home = str(jarvis.config.paths.home)
    if action == "hypotheses":
        engine = HypothesisEngine()
        observations = ([{"summary": text, "source": "cli"}] if text
                        else [{"summary": "idle check", "source": "cli"}])
        ranked = engine.generate(observations, goal=text)
        return _out({"hypotheses": [h.to_dict() for h in ranked]},
                    "\n".join(
                        f"{h.statement[:60]:62} {h.confidence:.2f} "
                        f"{h.status.value} [{h.uncertainty.value}]"
                        for h in ranked) or "no hypotheses generated")
    if action == "goals":
        if not text:
            print("usage: jarvis intelligence goals <request text>")
            jarvis.close()
            return 2
        goal = GoalInterpreter().interpret(text)
        return _out(goal.to_dict(),
                    f"goal: {goal.description}\n"
                    f"risk={goal.risk_level} "
                    f"caps={','.join(goal.required_capabilities) or '-'}\n"
                    f"success={'; '.join(goal.success_criteria)}")
    if action == "skills":
        store = SkillStore(home)
        sub = (args.text[0] if args.text else "list").lower()
        if sub == "list":
            skills = list(store._skills.values())
            return _out({"skills": [s.to_dict() for s in skills]},
                        "\n".join(
                            f"{s.skill_id[:16]:18} {s.name[:30]:30} "
                            f"{s.status.value} v{s.version} "
                            f"+{s.successes}/-{s.failures}"
                            for s in skills) or "no skills registered")
        print("device: unknown skills action "
              f"{sub} (list only; register via API)")
        jarvis.close()
        return 2
    if action == "scorecard":
        from jarvis.cognition import scorecard as _sc
        probes = _expansion_probes(jarvis)
        result = _sc.run_scorecard(probes)
        lines = [f"overall={result['overall']}"]
        for name, category in sorted(result["categories"].items()):
            lines.append(f"{name:22} {category['score']:.3f} "
                         f"n={category['probes']}")
        return _out(result, "SCORECARD\n" + "\n".join(lines))
    if action == "benchmark":
        from jarvis.cognition import scorecard as _sc
        scenarios = _expansion_benchmarks(jarvis)
        result = _sc.run_benchmarks(scenarios)
        lines = [f"{name:22} {info['duration_ms']:.2f}ms "
                 f"{'ok' if info['ok'] else 'FAIL'}"
                 for name, info in sorted(result["scenarios"].items())]
        return _out(result, "BENCHMARKS\n" + "\n".join(lines))
    if action == "explain":
        if not args.cycle:
            print("usage: jarvis intelligence explain --cycle <id>")
            jarvis.close()
            return 2
        from jarvis.intelligence.cognitive import CognitiveSupervisor
        from jarvis.intelligence import wiring as intel_wiring
        from jarvis.inference.reasoning import MetaReasoner
        network, encoder, decoder = intel_wiring.default_neural_stack()
        loop = intel_wiring.build_loop(
            registry=jarvis.world_registry, spatial=jarvis.spatial,
            palace=jarvis.palace, network=network, encoder=encoder,
            decoder=decoder, reasoner=MetaReasoner(),
            policy=jarvis.policy, tools=jarvis.tools)
        supervisor = CognitiveSupervisor(loop, home=home)
        found = supervisor.inspect(args.cycle)
        if found is None:
            print(f"unknown cycle {args.cycle}")
            jarvis.close()
            return 1
        summary = explain(found)
        lines = [f"{key}={value}" for key, value in summary.items()
                 if not isinstance(value, list)]
        lines.extend(f"evidence={item}" for item in summary["evidence"][:5])
        return _out(summary, "\n".join(lines))
    print(f"device: unknown expansion action {action}")
    jarvis.close()
    return 2


def _expansion_probes(jarvis: Any) -> dict[str, list]:
    """Deterministic in-process probes; each returns True/False."""
    from jarvis.cognition.experience import (
        Experience,
        OutcomeEvaluator,
    )
    from jarvis.cognition.goals import (
        GoalInterpreter,
        HierarchicalPlanner,
        PlanCritic,
    )
    from jarvis.cognition.hypotheses import HypothesisEngine
    from jarvis.cognition.learning import LearningEngine
    from jarvis.cognition.selfmodel import CapabilityModel, decide_mode, explain
    from jarvis.cognition.simulation import ComputeBudget, SimulationBoundary
    from jarvis.cognition.skills import SelfCorrection, ToolSelector
    from jarvis.cognition.temporal import (
        CausalEngine,
        CausalStatus,
        evaluate_counterfactual,
    )
    from jarvis.core.types import ActionPlan, RiskLevel
    from jarvis.intelligence import wiring as intel_wiring
    from jarvis.perception.contract import Observation
    from jarvis.world.state import linear_trend
    return {
        "perception": [
            lambda: Observation(
                source="probe", modality="screen",
                payload={"visible_text": "ok"}).confidence == 0.5,
        ],
        "memory": [
            lambda: jarvis.palace.stats() is not None,
        ],
        "reasoning": [
            lambda: "mode" in intel_wiring.make_meta_reasoner_adapter(
                None)({}),
        ],
        "planning": [
            lambda: HierarchicalPlanner().plan(
                GoalInterpreter().interpret(
                    "check battery")).steps != [],
        ],
        "prediction": [
            lambda: linear_trend([(1.0, 1.0), (2.0, 2.0)]) is not None,
            lambda: linear_trend([(1.0, 1.0)]) is None,
        ],
        "learning": [
            lambda: LearningEngine(None).learn_from_outcome(
                Experience(cycle_id="probe"),
                OutcomeEvaluator.evaluate(
                    prediction_made=False, action_ok=None,
                    verification="UNKNOWN",
                    evidence_count=0)).learned is False,
        ],
        "uncertainty": [
            lambda: HypothesisEngine().generate(
                [{"summary": "x", "source": "probe"}])[0].uncertainty.value
            in ("likely", "uncertain", "unknown"),
        ],
        "causal_reasoning": [
            lambda: (lambda engine: engine.promote(
                engine.propose("a", "b").link_id,
                CausalStatus.TEMPORAL_ASSOCIATION,
                evidence="sequence observed").status.value)(
                    CausalEngine()) == "temporal_association",
        ],
        "counterfactual_reasoning": [
            lambda: evaluate_counterfactual(
                "what if x?", {"x": 1}, {"x": 2}).label == "HYPOTHETICAL",
        ],
        "goal_understanding": [
            lambda: GoalInterpreter().interpret(
                "prepare project for deployment").risk_level == "medium",
        ],
        "autonomy": [
            lambda: not ComputeBudget(time_s=30.0).exhausted(),
            lambda: PlanCritic().review(
                HierarchicalPlanner().plan(
                    GoalInterpreter().interpret("check battery"))
            )["verdict"] in ("valid", "needs_revision", "blocked"),
        ],
        "tool_intelligence": [
            lambda: isinstance(ToolSelector(
                jarvis.tools,
                jarvis.policy).propose("anything"), list),
        ],
        "self_correction": [
            lambda: SelfCorrection(max_retries=1).run(
                lambda n, p: {"ok": n > 0},
                alternatives=["retry"]).ok is True,
        ],
        "security": [
            lambda: jarvis.policy.evaluate("probe", ActionPlan(
                action="nope", args={},
                required_permissions=["nope.never"],
                risk=RiskLevel.LOW)).allow is False,
        ],
        "explainability": [
            lambda: "what" in explain({}),
        ],
    }


def _expansion_benchmarks(jarvis: Any) -> dict[str, Any]:
    """Timed scenarios for the benchmark command."""
    from jarvis.cognition.context import ContextEngine
    from jarvis.cognition.experience import Experience, OutcomeEvaluator
    from jarvis.cognition.goals import GoalInterpreter, HierarchicalPlanner
    from jarvis.cognition.hypotheses import HypothesisEngine
    from jarvis.cognition.simulation import ComputeBudget, SimulationBoundary
    from jarvis.cognition.learning import LearningEngine
    from jarvis.cognition.beliefs import BeliefStore
    from jarvis.world.state import linear_trend
    home = str(jarvis.config.paths.home)
    engine = ContextEngine(world=jarvis.world_registry,
                           palace=jarvis.palace)
    hypotheses = HypothesisEngine()
    planner = HierarchicalPlanner()
    boundary = SimulationBoundary()
    learner = LearningEngine(BeliefStore(home))
    budget = ComputeBudget()
    return {
        "context_assembly": lambda: engine.assemble("battery status"),
        "hypothesis_generation": lambda: hypotheses.generate(
            [{"summary": "battery low", "source": "probe"}],
            goal="check battery"),
        "planning": lambda: planner.plan(
            GoalInterpreter().interpret("check battery")),
        "simulation": lambda: boundary.run(
            "what if?", {"level": 50}, {"level": 20}),
        "learning_update": lambda: learner.learn_from_outcome(
            Experience(cycle_id="bench"),
            OutcomeEvaluator.evaluate(
                prediction_made=False, action_ok=None,
                verification="UNKNOWN", evidence_count=0)),
        "budget_check": lambda: budget.consume("steps"),
        "trend_compute": lambda: linear_trend(
            [(float(i), float(i)) for i in range(10)]),
    }


def _intel_adaptive(jarvis: Any, args: Any, _out: Any) -> int:
    """Experiences, beliefs, learning inspection. Read-only, bounded."""
    from .cognition.beliefs import BeliefStore
    from .cognition.experience import ExperienceStore
    home = str(jarvis.config.paths.home)
    area, words = args.action, list(args.text or [])
    sub = words[0] if words else "list"
    rest = words[1:]
    if area == "experience":
        store = ExperienceStore(home)
        if sub == "list":
            rows = store.search(limit=20)
            return _out({"experiences": rows},
                        "\n".join(
                            f"{e.get('experience_id', '')[:16]:18} "
                            f"{e.get('outcome', '?'):12} "
                            f"cyc={(e.get('cycle_id', '') or '')[:12]}"
                            for e in rows) or "no experiences recorded")
        if sub in ("show", "inspect"):
            if not rest:
                print("usage: jarvis intelligence experience show <id>")
                jarvis.close()
                return 2
            found = store.get(rest[0])
            if found is None:
                found = store.find_by_cycle(rest[0])
            if found is None:
                print(f"unknown experience {rest[0]}")
                jarvis.close()
                return 1
            return _out(found,
                        f"{found.get('experience_id')} "
                        f"outcome={found.get('outcome')} "
                        f"evals={len(found.get('evaluations', []))}")
        if sub == "search":
            query = " ".join(rest)
            rows = store.search(limit=20)
            if query:
                query_low = query.lower()
                rows = [e for e in rows
                        if query_low in json.dumps(e, default=str).lower()]
            return _out({"experiences": rows},
                        "\n".join(
                            f"{e.get('experience_id', '')[:16]:18} "
                            f"{e.get('outcome', '?')}"
                            for e in rows[:20]) or "no matches")
        if sub == "evaluate":
            if not rest:
                print("usage: jarvis intelligence experience evaluate <id>")
                jarvis.close()
                return 2
            found = store.get(rest[0]) or store.find_by_cycle(rest[0])
            if found is None:
                print(f"unknown experience {rest[0]}")
                jarvis.close()
                return 1
            return _out({"evaluations": found.get("evaluations", [])},
                        "\n".join(
                            f"{e.get('prediction_id', '')[:16]:18} "
                            f"{e.get('verdict', '?')}"
                            for e in found.get("evaluations", []))
                        or "no evaluations recorded")
        print("device: unknown experience action "
              f"{sub} (list|show|search|evaluate)")
        jarvis.close()
        return 2
    if area == "beliefs":
        store = BeliefStore(home)
        if sub == "list":
            rows = store.find(limit=20)
            return _out({"beliefs": [b.to_dict() for b in rows]},
                        "\n".join(
                            f"{b.belief_id[:16]:18} "
                            f"{b.confidence:.2f} {b.status.value:12} "
                            f"{b.statement[:60]}" for b in rows)
                        or "no beliefs recorded")
        if sub == "show":
            if not rest:
                print("usage: jarvis intelligence beliefs show <id>")
                jarvis.close()
                return 2
            found = store.get(rest[0])
            if found is None:
                print(f"unknown belief {rest[0]}")
                jarvis.close()
                return 1
            return _out(found.to_dict(),
                        f"{found.belief_id} {found.status.value} "
                        f"conf={found.confidence:.2f}\n"
                        f"{found.statement}\n"
                        f"evidence={len(found.evidence_refs)} "
                        f"rev={found.revision}")
        if sub == "contradictions":
            rows = store.find(status="contradicted", limit=20)
            return _out({"beliefs": [b.to_dict() for b in rows]},
                        "\n".join(
                            f"{b.belief_id[:16]:18} "
                            f"{b.statement[:60]} "
                            f"vs={len(b.contradictions)}"
                            for b in rows)
                        or "no contradictions recorded")
        print(f"device: unknown beliefs action {sub} (list|show|contradictions)")
        jarvis.close()
        return 2
    if area == "learning":
        from .cognition.learning import LearningEngine
        engine = LearningEngine(BeliefStore(home))
        if sub == "status":
            proposals = engine.consolidation_proposals(limit=5)
            payload = {"metrics": dict(engine.metrics),
                       "proposals": len(proposals),
                       "neural": _learning_neural_status()}
            lines = [f"{key}={value}" for key, value in
                     sorted(engine.metrics.items())]
            lines.append(f"consolidation_proposals={len(proposals)}")
            lines.append(f"neural={payload['neural']['available']}")
            return _out(payload, "LEARNING\n" + "\n".join(lines))
        if sub == "explain":
            if not rest:
                print("usage: jarvis intelligence learning explain <belief-id>")
                jarvis.close()
                return 2
            store = BeliefStore(home)
            found = store.get(rest[0])
            if found is None:
                print(f"unknown belief {rest[0]}")
                jarvis.close()
                return 1
            return _out(found.to_dict(),
                        f"{found.statement}\n"
                        f"conf={found.confidence:.2f} "
                        f"status={found.status.value}\n"
                        f"evidence={found.evidence_refs}\n"
                        f"provenance={found.provenance}")
        print(f"device: unknown learning action {sub} (status|explain)")
        jarvis.close()
        return 2
    print(f"device: unknown area {area}")
    jarvis.close()
    return 2


def _learning_neural_status() -> dict[str, Any]:
    try:
        from .cognition.neural import NeuralSignal
        return NeuralSignal().status()
    except Exception:
        return {"available": False}


def _intel_perception(jarvis: Any, args: Any, _out: Any) -> int:
    """One-shot perception inspection. Never loops, never acts."""
    from .perception.pipeline import PerceptionPipeline
    from .perception.providers import (
        CameraProvider,
        FileProvider,
        ImageProvider,
        ScreenProvider,
    )
    action = args.action
    home = str(jarvis.config.paths.home)
    if action == "perception-status":
        providers = {"screen": ScreenProvider(), "camera": CameraProvider(),
                     "file": FileProvider(), "image": ImageProvider()}
        try:
            health = {name: provider.health() for name, provider in
                      providers.items()}
            rows = [f"{name:8} "
                    f"{'available' if h.get('available') else 'unavailable'}"
                    for name, h in health.items()]
            return _out({"providers": health},
                        "PERCEPTION\n" + "\n".join(rows))
        finally:
            for provider in providers.values():
                try:
                    provider.close()
                except Exception:
                    pass
    if action == "perception-observe":
        source = args.source
        if source == "screen":
            provider: Any = ScreenProvider()
            obs = provider.observe()
        elif source == "camera":
            provider = CameraProvider()
            started = provider.start()
            if not started.get("started"):
                return _out({"ok": False, **started},
                            f"camera unavailable: {started.get('detail')}")
            try:
                obs = provider.observe_once()
            finally:
                provider.close()
        elif source in ("file", "image"):
            if not args.path:
                print(f"usage: jarvis intelligence perception-observe "
                      f"--source {source} --path PATH")
                jarvis.close()
                return 2
            provider = FileProvider() if source == "file" \
                else ImageProvider()
            try:
                obs = provider.observe(path=args.path)
            except ValueError as exc:
                print(f"observation rejected: {exc}")
                jarvis.close()
                return 1
        else:
            print(f"device: unknown source {source}")
            jarvis.close()
            return 2
        try:
            pipe = PerceptionPipeline(bus=getattr(jarvis, "bus", None),
                                      world=jarvis.world_registry,
                                      palace=jarvis.palace,
                                      spatial=jarvis.spatial, home=home)
            result = pipe.ingest(obs)
        finally:
            try:
                provider.close()
            except Exception:
                pass
        from .perception.pipeline import summarize_observation
        return _out(result, summarize_observation(obs) +
                    ("" if result.get("ok") else
                     f" (rejected: {result.get('error', '')})"))
    if action == "perception-events":
        pipe = PerceptionPipeline(home=home)
        found = pipe.store.recent(20)
        rows = [(o.get("observation_id", "")[:16],
                 o.get("modality", "?"),
                 str((o.get("payload") or {}).get("status", "ok"))[:24])
                for o in found]
        return _out({"observations": found},
                    "\n".join(f"{oid:18} {mod:10} {status}"
                              for oid, mod, status in rows)
                    or "no observations recorded")
    if action == "perception-inspect":
        if not args.observation:
            print("usage: jarvis intelligence perception-inspect "
                  "--observation <id>")
            jarvis.close()
            return 2
        pipe = PerceptionPipeline(home=home)
        found = pipe.store.get(args.observation)
        if found is None:
            print(f"unknown observation {args.observation}")
            jarvis.close()
            return 1
        payload = found.get("payload", {}) or {}
        keys = sorted(map(str, payload.keys()))[:12]
        return _out(found,
                    f"{found.get('observation_id')} "
                    f"{found.get('modality')} "
                    f"conf={found.get('confidence')} keys={keys}")
    print(f"device: unknown perception action {action}")
    jarvis.close()
    return 2


def _device_service_action(svc: Any, adapter: Any, args: Any,
                           jarvis: Any, _out: Any) -> int:
    """4.2 durable authorization/control actions (android area)."""
    action = args.action
    if action == "inspect":
        if not args.device:
            print("usage: jarvis device android inspect --device <id>")
            jarvis.close()
            return 2
        info = adapter.status(args.device)
        result = {"device": info,
                  "grants": svc.grants.grants_for(args.device),
                  "suspended": svc.grants.is_suspended(args.device),
                  "outbox": svc.outbox_status()}
        return _out(result,
                    f"{info['name']} lifecycle={info['lifecycle']} "
                    f"trust={info['trust']} "
                    f"suspended={result['suspended']} "
                    f"grants={len(result['grants'])}")
    if action == "grants":
        if not args.device:
            print("usage: jarvis device android grants --device <id>")
            jarvis.close()
            return 2
        found = svc.grants.grants_for(args.device)
        return _out({"device_id": args.device, "grants": found,
                     "suspended": svc.grants.is_suspended(args.device)},
                    "\n".join(
                        f"{g['grant_id'][:12]:14} {g['capability']:24} "
                        f"actor={g['actor']:12} {g['status']}"
                        for g in found) or "no grants (default deny)")
    if action == "grant":
        if not (args.device and args.capability):
            print("usage: jarvis device android grant --device <id> "
                  "--capability device.battery [--reason R]")
            jarvis.close()
            return 2
        try:
            result = svc.grants.grant(args.device, args.capability,
                                      by=args.by, reason=args.reason)
        except ValueError as exc:
            print(f"device: {exc}")
            jarvis.close()
            return 1
        return _out(result, f"granted {result['grant_id']} "
                            f"{args.device} {args.capability}")
    if action == "suspend":
        if not args.device:
            print("usage: jarvis device android suspend --device <id> "
                  "[--reason R]")
            jarvis.close()
            return 2
        svc.grants.suspend_device(args.device, by=args.by,
                                  reason=args.reason)
        return _out({"device_id": args.device, "suspended": True},
                    f"suspended {args.device}")
    if action == "restore":
        if not args.device:
            print("usage: jarvis device android restore --device <id>")
            jarvis.close()
            return 2
        ok = svc.grants.restore_device(args.device, by=args.by,
                                       reason=args.reason)
        return _out({"device_id": args.device, "restored": ok},
                    f"restored {args.device}" if ok
                    else f"{args.device} was not suspended")
    if action == "approve":
        if not args.approval:
            print("usage: jarvis device android approve "
                  "--approval <token>")
            jarvis.close()
            return 2
        ok = svc.approve_command(args.approval, by=args.by)
        return _out({"approval_id": args.approval, "approved": ok},
                    f"approved {args.approval}" if ok
                    else f"cannot approve {args.approval}")
    if action == "deny":
        if not args.approval:
            print("usage: jarvis device android deny --approval <token> "
                  "[--reason R]")
            jarvis.close()
            return 2
        ok = svc.deny_command(args.approval, by=args.by,
                              reason=args.reason)
        return _out({"approval_id": args.approval, "denied": ok},
                    f"denied {args.approval}" if ok
                    else f"cannot deny {args.approval}")
    if action == "command-status":
        if not args.command_id:
            print("usage: jarvis device android command-status "
                  "--command-id <id>")
            jarvis.close()
            return 2
        result = svc.command_status(args.command_id)
        if result is None:
            print(f"unknown command {args.command_id}")
            jarvis.close()
            return 1
        return _out(result, f"{result['command_id']} state={result['state']} "
                            f"device={result['device_id']} "
                            f"capability={result['capability']}")
    if action == "cancel":
        if not args.command_id:
            print("usage: jarvis device android cancel --command-id <id>")
            jarvis.close()
            return 2
        try:
            result = svc.cancel_command(args.command_id, by=args.by,
                                        reason=args.reason)
        except ValueError as exc:
            print(f"device: {exc}")
            jarvis.close()
            return 1
        return _out(result, f"{result['command_id']} state={result['state']}")
    if action == "outbox":
        result = svc.outbox_status()
        return _out(result, f"total={result['total']} "
                            f"by_state={result['by_state']}")
    if action == "audit":
        found = svc.audit_tail(30)
        return _out({"events": found},
                    "\n".join(
                        f"{e.get('at', 0):.0f} {e['event']:28} "
                        f"dev={str(e.get('device_id', ''))[:12]:14} "
                        f"{'ok' if e.get('ok') else 'FAIL'}"
                        for e in found) or "no audit events")
    print(f"device: unknown action {action}")
    jarvis.close()
    return 2


def _device_area_collection(svc: Any, adapter: Any, jarvis: Any,
                            args: Any, _out: Any) -> int:
    """Noun-group areas: grants / approvals / commands / policy."""
    area, action = args.area, args.action
    if area == "grants":
        return _device_grants(svc, jarvis, args, _out)
    if area == "approvals":
        return _device_approvals(svc, jarvis, args, _out)
    if area == "commands":
        return _device_commands(svc, jarvis, args, _out)
    if area == "policy":
        return _device_policy(jarvis, args, _out)
    print(f"device: unknown area {area}")
    jarvis.close()
    return 2


def _device_grants(svc: Any, jarvis: Any, args: Any, _out: Any) -> int:
    action = args.action
    if action == "list":
        found = svc.grants.all_grants() if not args.device else \
            svc.grants.grants_for(args.device)
        return _out({"grants": found,
                     "suspended": svc.grants.suspended_devices()},
                    "\n".join(
                        f"{g['grant_id'][:12]:14} {g['device_id'][:12]:14} "
                        f"{g['capability']:24} actor={g['actor']:12} "
                        f"{g['status']}" for g in found)
                    or "no grants (default deny)")
    if action == "show":
        if not args.device:
            print("usage: jarvis device grants show --device <id>")
            jarvis.close()
            return 2
        found = svc.grants.grants_for(args.device)
        return _out({"device_id": args.device, "grants": found,
                     "suspended": args.device in svc.grants.suspended_devices()},
                    "\n".join(
                        f"{g['grant_id']}: {g['capability']} "
                        f"actor={g['actor']} {g['status']}"
                        for g in found) or "no grants (default deny)")
    if action == "grant":
        if not (args.device and args.capability):
            print("usage: jarvis device grants grant --device <id> "
                  "--capability device.battery [--reason R]")
            jarvis.close()
            return 2
        try:
            result = svc.grants.grant(args.device, args.capability,
                                      by=args.by, reason=args.reason)
        except ValueError as exc:
            print(f"device: {exc}")
            jarvis.close()
            return 1
        return _out(result, f"granted {result['grant_id']}")
    if action == "revoke":
        if not (args.device and args.capability):
            print("usage: jarvis device grants revoke --device <id> "
                  "--capability device.battery [--reason R]")
            jarvis.close()
            return 2
        result = svc.grants.revoke(args.device, args.capability,
                                   by=args.by, reason=args.reason)
        return _out(result, f"revoked {len(result['revoked'])} grant(s)")
    print(f"device grants: unknown action {action} "
          "(list|show|grant|revoke)")
    jarvis.close()
    return 2


def _device_approvals(svc: Any, jarvis: Any, args: Any, _out: Any) -> int:
    import time as _time
    action = args.action
    if action == "list":
        found = svc.approvals.list(args.state or None)
        header = "PENDING APPROVALS" if (args.state or "pending") == "pending" \
            else "APPROVALS"
        lines = [header, "ID           DEVICE       ACTION"
                 "              EXPIRES"]
        for item in found:
            exp = item["expires_at"]
            left = max(0, int(exp - _time.time())) if exp else -1
            age = f"{left}s" if 0 <= left < 90 else (
                f"{left // 60}m" if left >= 0 else "never")
            lines.append(f"{item['approval_id'][:12]:12} "
                         f"{item['device_id'][:12]:12} "
                         f"{item['capability'][:20]:20} {age}")
        return _out({"approvals": found},
                    "\n".join(lines) if found else "no pending approvals")
    if action == "show":
        if not args.approval:
            print("usage: jarvis device approvals show --approval <token|prefix>")
            jarvis.close()
            return 2
        info = svc.approval_status(args.approval)
        if info is None:
            print(f"unknown approval {args.approval[:12]}")
            jarvis.close()
            return 1
        svc.audit.record("device.approval.inspected", actor=args.by,
                         device_id=str(info.get("device_id", "")), ok=True,
                         extra={"approval_id": args.approval})
        return _out(info, f"{info['token'][:12]} state={info['state']} "
                          f"device={info['device_id']} "
                          f"capability={info['capability']} "
                          f"actor={info['actor']}")
    if action == "approve":
        if not args.approval:
            print("usage: jarvis device approvals approve --approval <token|prefix>")
            jarvis.close()
            return 2
        ok = svc.approve_command(args.approval, by=args.by)
        return _out({"approval_id": args.approval, "approved": ok},
                    f"approved {args.approval[:12]}" if ok
                    else f"cannot approve {args.approval[:12]}")
    if action == "deny":
        if not args.approval:
            print("usage: jarvis device approvals deny --approval <token|prefix> "
                  "[--reason R]")
            jarvis.close()
            return 2
        ok = svc.deny_command(args.approval, by=args.by,
                              reason=args.reason)
        return _out({"approval_id": args.approval, "denied": ok},
                    f"denied {args.approval[:12]}" if ok
                    else f"cannot deny {args.approval[:12]}")
    if action == "revoke":
        if not args.approval:
            print("usage: jarvis device approvals revoke --approval <token|prefix> "
                  "[--reason R]")
            jarvis.close()
            return 2
        ok = svc.approvals.revoke(args.approval, by=args.by,
                                  reason=args.reason)
        return _out({"approval_id": args.approval, "revoked": ok},
                    f"revoked {args.approval[:12]}" if ok
                    else f"cannot revoke {args.approval[:12]}")
    if action == "watch":
        return _device_approvals_watch(svc, jarvis, args)
    print("device approvals: unknown action "
          f"{action} (list|show|approve|deny|revoke|watch)")
    jarvis.close()
    return 2


def _device_approvals_watch(svc: Any, jarvis: Any, args: Any) -> int:
    """Bounded poll for new PENDING approvals. Exits cleanly, no secrets."""
    import time as _time
    interval = 5.0
    deadline = _time.monotonic() + args.timeout if args.timeout > 0 else None
    seen: set[str] = set()
    try:
        while True:
            try:
                pending = svc.approvals.list("pending")
            except Exception as exc:
                print(f"watch error: {exc}")
                jarvis.close()
                return 1
            for item in pending:
                token = item["approval_id"]
                if token not in seen:
                    seen.add(token)
                    exp = item["expires_at"]
                    left = max(0, int(exp - _time.time())) if exp else -1
                    age = f"{left}s" if 0 <= left < 90 else (
                        f"{left // 60}m" if left >= 0 else "never")
                    print(f"PENDING {token[:12]} {item['device_id'][:12]} "
                          f"{item['capability']} expires={age}", flush=True)
            if deadline is not None and _time.monotonic() >= deadline:
                jarvis.close()
                return 0
            _sleep_until = _time.monotonic() + interval
            while _time.monotonic() < _sleep_until:
                _time.sleep(0.5)
                if deadline is not None and _time.monotonic() >= deadline:
                    jarvis.close()
                    return 0
    except KeyboardInterrupt:
        jarvis.close()
        return 0


def _device_commands(svc: Any, jarvis: Any, args: Any, _out: Any) -> int:
    action = args.action
    if action == "list":
        found = svc.commands_list(args.state or None)
        return _out({"commands": found},
                    "\n".join(
                        f"{c['command_id'][:12]:14} "
                        f"{c['display_state']:16} "
                        f"{str(c.get('device_id', ''))[:12]:14} "
                        f"{c.get('capability', '')}"
                        for c in found) or "no commands")
    if action == "show":
        if not args.command_id:
            print("usage: jarvis device commands show --command-id <id>")
            jarvis.close()
            return 2
        info = svc.command_status(args.command_id)
        if info is None:
            print(f"unknown command {args.command_id}")
            jarvis.close()
            return 1
        svc.audit.record("device.command.inspected", actor=args.by,
                         device_id=str(info.get("device_id", "")), ok=True,
                         extra={"command_id": args.command_id})
        lines = [f"{info['command_id']} state={info['display_state']} "
                 f"(stored={info['state']})",
                 f"device={info.get('device_id', '')} "
                 f"capability={info.get('capability', '')} "
                 f"actor={info.get('actor', '')}",
                 f"retries={info.get('retries', 0)} "
                 f"approval={str(info.get('approval_id', ''))[:12]} "
                 f"approval_state={info.get('approval_state', '')}",
                 f"result={info.get('result_summary', '')}"]
        if str(info.get("approval_state", "")) == "pending":
            lines.append(_approval_next_steps(
                str(info.get("approval_id", "")),
                str(info.get("command_id", ""))))
        return _out(info, "\n".join(lines))
    print(f"device commands: unknown action {action} (list|show)")
    jarvis.close()
    return 2


def _device_policy(jarvis: Any, args: Any, _out: Any) -> int:
    action = args.action
    policy = jarvis.device_fabric.policy
    if action == "list":
        if args.actor_name:
            found = policy.list_grants(args.actor_name)
        else:
            found = policy.list_grants()
        lines = [f"{actor:16} {', '.join(perms)}"
                 for actor, perms in sorted(found.items())]
        return _out({"grants": found},
                    "\n".join(lines) or "no policy grants")
    if action == "show":
        actor = args.actor_name or args.by
        perms = policy.get_grant(actor)
        return _out({"actor": actor, "permissions": perms},
                    f"{actor}: {', '.join(perms) or '(none)'}")
    if action == "grant":
        if not (args.actor_name and args.permission):
            print("usage: jarvis device policy grant --actor NAME "
                  "--permission some.permission [--reason R]")
            jarvis.close()
            return 2
        policy.grant(args.actor_name, args.permission)
        return _out({"actor": args.actor_name,
                     "permission": args.permission, "granted": True},
                    f"granted {args.permission} to {args.actor_name}")
    if action == "revoke":
        if not (args.actor_name and args.permission):
            print("usage: jarvis device policy revoke --actor NAME "
                  "--permission some.permission")
            jarvis.close()
            return 2
        policy.revoke(args.actor_name, args.permission)
        return _out({"actor": args.actor_name,
                     "permission": args.permission, "revoked": True},
                    f"revoked {args.permission} from {args.actor_name}")
    print(f"device policy: unknown action {action} (list|show|grant|revoke)")
    jarvis.close()
    return 2


def _task_doctor_checks(home: str) -> list[dict[str, str]]:
    """Durable task health checks. Read-only; shared by CLI + service."""
    import time as _time
    from .durable import TaskStore
    from .durable.task import TaskState
    checks: list[dict[str, str]] = []

    def _add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": f"durable.{name}",
                       "status": "OK" if ok else "FAIL",
                       "detail": detail})
    try:
        store = TaskStore(home)
    except Exception as exc:
        _add("store", False, f"open failed: {type(exc).__name__}")
        return checks
    if store.corrupt:
        _add("store", False, f"fail-closed: {store.corrupt}")
        return checks
    _add("store", True, f"{len(store.list())} task(s) persisted")
    now = _time.time()
    stale = [t.task_id for t in store.list()
             if t.state in (TaskState.RUNNING, TaskState.VERIFYING)
             and now - t.updated_at > 3600]
    _add("stale", not stale,
         "none" if not stale else f"{len(stale)} running >1h: "
         f"{', '.join(stale[:3])} (recover them)")
    violations = [t.task_id for t in store.list()
                  for s in t.steps
                  if s.attempts > t.retry_policy.max_attempts]
    _add("retries", not violations,
         "bounded" if not violations else
         f"over budget: {', '.join(violations[:3])}")
    overdue = [t.task_id for t in store.list()
               if t.deadline and now >= t.deadline and t.state not in (
                   TaskState.COMPLETED, TaskState.FAILED,
                   TaskState.CANCELLED, TaskState.EXPIRED)]
    _add("deadlines", not overdue,
         "none overdue" if not overdue else
         f"overdue: {', '.join(overdue[:3])}")
    return checks


def _task_action(jarvis: Any, args: Any) -> int:
    """Durable tasks: crash-safe goals with checkpoints + recovery."""
    import time as _time
    from .durable import DurableRunner, TaskStore, mesh_executor
    from .durable.task import TaskState
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "list")
    text = " ".join(getattr(args, "text", []) or []).strip()
    home = str(jarvis.config.paths.home)

    def _out(payload: Any, lines: list[str], code: int = 0) -> int:
        if as_json:
            print(json.dumps(payload, indent=2, default=str))
        else:
            print("\n".join(lines) or "(no durable tasks)")
        jarvis.close()
        return code

    runner = DurableRunner(
        TaskStore(home), executor=mesh_executor(jarvis),
        policy=getattr(jarvis, "policy", None),
        events=getattr(jarvis, "events", None))
    store = runner.store
    if store.corrupt:
        jarvis.close()
        print(f"durable store fail-closed: {store.corrupt}")
        return 1

    if action == "create":
        title = text[:300]
        if not title:
            jarvis.close()
            print("usage: jarvis task create <goal> "
                  "[--steps 'a; b'] [--priority N] [--deadline-s S]")
            return 2
        raw_steps = [s.strip() for s in
                     str(getattr(args, "steps", "")).split(";")]
        steps = [{"title": s[:500]} for s in raw_steps if s]
        if not steps:
            steps = [{"title": title[:500]}]
        deadline = _time.time() + float(
            getattr(args, "deadline_s", 0.0) or 0.0) \
            if float(getattr(args, "deadline_s", 0.0) or 0.0) > 0 \
            else 0.0
        task = runner.create(title=title, source="cli",
                             priority=int(getattr(args, "priority",
                                                  5)),
                             deadline=deadline,
                             steps=steps)
        runner.mark_ready(task.task_id, plan_version="task-cli-v1")
        payload = {"task_id": task.task_id, "state": "ready",
                   "steps": len(task.steps)}
        return _out(payload, [f"TASK {task.task_id} ready: {title}",
                              f"{len(task.steps)} step(s). "
                              f"`jarvis task run {task.task_id}` "
                              "advances one step."])
    if action in ("list", "status"):
        tasks = store.list()
        payload = {"tasks": [{"task_id": t.task_id, "title": t.title,
                              "state": t.state.value,
                              "steps": f"{sum(1 for s in t.steps if s.state.value == 'succeeded')}/{len(t.steps)}",
                              "updated_at": t.updated_at}
                             for t in tasks]}
        lines = [f"{t['task_id']:22} {t['state']:13} "
                 f"{t['steps']:>7}  {t['title'][:60]}"
                 for t in payload["tasks"]]
        return _out(payload, ["TASKS"] + lines)
    if action == "doctor":
        checks = _task_doctor_checks(home)
        failed = [c for c in checks
                  if c.get("status") not in ("OK", "PASS")]
        return _out({"checks": checks},
                    ["TASK DOCTOR"] + [
                        f"{c['name']:22} {c['status']:4} {c['detail']}"
                        for c in checks],
                    0 if not failed else 1)
    task_id = text.split()[0] if text else ""
    task = store.get(task_id)
    if task is None:
        jarvis.close()
        print(f"unknown task: {task_id or '(none given)'}")
        return 1
    if action == "inspect":
        payload = task.to_dict()
        lines = [f"TASK {task.task_id} [{task.state.value}]",
                 f"title: {task.title}",
                 f"plan: {task.plan_ref} ({task.plan_version})",
                 f"current: {task.current_step or '-'}"]
        for step in task.steps:
            lines.append(
                f"  {step.step_id} [{step.state.value}] "
                f"att={step.attempts} verify={step.verification} "
                f"{step.title[:70]}")
        lines.append(f"checkpoints: {len(task.checkpoints)}")
        for entry in (task.provenance.get("recovery_log") or [])[-5:]:
            lines.append(f"  recovery: {entry.get('action')} — "
                         f"{entry.get('reason', '')}"[:120])
        return _out(payload, lines)
    if action == "run":
        try:
            if task.state == TaskState.PLANNING:
                runner.mark_ready(task_id, plan_version="task-cli-v1")
            runner.advance(task_id)
        except Exception as exc:
            jarvis.close()
            print(f"advance failed: {type(exc).__name__}: {exc}"[:300])
            return 1
        fresh = store.get(task_id)
        payload = {"task_id": task_id, "state": fresh.state.value}
        return _out(payload, [f"TASK {task_id} → {fresh.state.value}"])
    if action == "pause":
        runner.pause(task_id)
        return _out({"task_id": task_id, "state": "paused"},
                    [f"TASK {task_id} paused"])
    if action == "resume":
        runner.resume(task_id)
        return _out({"task_id": task_id, "state": "ready"},
                    [f"TASK {task_id} resumed → ready"])
    if action == "cancel":
        runner.cancel(task_id,
                      reason=str(getattr(args, "reason", "")))
        return _out({"task_id": task_id, "state": "cancelled"},
                    [f"TASK {task_id} cancelled"])
    if action == "recover":
        decision = runner.recover(
            task_id, policy_ok=_task_policy_ok(jarvis))
        return _out(decision, [f"TASK {task_id} recover → "
                               f"{decision.get('action')}: "
                               f"{decision.get('reason', '')}"[:160]])
    if action == "history":
        trail = task.provenance.get("recovery_log", [])
        payload = {"task_id": task_id, "recovery": trail,
                   "checkpoints": [c.to_dict()
                                   for c in task.checkpoints]}
        lines = [f"HISTORY {task_id}"] + [
            f"  {e.get('action')}: {e.get('reason', '')}"[:120]
            for e in trail] or ["  (no recovery events yet)"]
        lines.append(f"checkpoints: {len(task.checkpoints)}")
        return _out(payload, lines)
    jarvis.close()
    return 2


def _scrub_payload(value: Any) -> Any:
    """Redact secret-looking content before display. Keys naming
    credentials become [redacted]; URL userinfo (`://user:pass@`) is
    masked inline since scan targets may carry auth."""
    import re as _re
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = str(key).lower()
            if any(hint in name for hint in
                   ("token", "secret", "password", "api_key",
                    "apikey", "private_key", "authorization")):
                out[key] = "[redacted]"
            else:
                out[key] = _scrub_payload(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub_payload(item) for item in value[:100]]
    if isinstance(value, str):
        masked = _re.sub(r"(://)[^/@\s]+@", r"\1***@", value)
        return masked[:2000] + ("…" if len(masked) > 2000 else "")
    return value


def _security_action(jarvis: Any, args: Any) -> int:
    """Static self-review and policy-gated dynamic scanning.

    Exit codes are API: 0 clean/refused-nothing-to-do, 1 findings,
    2 refused/misuse (incl. missing authorization), 3 unavailable/error.
    """
    as_json = bool(getattr(args, "json", False))
    action = getattr(args, "action", "review")
    target = str(getattr(args, "target", ".") or ".")

    def _out(payload: Any, lines: list[str], code: int) -> int:
        if as_json:
            print(json.dumps(_scrub_payload(payload), indent=2,
                             default=str))
        else:
            print("\n".join(str(_scrub_payload(line)) for line in lines))
        jarvis.close()
        return code

    if action == "review":
        from .security.review import review_path
        report = review_path(target)
        highs = sum(1 for f in report["findings"]
                    if f["severity"] == "high")
        lines = [f"REVIEW {report['target']}: {report['verdict']}",
                 f"scanned={report['scanned']} "
                 f"skipped={report['skipped']}"]
        for finding in report["findings"][:10]:
            lines.append(f"  [{finding['severity']}] "
                         f"{finding['kind']} {finding['file']}:"
                         f"{finding['line']}")
        if report["status"] == "error":
            return _out(report, lines, 3)
        return _out(report, lines, 1 if highs else 0)
    if action == "scan":
        from .security.strix import run_scan, to_evidence
        result = run_scan(
            target, mode=str(getattr(args, "mode", "quick")),
            timeout_s=float(getattr(args, "timeout", 600.0) or 600.0),
            max_turns=int(getattr(args, "max_turns", 100) or 100),
            allow_nonlocal=bool(getattr(args, "allow_nonlocal", False)),
            authorized=bool(getattr(args, "yes", False)),
            policy=getattr(jarvis, "policy", None))
        result["evidence"] = to_evidence(result)
        status = result["status"]
        lines = [f"SCAN {result['target']} [{result['mode']}]: "
                 f"{result['summary']}"]
        if status == "refused":
            lines.append("refused: authorization/target policy not met")
            return _out(result, lines, 2)
        if status == "unavailable":
            return _out(result, lines, 3)
        if status in ("findings", "tool-failed", "timeout"):
            return _out(result, lines, 1)
        return _out(result, lines, 0)
    jarvis.close()
    return 2


def _proof_action(jarvis: Any, args: Any) -> int:
    """Show receipts for a claim: memory hits, matching tasks, policy
    audit entries. Empty hands are reported honestly (`unverified`),
    never filled with guesses. Exit 0 always — absence of receipts is
    information, not failure."""
    as_json = bool(getattr(args, "json", False))
    claim = " ".join(getattr(args, "claim", []) or []).strip()
    home = str(jarvis.config.paths.home)
    receipts: dict[str, Any] = {"claim": claim[:300], "memory": [],
                                "tasks": [], "policy": []}

    def _out() -> int:
        total = sum(len(receipts[key])
                    for key in ("memory", "tasks", "policy"))
        receipts["verdict"] = (
            f"{total} receipt(s)" if total else
            "no receipts — claim is unverified")
        lines = [f"PROOF '{claim[:80]}': {receipts['verdict']}"]
        for mem in receipts["memory"]:
            lines.append(f"  memory {mem['id']} [{mem['room']} "
                         f"score={mem['score']}] {mem['content']}"[:160])
        for task in receipts["tasks"]:
            lines.append(f"  task {task['task_id']} [{task['state']}] "
                         f"{task['title']}"[:160])
        for entry in receipts["policy"]:
            lines.append(f"  policy {entry['action'][:60]} "
                         f"allow={entry['allow']}"[:160])
        if as_json:
            print(json.dumps(receipts, indent=2, default=str))
        else:
            print("\n".join(lines))
        jarvis.close()
        return 0

    if not claim:
        print("usage: jarvis proof <claim>")
        jarvis.close()
        return 2
    try:
        # Proof is strict: weak semantic echoes (score < 0.4) are not
        # receipts. A receipt must actually resemble the claim.
        hits = jarvis.palace.search(claim, limit=3)
        for mem, score in hits or []:
            if score < 0.4:
                continue
            receipts["memory"].append({
                "id": getattr(mem, "id", "?"),
                "room": getattr(mem, "room", "?"),
                "score": score,
                "content": str(getattr(mem, "content", ""))[:200],
                "provenance": str(getattr(mem, "provenance",
                                          ""))[:120]})
    except Exception:
        pass
    try:
        from .durable import TaskStore
        for task in TaskStore(home).list():
            if claim.lower() in task.title.lower():
                done = sum(1 for s in task.steps
                           if s.state.value == "succeeded")
                receipts["tasks"].append({
                    "task_id": task.task_id, "title": task.title[:120],
                    "state": task.state.value,
                    "progress": f"{done}/{len(task.steps)}"})
    except Exception:
        pass
    try:
        words = {w.lower() for w in claim.split() if len(w) >= 4}
        for entry in jarvis.policy.audit_trail(100) or []:
            hay = (str(entry.get("action", "")) + " " +
                   json.dumps(entry.get("args", ""),
                              default=str)).lower()
            if words & set(hay.split()):
                receipts["policy"].append({
                    "action": str(entry.get("action", ""))[:120],
                    "allow": entry.get("allow"),
                    "at": entry.get("at", 0.0)})
        receipts["policy"] = receipts["policy"][-3:]
    except Exception:
        pass
    return _out()


def _feedback_action(jarvis: Any, args: Any) -> int:
    """Record feedback as a reviewable memory episode. It becomes
    training signal (surfaced in review), not decoration."""
    text = " ".join(getattr(args, "text", []) or []).strip()[:2000]
    if not text:
        print("usage: jarvis feedback <what should improve>")
        jarvis.close()
        return 2
    try:
        mem = jarvis.palace.store_episode(text, room="Feedback",
                                          importance=0.7)
        print(f"noted ({mem.id}): will surface in review.")
    except Exception as exc:
        print(f"feedback failed: {type(exc).__name__}")
        jarvis.close()
        return 1
    jarvis.close()
    return 0


def _setup_action(jarvis: Any, args: Any) -> int:
    """Guided first-run checklist. Read-only; exit 1 when any required
    check fails so scripts can gate on it."""
    _ = args
    home = str(jarvis.config.paths.home)
    rows: list[tuple[str, bool, str]] = []

    def _add(name: str, ok: bool, detail: str) -> None:
        rows.append((name, ok, detail))

    try:
        from pathlib import Path as _Path
        home_ok = _Path(home).exists()
        _add("home", home_ok, home)
    except Exception:
        _add("home", False, home)
    try:
        from .core.service import check_dependencies
        deps = check_dependencies(jarvis.config)
        bad = [c.name for c in deps if c.required and not c.ok]
        _add("dependencies", not bad,
             "ok" if not bad else f"missing: {', '.join(bad)}")
    except Exception as exc:
        _add("dependencies", False, f"{type(exc).__name__}")
    try:
        from .voice.setup import verify_reference
        ref = verify_reference(jarvis.config.voice.reference_audio)
        _add("voice reference", bool(ref.get("ok")),
             str(ref.get("detail", ref.get("path", "?")))[:120])
    except Exception as exc:
        _add("voice reference", False, f"{type(exc).__name__}")
    try:
        from .durable import TaskStore
        store = TaskStore(home)
        _add("task store", not store.corrupt,
             "ready" if not store.corrupt else store.corrupt)
    except Exception as exc:
        _add("task store", False, f"{type(exc).__name__}")
    failed = [name for name, ok, _ in rows if not ok]
    print("SETUP")
    for name, ok, detail in rows:
        print(f"[{'ok ' if ok else 'FAIL'}] {name}: {detail}")
    if failed:
        print("fix the FAIL rows above, then re-run `jarvis setup`.")
    else:
        print("next: `jarvis serve` + `jarvis board --open`, or "
              "`jarvis task create <goal>`.")
    jarvis.close()
    return 0 if not failed else 1


def _task_policy_ok(jarvis: Any) -> bool:
    try:
        check = getattr(getattr(jarvis, "policy", None),
                        "emergency_stop_engaged", None)
        if callable(check):
            return not bool(check())
    except Exception:
        pass
    return True


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    known = set(parser._subparsers._group_actions[0].choices.keys())
    head = list(raw)
    home = ""
    if len(head) >= 2 and head[0] == "--home":
        home = head[1]
        head = head[2:]
    if head and head[0] not in known and not head[0].startswith("-"):
        return _conductor_oneshot(raw, home=home)
    args = parser.parse_args(argv)
    if not args.command:
        # Bare `jarvis` drops into the chat: there is no wrong way to
        # start talking to him. --help still prints help (argparse).
        raw_home = list(sys.argv[1:] if argv is None else argv)
        args = parser.parse_args(["repl"])
        if "--home" in raw_home:
            try:
                args.home = raw_home[raw_home.index("--home") + 1]
            except (ValueError, IndexError):
                pass
    if not args.command:
        parser.print_help()
        return 2

    jarvis = _make_jarvis(getattr(args, "home", ""))

    if args.command == "talk":
        result = jarvis.cycle_once(" ".join(args.text))
        print(result.response)
        jarvis.close()
        return 0

    if args.command == "repl":
        from .conductor.service import ConductorService
        from .conversation import ConversationManager
        manager = ConversationManager()
        service = ConductorService(jarvis)
        session_id = ""
        try:
            snap = jarvis.status()
            nagents = len((snap.get("agents", {}) or {}).get(
                "agents", [])) if isinstance(
                snap.get("agents"), dict) else "?"
            print(f"jarvis live · cycle {snap.get('cycle', '?')} · "
                  f"{nagents} agents · {snap.get('events', '?')} events")
        except Exception:
            print("jarvis live.")
        print("commands: /reset (new topic) /summary (what I retain) /quit")
        try:
            while True:
                try:
                    line = input("you> ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    break
                if not line:
                    continue
                if line.lower() in ("exit", "quit", "/quit"):
                    break
                if line == "/reset":
                    if session_id:
                        manager.reset(session_id)
                    session_id = ""
                    print("jarvis> fresh session started.")
                    continue
                if line == "/summary":
                    session = manager.get(session_id) if session_id else None
                    print("jarvis>", session.summary or "(nothing retained yet)"
                          if session else "(no session yet)")
                    continue
                session = manager.get_or_create(session_id)
                session_id = session.session_id
                recent = [t.input for t in session.turns[-3:]]
                out = service.handle(
                    line, session_id=session_id,
                    session_context=" | ".join(recent))
                session.add(line, out.get("response", ""),
                            out.get("target", ""))
                spoken = ""
                if getattr(args, "speak", False) and out.get("response"):
                    try:
                        from .voice.speak import VoiceSpeaker
                        cfg = jarvis.config.voice.__dict__
                        said = VoiceSpeaker(config=cfg).say(
                            out["response"][:2000],
                            workdir=str(jarvis.config.paths.home))
                        spoken = " [spoken]" if said.get(
                            "spoken_aloud") else " [voice unavailable]"
                    except Exception:
                        spoken = " [voice unavailable]"
                print("jarvis>", (out.get("response") or
                      f"error: {out.get('error', 'unknown')}") + spoken)
        finally:
            jarvis.close()
        return 0

    if args.command == "board":
        url = f"http://{args.host}:{args.port}/board"
        print(f"status board: {url}")
        print("served by `jarvis serve` (same host/port/token). "
              "read-only, localhost by default.")
        if bool(getattr(args, "open", False)):
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception as exc:
                print(f"could not open browser: {type(exc).__name__}")
                jarvis.close()
                return 1
        jarvis.close()
        return 0

    if args.command == "remote":
        url = f"http://{args.host}:{args.port}/remote"
        print(f"remote: {url}")
        print("same token as `serve`. LAN use only on networks you trust: "
              "`serve --host <lan-ip>` (default stays localhost).")
        if bool(getattr(args, "open", False)):
            try:
                import webbrowser
                webbrowser.open(url)
            except Exception as exc:
                print(f"could not open browser: {type(exc).__name__}")
                jarvis.close()
                return 1
        jarvis.close()
        return 0

    if args.command == "serve":
        from .api.server import JarvisAPI
        api = JarvisAPI(jarvis, host=args.host, port=args.port, token=args.token)
        api.serve_forever()
        print(f"jarvis api on http://{args.host}:{api.port} (Ctrl-C to stop)")
        try:
            import time
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            api.shutdown()
            jarvis.close()
        return 0

    if args.command == "gods-eye":
        from .geospatial.application import GodsEyeApplication
        app = GodsEyeApplication(home=jarvis.config.paths.home)
        try:
            if args.action == "install":
                result = app.install()
            elif args.action == "start":
                result = app.start()
            elif args.action == "stop":
                result = app.stop()
            elif args.action == "open":
                result = {"url": app.open()}
            elif args.action == "live-sync":
                result = jarvis.live_eye.sync(
                    args.provider or None, allow_remote=args.allow_remote)
            elif args.action == "live-query":
                result = {"records": jarvis.live_eye.query(
                    args.lat, args.lon, radius_km=args.radius_km,
                    kind=args.kind, limit=args.limit)}
            elif args.action == "live-status":
                result = jarvis.live_eye.status()
            elif args.action == "live-promote":
                if not args.key:
                    raise RuntimeError("live-promote needs --key <observation-key>")
                result = jarvis.live_eye.promote(args.key, approved=args.approve)
            elif args.action == "live-doctor":
                result = {"checks": jarvis.live_eye.doctor()}
            else:
                result = app.status()
            print(json.dumps(result, indent=2, default=str))
            return 0
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            print(f"God's Eye View: {exc}")
            return 1
        finally:
            jarvis.close()

    if args.command == "status":
        print(json.dumps(jarvis.status(), indent=2, default=str))
        jarvis.close()
        return 0

    if args.command == "status-summary":
        snap = jarvis.status()
        agents = snap.get("agents", {})
        if isinstance(agents, dict) and isinstance(
                agents.get("agents"), list):
            agent_line = ", ".join(
                f"{a.get('name', '?')}:{a.get('state', '?')}"
                for a in agents["agents"][:8])
        else:
            agent_line = str(agents)[:120]
        lines = ["STATUS",
                 f"cycle: {snap.get('cycle', '?')}",
                 f"agents: {agent_line or '—'}",
                 f"memory: {snap.get('memory', '?')}",
                 f"events: {snap.get('events', '?')}",
                 f"policy conflicts: {snap.get('policy_conflicts', '?')}",
                 f"tasks: {snap.get('tasks', '?')}"]
        print("\n".join(str(line)[:200] for line in lines))
        jarvis.close()
        return 0

    if args.command == "agents":
        from .agents.contract import role_cards
        from .agents.orchestrator import TEAMS
        orch = jarvis.orchestrator
        if args.action == "list":
            for card in role_cards():
                print(f"{card.role_id:15} executor={card.executor or '-':10} "
                      f"model={card.model_requirements:9} "
                      f"{','.join(card.skills) or 'reasoning-only'}")
        elif args.action == "teams":
            for name, stages in TEAMS.items():
                print(f"{name}: {' → '.join(r for r, _ in stages)}")
        elif args.action == "status":
            info = {
                "roles": len(role_cards()),
                "executors": [a.name for a in
                              jarvis.supervisor.registry.list_agents()],
                "budgets": orch.budgets.to_dict(),
                "traced_tasks": len(orch.traces),
                "runs": len(orch.runs),
                "recent_runs": orch.recent_runs(5),
            }
            if args.json:
                print(json.dumps(info, indent=2, default=str))
                jarvis.close()
                return 0
            print(json.dumps(info, indent=2) if args.json else
                  f"roles: {info['roles']}  executors: {len(info['executors'])}  "
                  f"runs this session: {info['runs']}\n"
                  + "\n".join(f"  {r['status']:9} {r['goal'][:60]} "
                              f"({r['duration_ms']}ms)"
                              for r in info["recent_runs"])
                  or "  (no runs yet)")
        elif args.action in ("run", "explain"):
            goal = " ".join(args.text)
            if not goal and not args.task:
                print("usage: jarvis agents run <goal> [--team T] [--depth N]")
                jarvis.close()
                return 2
            if args.action == "explain" and args.task and not goal:
                # Cross-session: fall back to persisted traces on disk.
                if args.task not in orch.traces and orch.load_trace(args.task) is None:
                    print(f"no trace for task {args.task}")
                else:
                    print(orch.explain(args.task))
            else:
                out = orch.run(goal, team=args.team or None, depth=args.depth)
                if args.json:
                    print(json.dumps({
                        "task_id": out["task_id"], "run_id": out.get("run_id", ""),
                        "ok": out["ok"], "failure": out.get("failure", ""),
                        "result": out["result"],
                        "conflicts": out["conflicts"],
                        "state": out["state"]}, indent=2, default=str))
                else:
                    print(json.dumps(out["result"], indent=2, default=str))
                    print("--- trace ---")
                    print(orch.explain(out["task_id"]))
        elif args.action == "world":
            reg = jarvis.world_registry
            parts = list(args.text)
            sub = parts[0].lower() if parts else "entities"
            rest = parts[1:]
            as_json = args.json
            if sub == "entities":
                payload = {"entities": [
                    {"id": e.id, "type": e.type, "name": e.name,
                     "confidence": e.confidence, "version": e.version}
                    for e in sorted(reg.entities.values(),
                                    key=lambda x: x.name)[:50]]}
            elif sub == "get" and rest:
                entity = reg.get_entity(rest[0])
                payload = entity.to_dict() if entity is not None else {
                    "status": "unknown",
                    "note": f"never observed: {rest[0]}"}
            elif sub == "relations" and rest:
                if reg.get_entity(rest[0]) is None:
                    payload = {"status": "unknown",
                               "note": f"never observed: {rest[0]}"}
                else:
                    payload = {"relations": [
                        r.to_dict() for r in reg.get_relationships(rest[0])]}
            elif sub == "history" and rest:
                payload = {"history": reg.get_history(rest[0])}
            elif sub == "conflicts":
                payload = {"conflicts": reg.find_conflicts(rest[0] if rest else "")}
            elif sub == "uncertain":
                payload = {"uncertain": [
                    {"id": e.id, "name": e.name, "confidence": e.confidence}
                    for e in reg.find_uncertain()]}
            elif sub == "changes":
                payload = {"changes": reg.changes_since(0.0)[-20:]}
            else:
                print("usage: agents world "
                      "entities|get <id>|relations <id>|history <id>|"
                      "conflicts|uncertain|changes [--json]")
                jarvis.close()
                return 2
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            elif sub == "entities":
                for entry in payload["entities"]:
                    print(f"{entry['id']:40} {entry['type']:12} "
                          f"conf={entry['confidence']}")
                if not payload["entities"]:
                    print("(no entities observed yet)")
            else:
                print(json.dumps(payload, indent=2, default=str))
        jarvis.close()
        return 0

    if args.command == "proof":
        return _proof_action(jarvis, args)

    if args.command == "feedback":
        return _feedback_action(jarvis, args)

    if args.command == "setup":
        return _setup_action(jarvis, args)

    if args.command == "task":
        return _task_action(jarvis, args)

    if args.command == "security":
        return _security_action(jarvis, args)

    if args.command == "dots":
        from .dots.manager import DotManager
        from .dots.runtime import DotRuntime, RuntimeContext
        manager = jarvis.dots
        action = args.action
        as_json = args.json

        def _out(payload: Any, text: str) -> int:
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(text)
            jarvis.close()
            return 0

        if action == "list":
            dots = manager.list()
            payload = {"dots": [d.to_dict() for d in dots]}
            text = "\n".join(
                f"{d.dot_id[:13]:15} {d.name:24} {d.status.value:12} "
                f"progress={d.progress:.0%}" for d in dots) or "(no dots yet)"
            return _out(payload, text)
        if action == "create":
            text = " ".join(args.text).strip()
            if not text or "|" not in text:
                print('usage: jarvis dots create "Name | goal text" '
                      "[--role R] [--priority N] [--workspace PATH] "
                      "[--tools a,b] [--updates t1,t2]")
                jarvis.close()
                return 2
            name, _, goal = text.partition("|")
            workspace = {"root": args.workspace} if args.workspace else {}
            dot = manager.create(
                name=name.strip(), goal=goal.strip(), role=args.role,
                priority=args.priority, workspace=workspace,
                tools=[t.strip() for t in args.tools.split(",") if t.strip()],
                trigger_subscriptions=[
                    u.strip() for u in args.updates.split(",") if u.strip()])
            return _out({"dot": dot.to_dict()},
                        f"created {dot.dot_id} ({dot.status.value})")
        if action == "status" and not args.text:
            dots = manager.list()
            by_status: dict[str, int] = {}
            for dot in dots:
                by_status[dot.status.value] = by_status.get(dot.status.value, 0) + 1
            payload = {"dots": len(dots), "by_status": by_status,
                       "pending_activations": len(manager._pending)}
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(f"dots: {len(dots)}  "
                      + " ".join(f"{status}={count}"
                                 for status, count in sorted(by_status.items()))
                      or "(no dots yet)")
                if not dots:
                    print("(no dots yet)")
            jarvis.close()
            return 0
        if action in ("inspect", "status", "explain"):
            dot_id = " ".join(args.text).strip()
            info = manager.inspect(dot_id) if dot_id else None
            if info is None:
                print(f"unknown dot: {dot_id or '(none given)'}")
                jarvis.close()
                return 2
            if action == "explain":
                lines = [
                    f"dot {info['dot_id']} ({info['name']}): "
                    f"{info['status']}, progress={info['progress']:.0%}",
                    f"  goal: {info['goal'][:120]}",
                    f"  tasks: {info['task_ids']}",
                    f"  failures: {info['failures'][-3:] if info['failures'] else []}",
                    f"  checkpoint: "
                    f"{(info['checkpoint'] or {}).get('checkpoint_id', 'none')}",
                    f"  traces: {info['trace_refs'][-3:] if info['trace_refs'] else []}",
                ]
                return _out(info, "\n".join(lines))
            return _out(info, json.dumps(info, indent=2, default=str))
        if action in ("start", "pause", "resume", "stop"):
            dot_id = " ".join(args.text).strip()
            if not dot_id:
                print(f"usage: jarvis dots {action} <dot-id>")
                jarvis.close()
                return 2
            try:
                if action == "pause":
                    dot = manager.pause(dot_id)
                else:
                    dot = getattr(manager, action)(
                        dot_id, reason=f"cli {action}")
            except (KeyError, ValueError, Exception) as exc:
                print(f"cannot {action} {dot_id}: {exc}")
                jarvis.close()
                return 1
            return _out({"dot": dot.to_dict()},
                        f"{dot.dot_id}: {dot.status.value}")
        if action == "wake":
            # Event-driven activation: match text against subscriptions,
            # then run ONE bounded activation for each matched Dot.
            event = {"type": "manual", "entity": "", "summary": " ".join(args.text)}
            matched = manager.route_event(event)
            if not matched:
                return _out({"matched": [], "activations": []},
                            "(no subscribed dots matched)")
            runtime = DotRuntime(manager)
            ctx = RuntimeContext(
                orchestrator=jarvis.orchestrator, tasks=jarvis.tasks,
                palace=jarvis.palace,
                world_registry=jarvis.world_registry, policy=jarvis.policy)
            results = []
            for dot_id in matched:
                dot = manager.get(dot_id)
                if dot is None:
                    continue
                for fingerprint in manager.pending(dot_id):
                    manager.consume_pending(dot_id, fingerprint)
                result = runtime.activate(
                    dot, reason=f"cli wake: {event['summary'][:80]}",
                    ctx=ctx, event=event)
                results.append(result.to_dict())
            manager.persist()
            text = "\n".join(
                f"{r['dot_id'][:13]} → {r['outcome']}: {r['reason'][:100]}"
                for r in results) or "(no activations ran)"
            return _out({"matched": matched, "activations": results}, text)
        if action == "schedule":
            parts = list(args.text)
            sub = parts[0].lower() if parts else "list"
            rest = parts[1:]
            if sub == "list":
                scheds = manager.list_schedules(
                    rest[0] if rest else "")
                payload = {"schedules": [s.to_dict() for s in scheds]}
                text = "\n".join(
                    f"{s.schedule_id[:13]:15} {s.kind:10} "
                    f"dot={s.dot_id[:13]:15} "
                    f"{'on' if s.enabled else 'off':4} "
                    f"next={s.next_run or '-'} runs={s.activations}"
                    for s in scheds) or "(no schedules yet)"
                return _out(payload, text)
            if sub == "create":
                import json as _json
                if len(rest) < 2:
                    print("usage: jarvis dots schedule create <dot-id> "
                          "<kind> --config '{...}' [--tz TZ] "
                          "[--reason R] [--cooldown S]")
                    jarvis.close()
                    return 2
                try:
                    config = _json.loads(args.config or "{}")
                except ValueError as exc:
                    print(f"bad --config JSON: {exc}")
                    jarvis.close()
                    return 2
                try:
                    sched = manager.create_schedule(
                        rest[0], rest[1], config=config,
                        timezone=args.tz, reason=args.reason,
                        cooldown_s=args.cooldown)
                except (KeyError, ValueError) as exc:
                    print(f"cannot create schedule: {exc}")
                    jarvis.close()
                    return 1
                return _out({"schedule": sched.to_dict()},
                            f"created {sched.schedule_id} "
                            f"next={sched.next_run or '(event-driven)'}")
            if sub in ("inspect", "enable", "disable", "delete"):
                if not rest:
                    print(f"usage: jarvis dots schedule {sub} <schedule-id>")
                    jarvis.close()
                    return 2
                sid = rest[0]
                try:
                    if sub == "inspect":
                        sched = manager.get_schedule(sid)
                        if sched is None:
                            print(f"unknown schedule: {sid}")
                            jarvis.close()
                            return 2
                        return _out({"schedule": sched.to_dict()},
                                    json.dumps(sched.to_dict(), indent=2,
                                               default=str))
                    if sub == "enable":
                        sched = manager.enable_schedule(sid)
                    elif sub == "disable":
                        sched = manager.disable_schedule(sid)
                    else:
                        if not manager.delete_schedule(sid):
                            print(f"unknown schedule: {sid}")
                            jarvis.close()
                            return 2
                        return _out({"deleted": sid}, f"deleted {sid}")
                except KeyError as exc:
                    print(f"unknown schedule: {exc}")
                    jarvis.close()
                    return 2
                return _out({"schedule": sched.to_dict()},
                            f"{sid}: enabled={sched.enabled}")
            if sub == "wake":
                if not rest:
                    print("usage: jarvis dots schedule wake <dot-id>")
                    jarvis.close()
                    return 2
                dot = manager.get(rest[0])
                if dot is None:
                    print(f"unknown dot: {rest[0]}")
                    jarvis.close()
                    return 2
                from .dots.runtime import DotRuntime, RuntimeContext
                from .dots import wake as wake_mod
                report = wake_mod.fire_dot(
                    manager, jarvis.proactive, dot,
                    args.reason or "manual schedule wake",
                    DotRuntime(manager),
                    RuntimeContext(
                        orchestrator=jarvis.orchestrator,
                        tasks=jarvis.tasks, palace=jarvis.palace,
                        world_registry=jarvis.world_registry,
                        policy=jarvis.policy),
                    policy=jarvis.policy)
                return _out(report, json.dumps(report, indent=2,
                                               default=str))
            print("usage: jarvis dots schedule "
                  "list|create|inspect|enable|disable|delete|wake [--json]")
            jarvis.close()
            return 2
        if action == "tick":
            # On-demand schedule evaluation. No threads, no daemons:
            # whoever invokes tick (human, cron, service loop) drives it.
            from .dots import wake as wake_mod
            from .dots.runtime import DotRuntime, RuntimeContext
            ctx = RuntimeContext(
                orchestrator=jarvis.orchestrator, tasks=jarvis.tasks,
                palace=jarvis.palace,
                world_registry=jarvis.world_registry, policy=jarvis.policy)
            reports = wake_mod.poll_schedules(
                manager, jarvis.triggers, jarvis.proactive,
                policy=jarvis.policy, bus=jarvis.bus,
                activate=lambda dot, reason, event: DotRuntime(
                    manager).activate(dot, reason, ctx, event=event))
            payload = {"wakes": reports}
            fired = [r for r in reports if r.get("status") == "activated"]
            text = (f"{len(fired)} activation(s), "
                    f"{len(reports)} schedule(s) checked" if reports
                    else "(no schedules configured)")
            return _out(payload, text)
        if action == "notify":
            notes = jarvis.proactive.notifications
            payload = {"notifications": notes[-20:]}
            if as_json:
                return _out(payload, json.dumps(payload, indent=2,
                                                 default=str))
            lines = [f"{n.get('text', '')[:100]} [{n.get('level', '')}]"
                     for n in notes[-20:]] or ["(no notifications)"]
            return _out(payload, "\n".join(lines))
        print('usage: jarvis dots '
              'list|create|inspect|start|pause|resume|stop|status|explain|wake|'
              'schedule|tick|notify')
        jarvis.close()
        return 2

    if args.command == "missions":
        from .missions.runtime import MissionContext, MissionRuntime
        manager = jarvis.missions
        action = args.action
        as_json = args.json

        def _out(payload: Any, text: str) -> int:
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(text)
            jarvis.close()
            return 0

        def _ctx() -> MissionContext:
            return MissionContext(
                orchestrator=jarvis.orchestrator, tasks=jarvis.tasks,
                dots=jarvis.dots, palace=jarvis.palace,
                world_registry=jarvis.world_registry,
                policy=jarvis.policy)

        if action == "list":
            missions = manager.list()
            payload = {"missions": [m.to_dict() for m in missions]}
            text = "\n".join(
                f"{m.mission_id[:13]:15} {m.name:28} {m.status.value:12} "
                f"progress={m.progress:.0%}" for m in missions) \
                or "(no missions yet)"
            return _out(payload, text)
        if action == "create":
            text = " ".join(args.text).strip()
            if not text or "|" not in text:
                print('usage: jarvis missions create "Name | goal text"')
                jarvis.close()
                return 2
            name, _, goal = text.partition("|")
            mission = manager.create(name=name.strip(), goal=goal.strip(),
                                     priority=args.priority)
            return _out({"mission": mission.to_dict()},
                        f"created {mission.mission_id} ({mission.status.value})")
        if action == "status" and not args.text:
            missions = manager.list()
            by_status: dict[str, int] = {}
            for mission in missions:
                by_status[mission.status.value] = \
                    by_status.get(mission.status.value, 0) + 1
            payload = {"missions": len(missions), "by_status": by_status}
            if as_json:
                return _out(payload, json.dumps(payload, indent=2))
            print(f"missions: {len(missions)}  "
                  + " ".join(f"{s}={c}" for s, c in sorted(by_status.items()))
                  or "(no missions yet)")
            if not missions:
                print("(no missions yet)")
            jarvis.close()
            return 0
        if action in ("inspect", "status", "explain"):
            mid = " ".join(args.text).strip()
            info = manager.inspect(mid) if mid else None
            if info is None:
                print(f"unknown mission: {mid or '(none given)'}")
                jarvis.close()
                return 2
            if action == "explain":
                lines = [
                    f"mission {info['mission_id']} ({info['name']}): "
                    f"{info['status']}, progress={info['progress']:.0%}",
                    f"  goal: {info['goal'][:120]}",
                    f"  active objective: "
                    f"{info['active_objective'][:13] or 'none'}",
                    f"  ready: {info['ready_objectives']}",
                    f"  blocked_by: {info['blocked_by']}",
                    f"  uncertainty: {info['uncertainty'][-3:] if info['uncertainty'] else []}",
                    f"  evidence: {len(info['evidence_refs'])} refs",
                    f"  checkpoints: {len(info['checkpoint_refs'])}",
                ]
                return _out(info, "\n".join(lines))
            return _out(info, json.dumps(info, indent=2, default=str))
        if action in ("start", "pause", "resume", "stop", "cancel",
                      "recover"):
            mid = " ".join(args.text).strip()
            if not mid:
                print(f"usage: jarvis missions {action} <mission-id>")
                jarvis.close()
                return 2
            try:
                if action == "recover":
                    mission = manager.recover(mid, reason=args.reason)
                else:
                    mission = getattr(manager, action)(
                        mid, **({"reason": args.reason}
                                if action in ("stop", "cancel", "resume")
                                else {}))
            except (KeyError, ValueError, Exception) as exc:
                print(f"cannot {action} {mid}: {exc}")
                jarvis.close()
                return 1
            return _out({"mission": mission.to_dict()},
                        f"{mission.mission_id}: {mission.status.value}")
        if action == "objectives":
            parts = list(args.text)
            sub = parts[0].lower() if parts else "list"
            rest = parts[1:]
            if sub == "add" and rest:
                import json as _json
                mid = rest[0]
                spec = " ".join(rest[1:])
                if "|" not in spec:
                    print("usage: jarvis missions objectives add "
                          "<mission-id> \"Name | description\" "
                          "[--depends id1,id2] [--weight N] [--dot ID] "
                          "[--criteria JSON]")
                    jarvis.close()
                    return 2
                name, _, desc = spec.partition("|")
                try:
                    criteria = _json.loads(args.criteria or "[]")
                except ValueError as exc:
                    print(f"bad --criteria JSON: {exc}")
                    jarvis.close()
                    return 2
                try:
                    obj = manager.add_objective(
                        mid, name=name.strip(), description=desc.strip(),
                        depends_on=[d.strip() for d in args.depends.split(",")
                                    if d.strip()],
                        weight=args.weight, dot_id=args.dot,
                        success_criteria=criteria)
                except (KeyError, ValueError) as exc:
                    print(f"cannot add objective: {exc}")
                    jarvis.close()
                    return 1
                return _out({"objective": obj.to_dict()},
                            f"added {obj.objective_id}")
            mid = rest[0] if (sub == "list" and rest) else ""
            if sub not in ("list", "add"):
                mid = parts[0]  # bare: `objectives <mission-id>`
            mission = manager.get(mid) if mid else None
            if mission is None:
                print(f"usage: jarvis missions objectives "
                      f"[list <mission-id>|add ...]; unknown mission: {mid}")
                jarvis.close()
                return 2
            payload = {"objectives": [o.to_dict() for o in
                                      mission.objectives.values()]}
            text = "\n".join(
                f"{o.objective_id[:13]:15} {o.name:28} {o.status.value:10} "
                f"w={o.weight:g} deps={len(o.depends_on)}" for o in
                mission.objectives.values()) or "(no objectives yet)"
            return _out(payload, text)
        if action == "verify":
            mid = " ".join(args.text).strip()
            mission = manager.get(mid) if mid else None
            if mission is None:
                print(f"unknown mission: {mid or '(none given)'}")
                jarvis.close()
                return 2
            from .missions.verification import verify_all
            from .missions.runtime import _VerifyContext, MissionContext as MC
            report = verify_all(mission.success_criteria,
                                _VerifyContext(MC(
                                    orchestrator=jarvis.orchestrator,
                                    tasks=jarvis.tasks, dots=jarvis.dots,
                                    palace=jarvis.palace,
                                    world_registry=jarvis.world_registry,
                                    policy=jarvis.policy), mission))
            return _out(report, f"verdict: {report['verdict']}\n" + "\n".join(
                f"  {r['kind']}: {r['verdict']} — {r['detail'][:100]}"
                for r in report["results"]) or "  (no criteria)")
        if action == "checkpoint":
            mid = " ".join(args.text).strip()
            mission = manager.get(mid) if mid else None
            if mission is None:
                print(f"unknown mission: {mid or '(none given)'}")
                jarvis.close()
                return 2
            checkpoints = mission.metadata.get("checkpoints", [])
            payload = {"checkpoints": checkpoints}
            if as_json:
                return _out(payload, json.dumps(payload, indent=2,
                                                 default=str))
            lines = [f"{c.get('checkpoint_id', '?')[:18]:20} "
                     f"{c.get('verdict', ''):10} {c.get('note', '')[:60]}"
                     for c in checkpoints] or ["(no checkpoints yet)"]
            return _out(payload, "\n".join(lines))
        if action == "advance":
            mid = " ".join(args.text).strip()
            if not mid:
                print("usage: jarvis missions advance <mission-id>")
                jarvis.close()
                return 2
            from .missions.runtime import MissionContext as MC
            from .missions.runtime import MissionRuntime
            runtime = MissionRuntime(manager)
            try:
                report = runtime.advance(mid, MC(
                    orchestrator=jarvis.orchestrator, tasks=jarvis.tasks,
                    dots=jarvis.dots, palace=jarvis.palace,
                    world_registry=jarvis.world_registry,
                    policy=jarvis.policy))
            except (KeyError, ValueError, Exception) as exc:
                print(f"cannot advance {mid}: {exc}")
                jarvis.close()
                return 1
            return _out(report.to_dict(),
                        f"{report.outcome}: {report.reason[:160]}")
        if action == "proposals":
            from .missions import detectors as _detectors
            parts = list(args.text)
            sub = parts[0].lower() if parts else "list"
            rest = parts[1:]
            if sub == "list":
                items = manager.list_proposals(
                    rest[0] if rest and rest[0] in (
                        "draft", "proposed", "approved", "rejected",
                        "ignored", "expired", "converted", "cancelled")
                    else "")
                payload = {"proposals": [p.to_dict() for p in items]}
                text = "\n".join(
                    f"{p.proposal_id[:13]:15} {p.status.value:10} "
                    f"score={p.score:.2f} {p.title[:60]}" for p in items) \
                    or "(no proposals yet)"
                return _out(payload, text)
            if sub == "scan":
                found = _detectors.scan_all(
                    manager, palace=jarvis.palace, tasks=jarvis.tasks,
                    tools=jarvis.tools, tracker=jarvis.state)
                payload = {"proposals": [p.to_dict() for p in found]}
                text = "\n".join(
                    f"{p.proposal_id[:13]:15} score={p.score:.2f} "
                    f"{p.title[:60]}" for p in found) or "(nothing detected)"
                return _out(payload, text)
            if sub in ("inspect", "explain", "approve", "reject", "ignore"):
                if not rest:
                    print(f"usage: jarvis missions proposals {sub} <proposal-id>")
                    jarvis.close()
                    return 2
                pid = rest[0]
                try:
                    if sub == "inspect":
                        proposal = manager.get_proposal(pid)
                        if proposal is None:
                            print(f"unknown proposal: {pid}")
                            jarvis.close()
                            return 2
                        return _out(
                            {"proposal": proposal.to_dict()},
                            json.dumps(proposal.to_dict(), indent=2,
                                       default=str))
                    if sub == "explain":
                        proposal = manager.get_proposal(pid)
                        if proposal is None:
                            print(f"unknown proposal: {pid}")
                            jarvis.close()
                            return 2
                        lines = [
                            f"proposal {proposal.proposal_id} "
                            f"({proposal.status.value}, score={proposal.score:.2f})",
                            f"  why: {proposal.reason[:200]}",
                            f"  evidence: {len(proposal.evidence_refs)} refs",
                            f"  confidence={proposal.confidence:.2f} "
                            f"uncertainty: {proposal.uncertainty[:3]}",
                            f"  factors: {proposal.score_factors}",
                            f"  would create: "
                            f"{len(proposal.suggested_objectives)} objectives",
                            f"  expires: "
                            f"{proposal.expires_at or 'never'}",
                        ]
                        return _out({"proposal": proposal.to_dict()},
                                    "\n".join(lines))
                    if sub == "approve":
                        proposal = manager.approve_proposal(pid)
                    elif sub == "reject":
                        proposal = manager.reject_proposal(
                            pid, reason=args.reason)
                    else:
                        proposal = manager.ignore_proposal(pid)
                except (KeyError, ValueError, Exception) as exc:
                    print(f"cannot {sub} {pid}: {exc}")
                    jarvis.close()
                    return 1
                return _out({"proposal": proposal.to_dict()},
                            f"{pid}: {proposal.status.value}")
            if sub == "convert":
                if not rest:
                    print("usage: jarvis missions proposals convert "
                          "<proposal-id>")
                    jarvis.close()
                    return 2
                try:
                    mission = manager.convert_proposal(rest[0])
                except (KeyError, ValueError, Exception) as exc:
                    print(f"cannot convert: {exc}")
                    jarvis.close()
                    return 1
                return _out({"mission": mission.to_dict()},
                            f"converted → mission {mission.mission_id}")
            print("usage: jarvis missions proposals "
                  "list|scan|inspect|explain|approve|reject|ignore|convert "
                  "[--json]")
            jarvis.close()
            return 2
        if action == "control":
            from .missions.hud import HudContext, build_snapshot
            snapshot = build_snapshot(HudContext(
                missions=manager, dots=jarvis.dots, tasks=jarvis.tasks,
                notifier=getattr(jarvis, "notifier", None),
                policy=jarvis.policy,
                system_state=jarvis.world.system_state
                if hasattr(jarvis.world, "system_state") else None,
                emergency_engaged=lambda: jarvis.policy._emergency_stop()
                if hasattr(jarvis.policy, "_emergency_stop") else False,
                proposals=manager))
            if as_json:
                print(json.dumps(snapshot, indent=2, default=str))
            else:
                missions = snapshot["missions"]
                print(f"missions: {len(missions)}  "
                      f"dots: {len(snapshot['dots'])}  "
                      f"blockers: {len(snapshot['blockers'])}  "
                      f"approvals: {len(snapshot['approvals'])}  "
                      f"emergency_stop={snapshot['emergency_stop']}")
                for row in missions[:10]:
                    print(f"  {row['mission_id'][:13]:15} {row['name'][:30]:30} "
                          f"{row['status']:12} {row['progress']:.0%}")
                for blocker in snapshot["blockers"][:5]:
                    print(f"  ! blocked: {blocker.get('reason', '')[:80]}")
            jarvis.close()
            return 0
        print("usage: jarvis missions list|create|inspect|start|pause|resume|"
              "stop|cancel|status|explain|objectives|verify|checkpoint|"
              "recover|advance|proposals|control [--json]")
        jarvis.close()
        return 2

    if args.command == "proactive":
        engine = jarvis.proactive
        action = args.action
        as_json = args.json
        if action == "scan":
            found = jarvis.poll_proactive()
            payload = {"candidates": found, "count": len(found)}
            print(json.dumps(payload, indent=2) if as_json else
                  (f"{len(found)} candidate(s): " + ", ".join(found)
                   if found else "(no candidates)"))
        elif action == "candidates":
            pending = [c.to_dict() for c in engine.candidates.values()
                       if c.status == "pending"]
            if as_json:
                print(json.dumps({"candidates": pending}, indent=2,
                                 default=str))
            elif not pending:
                print("(no pending candidates)")
            else:
                for cand in pending:
                    print(f"{cand['candidate_id']} [{cand['level']}] "
                          f"{cand['type']} {cand['entity'] or ''}".rstrip()
                          + f" score={cand['score']:.2f}")
        elif action == "explain":
            cid = " ".join(args.text).strip()
            if not cid:
                print("usage: proactive explain <candidate-id> [--json]")
                jarvis.close()
                return 2
            if as_json:
                cand = engine.candidates.get(cid)
                decision = engine.decisions.get(cid)
                print(json.dumps({
                    "candidate": cand.to_dict() if cand else None,
                    "decision": decision.to_dict() if decision else None,
                }, indent=2, default=str))
            else:
                print(engine.explain(cid))
        else:  # status
            info = engine.status()
            print(json.dumps(info, indent=2) if as_json else
                  f"candidates: {info['candidates']}  "
                  f"pending: {info['pending']}  decided: {info['decided']}  "
                  f"notifications: {info['notifications']}")
        jarvis.close()
        return 0

    if args.command == "mentalist":
        text = " ".join(args.text)
        mode = jarvis.mentalist
        mode.observe(text, kind="text", source="cli")
        mode.hypothesize([f"interpretation A: {text[:60]}",
                          f"interpretation B (alternative): {text[:60]}"])
        print(mode.render())
        jarvis.close()
        return 0

    if args.command == "remember":
        mem = jarvis.palace.store_fact(" ".join(args.text), room=args.room,
                                       source="cli", importance=0.8)
        print(f"stored in {mem.room}: {mem.id}")
        jarvis.close()
        return 0

    if args.command == "consolidate":
        from .memory.consolidation import MemoryConsolidator
        report = MemoryConsolidator(jarvis.palace, jarvis.config).run()
        print(json.dumps(report.to_dict(), indent=2, default=str))
        jarvis.close()
        return 0

    if args.command == "see":
        from .vision.observer import VisionObserver
        observer = VisionObserver()
        if args.source == "camera":
            obs = observer.see_camera(question=args.ask, scene=not args.fast)
        elif args.source == "file":
            if not args.path:
                print("see file needs --path <image>")
                jarvis.close()
                return 2
            obs = observer.see_file(args.path, question=args.ask,
                                    scene=not args.fast)
        else:
            obs = observer.see_screen(question=args.ask, scene=not args.fast)
        if not obs.ok:
            print("see failed: " + obs.error)
            jarvis.close()
            return 1
        fed = observer.feed(obs, world=jarvis.world, palace=jarvis.palace,
                            mentalist=jarvis.mentalist)
        print(obs.summary())
        print("remembered as: " + str(fed.get("memory_id", "?")))
        jarvis.close()
        return 0

    if args.command in ("start", "stop", "restart", "doctor"):
        from .core.service import ServiceManager, check_dependencies
        manager = ServiceManager(jarvis.config)
        jarvis.close()
        if args.command == "start":
            print(json.dumps(manager.start(), indent=2, default=str))
            return 0
        if args.command == "stop":
            print(json.dumps(manager.stop(), indent=2, default=str))
            return 0
        if args.command == "restart":
            print(json.dumps(manager.restart(), indent=2, default=str))
            return 0
        checks = check_dependencies(jarvis.config)
        bad = [c.name for c in checks if not c.ok]
        for check in checks:
            mark = "ok " if check.ok else "FAIL"
            req = " (required)" if check.required else ""
            print(f"[{mark}] {check.name}: {check.detail}{req}")
        return 0 if not [c for c in checks if c.required and not c.ok] else 1

    if args.command == "benchmark":
        from .bench import run
        print(json.dumps(run(jarvis, samples=args.samples), indent=2, default=str))
        jarvis.close()
        return 0

    if args.command == "devices":
        from .computer.computer import ComputerController
        from .models.ollama import OllamaClient
        from .vision.observer import VisionObserver
        from .voice.runtime import VoiceLoop
        snapshot = {
            "voice": VoiceLoop().status(),
            "vision": VisionObserver().status(),
            "computer": ComputerController().status(),
            "models": OllamaClient().health(),
            "memory": jarvis.palace.stats(),
        }
        print(json.dumps(snapshot, indent=2, default=str))
        jarvis.close()
        return 0

    if args.command == "integration":
        return _integration_action(jarvis, args)

    if args.command == "intelligence":
        from .intelligence import wiring as intel_wiring
        from .intelligence.cognitive import CognitiveSupervisor
        from .intelligence.sensory import event_from_user
        from .inference.reasoning import MetaReasoner
        network, encoder, decoder = intel_wiring.default_neural_stack()
        loop = intel_wiring.build_loop(
            registry=jarvis.world_registry, spatial=jarvis.spatial,
            palace=jarvis.palace, network=network, encoder=encoder,
            decoder=decoder, reasoner=MetaReasoner(),
            policy=jarvis.policy, tools=jarvis.tools)
        home = str(jarvis.config.paths.home)
        supervisor = CognitiveSupervisor(loop, home=home)
        as_json = args.json

        def _intel_out(payload: Any, text: str) -> int:
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(text)
            jarvis.close()
            return 0

        if args.action == "cycle":
            text = " ".join(args.text) if args.text else "status check"
            outcome = supervisor.process(event_from_user(text))
            payload = outcome.to_dict()
            return _intel_out(payload,
                              f"cycle {outcome.cycle_id}: "
                              f"state={outcome.state.value} "
                              f"action={outcome.action.action or '-'} "
                              f"policy={outcome.policy_allowed}")
        if args.action == "inspect":
            if not args.cycle:
                print("usage: jarvis intelligence inspect --cycle <id>")
                jarvis.close()
                return 2
            found = supervisor.inspect(args.cycle)
            if found is None:
                print(f"unknown cycle {args.cycle}")
                jarvis.close()
                return 1
            stages = found.get("stages", [])
            summary = [(s.get("stage"), s.get("ok")) for s in stages
                       if isinstance(s, dict)]
            return _intel_out(found,
                              f"{found.get('cycle_id')} "
                              f"ok={found.get('ok', found.get('state'))} "
                              f"stages={summary}")
        if args.action == "replay":
            if not args.cycle:
                print("usage: jarvis intelligence replay --cycle <id>")
                jarvis.close()
                return 2
            try:
                outcome = supervisor.replay(args.cycle)
            except ValueError as exc:
                print(f"device: {exc}")
                jarvis.close()
                return 1
            payload = outcome.to_dict()
            return _intel_out(payload,
                              f"replay {outcome.cycle_id}: "
                              f"state={outcome.state.value} "
                              f"replayed={outcome.replayed}")
        if args.action == "events":
            found = supervisor.store.read(limit=20)
            rows = [(c.get("cycle_id", "")[:16],
                     (c.get("event") or {}).get("type", "?"),
                     c.get("state", "?")) for c in found]
            return _intel_out({"cycles": found},
                              "\n".join(
                                  f"{cid:18} {typ:16} {state}"
                                  for cid, typ, state in rows)
                              or "no cognitive cycles recorded")
        if args.action == "failures":
            found = supervisor.failures(limit=20)
            rows = [(c.get("cycle_id", "")[:16],
                     str([s.get("stage") for s in c.get("stages", [])
                          if isinstance(s, dict)
                          and not s.get("ok", True)]))
                    for c in found]
            return _intel_out({"failures": found},
                              "\n".join(
                                  f"{cid:18} failed={stages}"
                                  for cid, stages in rows)
                              or "no cognitive failures recorded")
        if args.action in ("perception-status", "perception-observe",
                           "perception-events", "perception-inspect"):
            return _intel_perception(jarvis, args, _intel_out)
        if args.action in ("experience", "beliefs", "learning"):
            return _intel_adaptive(jarvis, args, _intel_out)
        if args.action in ("hypotheses", "goals", "skills", "scorecard",
                           "benchmark", "explain"):
            return _intel_expansion(jarvis, args, _intel_out)
        payload = {"loop": loop.status(),
                   "subsystems": {
                       "world": jarvis.world_registry.stats()
                       if hasattr(jarvis.world_registry, "stats") else {},
                       "memory": jarvis.palace.stats(),
                       "policy": {"audit": len(jarvis.policy.audit)},
                   }}
        return _intel_out(payload, json.dumps(payload, indent=2, default=str))

    if args.command == "neural":
        from .neural.scale import SparseLIFNetwork
        from .neural.topology import FLY_166K_SCHEMA, SyntheticGenerator
        as_json = args.json

        def _neural_out(payload: Any, text: str) -> int:
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(text)
            jarvis.close()
            return 0

        if args.action == "benchmark":
            import random
            import time
            n = max(16, min(args.neurons, 166000))
            net = SparseLIFNetwork(n)
            rng = random.Random(41)
            edges = min(n * 10, 200000)
            for _ in range(edges):
                net.stage_edge(rng.randrange(n), rng.randrange(n),
                               rng.uniform(0.1, 0.9), rng.randrange(3))
            t0 = time.perf_counter()
            net.compile()
            gen_ms = (time.perf_counter() - t0) * 1000.0
            t0 = time.perf_counter()
            spikes = 0
            for _ in range(5):
                spikes += len(net.step({0: 2.0}))
            step_ms = (time.perf_counter() - t0) * 1000.0 / 5.0
            payload = {"neurons": n, "edges": net.edge_count,
                       "compile_ms": round(gen_ms, 1),
                       "step_ms": round(step_ms, 2), "spikes": spikes}
            return _neural_out(payload,
                               f"neural: {n} neurons, {net.edge_count} edges, "
                               f"step {step_ms:.2f} ms")
        if args.action == "snapshot":
            import random
            n = max(4, min(args.neurons, 5000))
            net = SparseLIFNetwork(n)
            rng = random.Random(7)
            for _ in range(n * 2):
                net.stage_edge(rng.randrange(n), rng.randrange(n), 0.8, 0)
            net.compile()
            net.step({0: 2.0})
            payload = net.snapshot()
            payload = {"time": payload["time"], "size": payload["size"],
                       "edge_count": payload["edge_count"],
                       "total_spikes": payload["total_spikes"]}
            return _neural_out(payload, json.dumps(payload, indent=2, default=str))
        payload = {"substrate": "sparse-lif-csr",
                   "fly_schema_neurons": FLY_166K_SCHEMA.total_neurons(),
                   "fly_schema_origin": FLY_166K_SCHEMA.origin,
                   "populations": len(FLY_166K_SCHEMA.populations),
                   "synthetic_generator": "seeded, deterministic"}
        return _neural_out(payload, json.dumps(payload, indent=2, default=str))

    if args.command == "device-fabric":
        fabric = jarvis.device_fabric
        as_json = args.json

        def _out(payload: Any, text: str) -> int:
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(text)
            jarvis.close()
            return 0

        try:
            if args.action == "status":
                info = fabric.status()
                return _out(info, f"devices: {info['devices']}  "
                                 f"transports: {info['transports_available']}  "
                                 f"policy: {'bound' if info['policy_bound'] else 'UNBOUND'}")
            if args.action == "list":
                rows = fabric.list_devices()
                return _out(rows, "\n".join(
                    f"{r['device_id']:22} {r['name'][:24]:24} "
                    f"{r['lifecycle']:13} {r['trust']:11} {r['connectivity']}"
                    for r in rows) or "(no devices enrolled)")
            if args.action == "info":
                if not args.device:
                    print("usage: jarvis device-fabric info --device <id>")
                    jarvis.close()
                    return 2
                info = fabric.info(args.device)
                return _out(info, fabric.describe(args.device))
            if args.action == "register":
                if not args.name:
                    print("usage: jarvis device-fabric register --name <n> [--type T]")
                    jarvis.close()
                    return 2
                info = fabric.register_device(args.name, args.type, by=args.by)
                return _out(info, f"registered {info['name']} "
                                  f"({info['device_id']}) trust={info['trust']}")
            if args.action == "enroll-local":
                info = fabric.register_local(name=args.name, by=args.by)
                return _out(info, f"local node {info['name']} "
                                  f"({info['device_id']}) online={info['connectivity']}")
            if args.action == "discover":
                if not args.name:
                    print("usage: jarvis device-fabric discover --name <n>")
                    jarvis.close()
                    return 2
                info = fabric.discover_device(args.name, args.type, by=args.by)
                return _out(info, f"sighted {info['name']} ({info['device_id']})")
            if args.action == "unregister":
                if not args.device:
                    print("usage: jarvis device-fabric unregister --device <id>")
                    jarvis.close()
                    return 2
                ok = fabric.unregister_device(args.device, by=args.by)
                return _out({"ok": ok}, "unregistered" if ok else "unknown device")
            if args.action in ("trust", "distrust", "revoke", "quarantine",
                               "release", "enable", "disable"):
                if not args.device:
                    print(f"usage: jarvis device-fabric {args.action} --device <id> "
                          f"[--reason R]")
                    jarvis.close()
                    return 2
                method = getattr(fabric, f"{args.action}_device")
                info = method(args.device, by=args.by, reason=args.reason) \
                    if args.action not in ("release", "enable") \
                    else method(args.device, by=args.by)
                return _out(info, f"{args.device}: lifecycle={info['lifecycle']} "
                                  f"trust={info['trust']}")
            if args.action == "capabilities":
                if not args.device or not args.capability:
                    print("usage: jarvis device-fabric capabilities --device <id> "
                          "--capability a.b,c.d")
                    jarvis.close()
                    return 2
                caps = [{"name": c.strip(), "version": 1}
                        for c in args.capability.split(",") if c.strip()]
                info = fabric.declare_capabilities(args.device, caps, by=args.by)
                return _out(info, f"{args.device}: "
                                  f"{sorted(info['capabilities'])}")
            if args.action == "heartbeat":
                if not args.device:
                    print("usage: jarvis device-fabric heartbeat --device <id>")
                    jarvis.close()
                    return 2
                info = fabric.heartbeat(args.device)
                return _out(info, f"{args.device}: {info['connectivity']}")
            if args.action == "sweep":
                changed = fabric.sweep()
                return _out({"offline": changed},
                            f"{len(changed)} node(s) timed out: {changed}")
            if args.action == "locate":
                if not args.device:
                    print("usage: jarvis device-fabric locate --device <id> "
                          "[--room R]  (empty room clears to UNKNOWN)")
                    jarvis.close()
                    return 2
                info = fabric.set_location(args.device, args.room, by=args.by)
                return _out(info, f"{args.device}: "
                                  f"location={info['location'] or 'UNKNOWN'}")
            if args.action == "command":
                if not args.device or not args.capability:
                    print("usage: jarvis device-fabric command --device <id> "
                          "--capability a.b [--args '{...}'] [--approve TOKEN]")
                    jarvis.close()
                    return 2
                try:
                    cmd_args = json.loads(args.args) if args.args else {}
                except json.JSONDecodeError as exc:
                    print(f"bad --args JSON: {exc}")
                    jarvis.close()
                    return 2
                result = fabric.route_command("cli", args.device,
                                              args.capability, cmd_args,
                                              approval_token=args.approve)
                return _out(result, result.get("error", str(result.get("result", ""))))
            # doctor
            result = {"checks": fabric.doctor()}
            return _out(result, "\n".join(
                f"{c['name']:28} {'ok' if c['ok'] else 'FAIL'}  {c['detail']}"
                for c in result["checks"]))
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"device-fabric: {exc}")
            jarvis.close()
            return 1

    if args.command == "device":
        from .device.android import AndroidNodeAdapter
        adapter = AndroidNodeAdapter(jarvis.device_fabric)
        as_json = args.json

        def _out(payload: Any, text: str) -> int:
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(text)
            jarvis.close()
            return 0

        if args.area in ("grants", "approvals", "commands", "policy"):
            from .device.service import DeviceCommandService
            svc = DeviceCommandService(adapter)
            return _device_area_collection(svc, adapter, jarvis, args, _out)

        if args.area in ("audit", "outbox"):
            # Bare aliases: `device audit` == `device android audit`, etc.
            args.action = args.area
            args.area = "android"

        if args.area == "transport":
            from .device.android_transport import (
                AndroidSocketHost,
                read_host_status,
            )
            try:
                if args.action == "status":
                    result = read_host_status(jarvis.device_fabric.home)
                    state = ("live" if result.get("live")
                             else "not running")
                    detail = (f"port={result.get('port')} "
                              f"pid={result.get('pid')} "
                              f"peers={result.get('peers', [])}"
                              if result.get("live")
                              else result.get("detail", "no host running"))
                    return _out(result, f"transport {state}: {detail}")
                if args.action == "peers":
                    result = read_host_status(jarvis.device_fabric.home)
                    peers = (result.get("peers", [])
                             if result.get("live") else [])
                    return _out({"peers": peers},
                                "\n".join(peers) or "no peers connected")
                if args.action == "approve":
                    if not args.device:
                        print("usage: jarvis device transport approve "
                              "--device <id> [--reason R]")
                        jarvis.close()
                        return 2
                    result = adapter.trust_android(args.device, by=args.by,
                                                   reason=args.reason)
                    return _out(result,
                                f"approved {result['name']} "
                                f"trust={result['trust']}")
                if args.action == "serve":
                    host = AndroidSocketHost(
                        adapter, host=args.host, port=args.port)
                    port = host.start()
                    print(f"serving android transport on port {port} "
                          f"(Ctrl-C to stop)")
                    try:
                        import time
                        from .device.service import DeviceCommandService
                        svc = DeviceCommandService(adapter, host=host)
                        tick_at = 0.0
                        while True:
                            time.sleep(1.0)
                            # Drain the durable outbox while serving so
                            # CLI-enqueued commands reach live lanes.
                            # Best-effort and throttled; never kills serve.
                            try:
                                if time.monotonic() >= tick_at:
                                    svc.tick()
                                    tick_at = time.monotonic() + 10.0
                            except Exception:
                                pass
                    except KeyboardInterrupt:
                        pass
                    finally:
                        host.stop()
                    jarvis.close()
                    return 0
                print("usage: jarvis device transport "
                      "{status|serve|peers|approve}")
                jarvis.close()
                return 2
            except (OSError, RuntimeError, ValueError) as exc:
                print(f"device transport: {exc}")
                jarvis.close()
                return 1

        try:
            if args.action == "status":
                if args.device:
                    result = adapter.status(args.device)
                    return _out(result,
                                f"{result['name']} pair={result['pairing_state']} "
                                f"connected={result['connected']} "
                                f"queued={result['queue']['queued']}")
                result = {"nodes": adapter.list_android()}
                return _out(result, "\n".join(
                    f"{r['device_id'][:12]:14} {r['name']:20} "
                    f"{r['pairing_state']:12} "
                    f"{'online' if r['connected'] else 'offline'}"
                    for r in result["nodes"]) or "no android nodes")
            if args.action == "list":
                result = {"nodes": adapter.list_android()}
                return _out(result, "\n".join(
                    f"{r['device_id'][:12]:14} {r['name']:20} "
                    f"lifecycle={r['lifecycle']} trust={r['trust']}"
                    for r in result["nodes"]) or "no android nodes")
            if args.action == "info":
                if not args.device:
                    print("usage: jarvis device android info --device <id>")
                    jarvis.close()
                    return 2
                result = adapter.status(args.device)
                return _out(result,
                            f"{result['name']} ({result['device_type']}) "
                            f"lifecycle={result['lifecycle']} "
                            f"trust={result['trust']} "
                            f"pair={result['pairing_state']} "
                            f"connected={result['connected']}")
            if args.action == "register":
                if not (args.name and args.model and args.android_version
                        and args.app_version):
                    print("usage: jarvis device android register --name N "
                          "--model M --android-version V --app-version A "
                          "[--owner O]")
                    jarvis.close()
                    return 2
                result = adapter.register_android(
                    args.name,
                    {"device_model": args.model,
                     "android_version": args.android_version,
                     "app_version": args.app_version},
                    by=args.by, owner=args.owner)
                return _out(result,
                            f"registered {result['device_id']} "
                            f"pairing code {result['pairing']['pairing_code']} "
                            f"(expires in {result['pairing']['expires_in_s']:.0f}s)")
            if args.action == "pair":
                if not (args.device and args.code):
                    print("usage: jarvis device android pair --device <id> "
                          "--code 123456 [--node <node-id>] [--reason R]")
                    jarvis.close()
                    return 2
                result = adapter.pair(args.device, args.code, by=args.by,
                                      reason=args.reason, node_id=args.node)
                return _out(result,
                            f"paired {result['name']} "
                            f"trust={result['trust']}")
            if args.action == "trust":
                if not args.device:
                    print("usage: jarvis device android trust --device <id> "
                          "[--reason R]")
                    jarvis.close()
                    return 2
                result = adapter.trust_android(args.device, by=args.by,
                                               reason=args.reason)
                return _out(result,
                            f"trusted {result['name']} "
                            f"trust={result['trust']}")
            if args.action == "revoke":
                if not args.device:
                    print("usage: jarvis device android revoke --device <id> "
                          "[--capability a.b] [--reason R]")
                    jarvis.close()
                    return 2
                if args.capability:
                    # Grant-level revoke (4.2 durable authorization).
                    from .device.service import DeviceCommandService
                    svc = DeviceCommandService(adapter)
                    result = svc.grants.revoke(args.device, args.capability,
                                              by=args.by, reason=args.reason)
                    return _out(result,
                                f"revoked {len(result['revoked'])} grant(s) "
                                f"for {args.device} {args.capability}")
                result = adapter.revoke_android(args.device, by=args.by,
                                                 reason=args.reason)
                return _out(result, f"revoked {result['name']}")
            if args.action == "unpair":
                if not args.device:
                    print("usage: jarvis device android unpair --device <id> "
                          "[--reason R]")
                    jarvis.close()
                    return 2
                ok = adapter.unpair(args.device, by=args.by)
                return _out({"device_id": args.device, "unpaired": ok},
                            f"unpaired {args.device}" if ok
                            else f"unknown device {args.device}")
            if args.action == "capabilities":
                if not args.device:
                    print("usage: jarvis device android capabilities "
                          "--device <id> [--capability a.b,c]")
                    jarvis.close()
                    return 2
                if args.capability:
                    declared = [c.strip() for c in args.capability.split(",")
                                if c.strip()]
                    result = adapter.declare_android_capabilities(
                        args.device, declared, by=args.by)
                    return _out(result,
                                f"granted={result['granted']} "
                                f"withheld={len(result['withheld'])}")
                result = adapter.status(args.device)
                return _out({"capabilities": result["capabilities"]},
                            ", ".join(sorted(result["capabilities"]))
                            or "no capabilities")
            if args.action == "permissions":
                if not (args.device and args.report):
                    print("usage: jarvis device android permissions "
                          "--device <id> --report '{...}'")
                    jarvis.close()
                    return 2
                try:
                    report = json.loads(args.report)
                except json.JSONDecodeError as exc:
                    print(f"bad --report JSON: {exc}")
                    jarvis.close()
                    return 2
                result = adapter.report_permissions(args.device, report,
                                                    by=args.by)
                return _out(result,
                            f"granted={result['granted']} "
                            f"withheld={len(result['withheld'])}")
            if args.action == "command":
                if not (args.device and args.node_command):
                    print("usage: jarvis device android command --device <id> "
                          "--command device.vibrate [--args '{...}'] "
                          "[--approve TOKEN]")
                    jarvis.close()
                    return 2
                try:
                    cmd_args = json.loads(args.args) if args.args else {}
                except json.JSONDecodeError as exc:
                    print(f"bad --args JSON: {exc}")
                    jarvis.close()
                    return 2
                # Durable path (4.2): authorize, enqueue, drain, verify.
                from .device.service import DeviceCommandService
                svc = DeviceCommandService(adapter)
                result = svc.request_command("cli", args.device,
                                             args.node_command, cmd_args,
                                             approval_id=args.approve)
                if result.get("ok"):
                    return _out(result, str(result.get("result", ""))[:500])
                if result.get("requires_approval"):
                    return _out(result, _approval_next_steps(
                        str(result.get("approval_id", "")),
                        str(result.get("command_id", ""))))
                return _out(result, result.get("error", str(result.get(
                    "command_id", result))))
            if args.action == "connect":
                if not args.device:
                    print("usage: jarvis device android connect --device <id>")
                    jarvis.close()
                    return 2
                result = adapter.connect(args.device, by=args.by)
                return _out(result,
                            f"connected={result['connected']} "
                            f"drained={result['drained']}")
            if args.action == "disconnect":
                if not args.device:
                    print("usage: jarvis device android disconnect "
                          "--device <id>")
                    jarvis.close()
                    return 2
                result = adapter.disconnect(args.device, by=args.by)
                return _out(result,
                            f"connected={result['connected']}")
            if args.action in ("inspect", "grants", "grant", "suspend",
                               "restore", "approve", "deny", "command-status",
                               "cancel", "outbox", "audit"):
                from .device.service import DeviceCommandService
                svc = DeviceCommandService(adapter)
                return _device_service_action(svc, adapter, args,
                                              jarvis, _out)
            # queue
            if not args.device:
                print("usage: jarvis device android queue --device <id>")
                jarvis.close()
                return 2
            result = adapter.queue_depth(args.device)
            return _out(result, f"queued={result['queued']} "
                               f"dropped={result['dropped_while_offline']}")
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"device: {exc}")
            jarvis.close()
            return 1

    if args.command == "pi":
        from .device.pi_adapter import PiNodeAdapter
        adapter = PiNodeAdapter(jarvis.device_fabric)
        as_json = args.json

        def _pi_out(payload: Any, text: str) -> int:
            if as_json:
                print(json.dumps(payload, indent=2, default=str))
            else:
                print(text)
            jarvis.close()
            return 0

        try:
            return _pi_action(adapter, jarvis, args, _pi_out)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"pi: {exc}")
            jarvis.close()
            return 1

    if args.command == "say":
        from .voice.speak import speak_text
        from .voice.voice_profile import effective_style
        cfg = jarvis.config.voice.__dict__
        result = speak_text(" ".join(args.text), config=cfg,
                            style=effective_style(
                                str(jarvis.config.paths.home),
                                str(getattr(args, "style", "") or "")),
                            workdir=str(jarvis.config.paths.home))
        print(json.dumps(result, indent=2, default=str))
        jarvis.close()
        return 0 if result.get("ok") else 1

    if args.command == "listen":
        from .voice.runtime import VoiceLoop
        loop = VoiceLoop(always_listen=args.always,
                         jarvis_voice=args.voice,
                         voice_config=jarvis.config.voice.__dict__,
                         max_turns=args.max_turns)
        ready, missing = loop.check_ready()
        if not ready:
            print("voice not ready, missing: " + ", ".join(missing))
            jarvis.close()
            return 1
        if args.loop:
            import threading
            stop = threading.Event()
            try:
                summary = loop.run(jarvis, on_turn=lambda t: print(
                    f"heard: {t.get('heard', '?')}\njarvis: {t.get('response', t)}"),
                    stop=stop)
            except KeyboardInterrupt:
                summary = {"ok": True, "turns": -1, "note": "interrupted"}
            print(json.dumps(summary, indent=2, default=str))
            jarvis.close()
            return 0
        if args.no_speak:
            heard = loop.listen_once(addressed=not args.always)
            if not heard.get("ok"):
                print("no turn: " + str(heard.get("error", heard)))
                jarvis.close()
                return 1
            result = jarvis.cycle_once(heard["text"], source="voice")
            print(f"heard: {heard['text']}\njarvis: {result.response}")
            jarvis.close()
            return 0
        turn = loop.converse_once(jarvis, addressed=not args.always)
        if not turn.get("ok"):
            print("no turn: " + str(turn.get("error", turn)))
            jarvis.close()
            return 1
        print(f"heard: {turn['heard']}")
        jarvis.close()
        return 0

    if args.command == "audio":
        return _audio_action(jarvis, args)

    if args.command == "voice":
        return _voice_action(jarvis, args)

    if args.command == "voice-test":
        from types import SimpleNamespace
        return _voice_action(jarvis, SimpleNamespace(
            action="test", path="", text="Good evening. How can I "
            "assist you?", no_play=True, json=args.json))

    if args.command == "world":
        return _world_action(jarvis, args)

    if args.command == "grants":
        return _grants_action(jarvis, args)

    if args.command == "backup":
        return _backup_action(jarvis, args)

    if args.command == "approvals":
        return _approvals_action(jarvis, args)

    if args.command == "autonomy":
        return _autonomy_action(jarvis, args)

    if args.command == "service":
        return _service_action(jarvis, args)

    parser.print_help()
    jarvis.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
