"""JARVIS command line: talk, serve, status, mentalist, remember."""

from __future__ import annotations

import argparse
import json
import sys
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

    bench = sub.add_parser("benchmark", help="latency + resource benchmark")
    bench.add_argument("--samples", type=int, default=3)

    sub.add_parser("start", help="start the JARVIS service (API server, supervised)")
    sub.add_parser("stop", help="stop the JARVIS service")
    sub.add_parser("restart", help="restart the JARVIS service")
    sub.add_parser("doctor", help="dependency + hardware + model health checks")

    ag = sub.add_parser("agents", help="multi-agent organization")
    ag.add_argument("action", nargs="?", default="list",
                    choices=["list", "status", "run", "explain", "teams"])
    ag.add_argument("text", nargs="*", help="goal text for run")
    ag.add_argument("--team", default="",
                    help="team strategy: research/coding/debugging/computer/decision/daily")
    ag.add_argument("--depth", type=int, default=None,
                    help="adaptive depth 0-5 (default: auto)")
    ag.add_argument("--task", default="", help="task id for explain")
    ag.add_argument("--json", action="store_true",
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
