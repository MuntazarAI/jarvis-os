"""JARVIS command line: talk, serve, status, mentalist, remember."""

from __future__ import annotations

import argparse
import json
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

    sub.add_parser("repl", help="interactive prompt (Ctrl-D to quit)")

    serve = sub.add_parser("serve", help="start the HTTP + WebSocket API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--token", default="")

    sub.add_parser("status", help="print system status JSON")

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
                              "commands", "policy"])
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

    bench = sub.add_parser("benchmark", help="latency + resource benchmark")
    bench.add_argument("--samples", type=int, default=3)

    intel = sub.add_parser("intelligence", help="unified cognitive loop")
    intel.add_argument("action", nargs="?", default="status",
                       choices=["status", "cycle"])
    intel.add_argument("text", nargs="*", help="input text for cycle")
    intel.add_argument("--json", action="store_true",
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

    pro = sub.add_parser("proactive", help="proactive attention + decisions")
    pro.add_argument("action", nargs="?", default="status",
                     choices=["status", "candidates", "explain", "scan"])
    pro.add_argument("text", nargs="*", help="candidate id for explain")
    pro.add_argument("--json", action="store_true",
                     help="machine-readable output")

    say = sub.add_parser("say", help="speak text aloud via TTS")
    say.add_argument("text", nargs="+")

    listen = sub.add_parser("listen", help="voice turn: mic → STT → think → speak")
    listen.add_argument("--always", action="store_true",
                        help="respond even without the wake word")
    listen.add_argument("--loop", action="store_true",
                        help="keep conversing until Ctrl-C")
    listen.add_argument("--no-speak", action="store_true",
                        help="print the reply instead of speaking it")
    return parser


def _make_jarvis(home: str) -> Jarvis:
    config = JarvisConfig()
    if home:
        config.paths.home = Path(home)
    return Jarvis(config=config)


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
            print("usage: jarvis device approvals show --approval <token>")
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
            print("usage: jarvis device approvals approve --approval <token>")
            jarvis.close()
            return 2
        ok = svc.approve_command(args.approval, by=args.by)
        return _out({"approval_id": args.approval, "approved": ok},
                    f"approved {args.approval[:12]}" if ok
                    else f"cannot approve {args.approval[:12]}")
    if action == "deny":
        if not args.approval:
            print("usage: jarvis device approvals deny --approval <token> "
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
            print("usage: jarvis device approvals revoke --approval <token> "
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
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
        from .conversation import ConversationManager
        manager = ConversationManager()
        session_id = ""
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
                turn = manager.turn(jarvis, session_id, line)
                session_id = turn["session"]
                print("jarvis>", turn["response"])
        finally:
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

    if args.command == "intelligence":
        from .intelligence import wiring as intel_wiring
        from .intelligence.sensory import event_from_user
        from .inference.reasoning import MetaReasoner
        network, encoder, decoder = intel_wiring.default_neural_stack()
        loop = intel_wiring.build_loop(
            registry=jarvis.world_registry, spatial=jarvis.spatial,
            palace=jarvis.palace, network=network, encoder=encoder,
            decoder=decoder, reasoner=MetaReasoner(),
            policy=jarvis.policy, tools=jarvis.tools)
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
            loop.start()
            record = loop.cycle_once(event_from_user(text))
            payload = record.to_dict()
            return _intel_out(payload,
                              f"cycle {record.cycle_id}: ok={record.ok} "
                              f"action={record.action_taken or '-'} "
                              f"policy={record.policy_allowed}")
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
                    return _out(result,
                                f"needs approval {result.get('approval_id')} "
                                f"(command {result.get('command_id')})")
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

    if args.command == "say":
        from .voice.runtime import Speaker
        result = Speaker().say(" ".join(args.text))
        print(json.dumps(result, indent=2, default=str))
        jarvis.close()
        return 0 if result.get("ok") else 1

    if args.command == "listen":
        from .voice.runtime import VoiceLoop
        loop = VoiceLoop(always_listen=args.always)
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

    parser.print_help()
    jarvis.close()
    return 2


if __name__ == "__main__":
    sys.exit(main())
