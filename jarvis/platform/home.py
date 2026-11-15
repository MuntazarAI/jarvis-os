"""The Command Centre — the home page of the platform.

The look is the reference design the user chose, used as it is: the
dark command room, the seven agents at their desks around the glowing
core, the mission panel, the task queue and the system meters.

The one difference: **every number is real**. It is this person's own
JARVIS — their missions, tasks, memory, events, tools and the machine
it runs on. Nothing on the page is invented.

`build_home()` gathers the snapshot; the page fetches it every five
seconds and fills itself in.
"""

from __future__ import annotations

import os
import shutil
import socket
import time
from pathlib import Path
from typing import Any

#: The seven agents in the command room, and what they are for.
ROLES: tuple[tuple[str, str, str, str], ...] = (
    ("Orion", "Supervisor", "Coordinates &amp; oversees", "cyan"),
    ("Nova", "Planner", "Breaks goals into steps", "violet"),
    ("Sage", "Researcher", "Finds &amp; verifies information", "green"),
    ("Kael", "Coder", "Writes &amp; builds code", "gold"),
    ("Zen", "Analyst", "Analyses &amp; finds insights", "orange"),
    ("Iris", "Security", "Monitors &amp; protects", "blue"),
    ("Pixel", "Computer", "Runs tools &amp; executes", "purple"),
)


def _safe(call: Any, fallback: Any = None) -> Any:
    """Never let one broken subsystem take the page down."""
    try:
        return call()
    except Exception:
        return fallback


def _uptime_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} day{'s' if days > 1 else ''}, {hours} hours"
    if hours:
        return f"{hours} hours, {minutes} min"
    return f"{minutes} minutes"


def _system_info() -> dict[str, Any]:
    """CPU, memory, disk, network, temperature, uptime — from /proc."""
    info: dict[str, Any] = {"cpu": 0, "memory": 0, "disk": 0,
                            "network": "—", "temperature": "—",
                            "uptime": "—"}
    try:
        load = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        info["cpu"] = min(99, int(round(load / cores * 100)))
    except (OSError, AttributeError):
        pass
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            values = {}
            for line in handle:
                key, _, rest = line.partition(":")
                values[key.strip()] = int(rest.strip().split()[0])
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        if total:
            info["memory"] = int(round((total - available) / total * 100))
    except (OSError, ValueError, IndexError):
        pass
    try:
        usage = shutil.disk_usage("/")
        info["disk"] = int(round(usage.used / max(usage.total, 1) * 100))
    except OSError:
        pass
    try:
        info["network"] = socket.gethostbyname(socket.gethostname())
    except OSError:
        pass
    try:
        with open("/proc/uptime", encoding="utf-8") as handle:
            info["uptime"] = _uptime_text(float(handle.read().split()[0]))
    except (OSError, ValueError, IndexError):
        pass
    try:
        for path in ("/sys/class/thermal/thermal_zone0/temp",
                     "/sys/class/hwmon/hwmon0/temp1_input"):
            with open(path, encoding="utf-8") as handle:
                raw = float(handle.read().strip())
            info["temperature"] = (f"{raw / 1000:.0f}°C" if raw > 200
                                   else f"{raw:.0f}°C")
            break
    except (OSError, ValueError):
        pass
    return info


def _tools_info(jarvis: Any) -> list[dict[str, Any]]:
    """What JARVIS can reach from here."""
    rows: list[dict[str, Any]] = []
    for name, detail, binary in (
            ("Ollama", "Local LLM", "ollama"),
            ("Docker", "Containers", "docker"),
            ("Brave", "Browser", "brave"),
            ("Tailscale", "Networking", "tailscale"),
            ("VS Code", "Development", "code")):
        rows.append({"name": name, "detail": detail,
                     "online": bool(shutil.which(binary))})
    try:
        from ..models.backends import (build_client, configured_backends,
                                       resolve_selection)
        cfg = getattr(jarvis, "config", None)
        selection = resolve_selection(cfg)
        chosen = str(selection.get("fast") or "")
        online = False
        for spec in configured_backends(cfg):
            client = build_client(spec, cfg)
            if client is None:
                continue
            try:
                online = bool(client.models())
            except Exception:
                online = False
            if online:
                break
        rows.append({"name": "Models", "detail": chosen.split(":")[-1][:28],
                      "online": online})
    except Exception:
        pass
    return rows


def _agents_info(jarvis: Any) -> list[dict[str, Any]]:
    """The seven roles and what they are doing right now."""
    states: dict[str, str] = {}
    tasks: dict[str, str] = {}
    status = _safe(lambda: jarvis.status(), {}) or {}
    agents = (status.get("agents") or {}).get("agents") or []
    for agent in agents:
        if isinstance(agent, dict):
            key = str(agent.get("name") or "").lower()
            states[key] = str(agent.get("state") or "idle")
            if agent.get("task"):
                tasks[key] = str(agent.get("task"))[:60]
    out: list[dict[str, Any]] = []
    for name, role, about, _colour in ROLES:
        key = name.lower()
        out.append({"name": name, "role": role, "about": about,
                    "state": states.get(key, "idle"),
                    "task": tasks.get(key, "")})
    return out


def _missions_info(jarvis: Any) -> dict[str, Any]:
    """The mission in front, with its steps."""
    missions = _safe(lambda: jarvis.missions.list(), []) or []
    if not missions:
        return {"title": "No mission yet", "description": "Ask JARVIS for "
                "something to do and it will show up here.", "progress": 0,
                "steps": [], "eta": "—", "priority": "—"}
    mission = missions[0]
    objectives = _safe(lambda: list(getattr(mission, "objectives", []) or []),
                       []) or []
    steps = []
    done = 0
    for objective in objectives[:5]:
        state = str(getattr(objective, "state", "") or "")
        label = str(getattr(objective, "title", "") or
                    getattr(objective, "description", "") or "")[:70]
        if state in ("done", "completed", "succeeded", "verified"):
            status = "done"
            done += 1
        elif state in ("active", "in_progress", "running"):
            status = "active"
        else:
            status = "pending"
        steps.append({"text": label, "state": status})
    progress = int(round(done / max(len(objectives), 1) * 100))
    return {"title": str(getattr(mission, "title", "") or "Mission")[:70],
            "description": str(getattr(mission, "summary", "") or
                               getattr(mission, "description", "") or "")[:220],
            "progress": progress, "steps": steps,
            "eta": "—", "priority": str(
                getattr(mission, "priority", "") or "Normal")}


def _tasks_info(jarvis: Any) -> list[dict[str, Any]]:
    """What is running right now."""
    store = _safe(lambda: jarvis.tasks, None)
    tasks = _safe(lambda: store.list(), []) or []
    out: list[dict[str, Any]] = []
    for task in tasks[:8]:
        steps = getattr(task, "steps", []) or []
        finished = sum(1 for s in steps
                       if str(getattr(getattr(s, "state", None), "value", "")
                              or s) == "succeeded")
        progress = int(round(finished / max(len(steps), 1) * 100))
        out.append({"title": str(getattr(task, "title", ""))[:60],
                    "role": str(getattr(task, "owner", "") or
                                getattr(task, "agent", "") or "JARVIS")[:20],
                    "progress": progress,
                    "state": str(getattr(getattr(task, "state", None),
                                         "value", "") or "")[:20]})
    return out


def _events_info(jarvis: Any) -> list[dict[str, Any]]:
    """Recent activity, newest first."""
    events = _safe(lambda: jarvis.events, None)
    types = _safe(lambda: events.types(), {}) or {}
    return [{"type": str(name), "count": int(count)}
            for name, count in sorted(types.items(),
                                      key=lambda kv: -kv[1])[:6]]


def build_home(jarvis: Any) -> dict[str, Any]:
    """The real snapshot behind the command room."""
    tasks = _tasks_info(jarvis)
    running = [t for t in tasks
               if t["state"] in ("running", "active", "in_progress")]
    queued = [t for t in tasks if t["state"] in ("queued", "pending")]
    agents = _agents_info(jarvis)
    active_agents = [a for a in agents
                      if a["state"] not in ("idle", "unknown", "")]
    service = _safe(lambda: jarvis.status(), {}) or {}
    return {
        "counts": {
            "agents_active": len(active_agents),
            "agents_total": len(agents),
            "tasks_running": len(running),
            "tasks_queued": len(queued),
        },
        "agents": agents,
        "mission": _missions_info(jarvis),
        "tasks": tasks,
        "events": _events_info(jarvis),
        "memory": _safe(lambda: jarvis.palace.stats(), {}) or {},
        "graph": _safe(lambda: jarvis.graph.stats(), {}) or {},
        "system": _system_info(),
        "tools": _tools_info(jarvis),
        "service": {"running": bool(service.get("running", True))},
        "generated_at": time.time(),
    }


def _here() -> Path:
    return Path(__file__).parent


def _read(name: str) -> str:
    try:
        return (_here() / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def build_home_page() -> str:
    """The finished page: the design, the real data hooks.

    The markup, the CSS and the script live in their own files, so the
    design can be changed without touching Python — and the page picks
    the change up on the next refresh.
    """
    markup = _read("home_markup.html")
    style = _read("home_style.css")
    script = _read("home_script.js")
    page = ("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS — AI Command Centre</title>
<style>
__STYLE__
</style>
</head>
<body>
__MARKUP__
<script>
__SCRIPT__
</script>
</body>
</html>
""")
    return (page.replace("__STYLE__", style)
            .replace("__MARKUP__", markup)
            .replace("__SCRIPT__", script))


__all__ = ["build_home", "build_home_page", "HOME_HTML", "ROLES"]
