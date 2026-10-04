"""Local status board (read-only Mission Control page).

One JSON snapshot (`build_board`) assembled ONLY from existing
subsystems — status, missions HUD, durable tasks, voice config,
service heartbeat, approvals, events — plus a single-file HTML page
(no CDN, no external fetches: works fully offline).

Rules: read-only (no POST route), defensive (any failing subsystem
contributes an explicit `unknown` marker, the snapshot never raises),
and secret-scrubbed (tokens/keys never enter the payload). The page
itself carries no authority: same token gate as the API, token kept
in sessionStorage, sent as a header, never in URLs.
"""

from __future__ import annotations

import time
from typing import Any

BOARD_VERSION = 1

_SECRET_HINTS = ("token", "secret", "password", "api_key", "apikey",
                 "authorization", "private_key")


def _safe(fn: Any, fallback: Any) -> Any:
    try:
        return fn()
    except Exception:
        return fallback


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = str(key).lower()
            if any(hint in name for hint in _SECRET_HINTS):
                out[key] = "[redacted]"
            else:
                out[key] = _scrub(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_scrub(item, depth + 1) for item in value[:50]]
    if isinstance(value, str) and len(value) > 500:
        return value[:500] + "…"
    return value


def _home(jarvis: Any) -> str:
    return str(_safe(lambda: jarvis.config.paths.home, "") or "")


def _service_info(home: str) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        from ..service.runtime import BackgroundService, read_pid_info
        info = read_pid_info(home) if home else {}
        heart = _safe(lambda: BackgroundService(home).read_heartbeat()
                      if home else {}, {})
        return {"running": bool(info.get("running")),
                "pid": info.get("pid"),
                "heartbeat_age_s": heart.get("age_s"),
                "heartbeat_state": heart.get("state", "unknown")}
    return _safe(_read, {"running": "unknown"})


def _presence_info(home: str) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        from ..autonomy.presence import PresenceRuntime
        return PresenceRuntime(home).health() if home else {}
    return _safe(_read, {"status": "unknown"})


def _durable_info(home: str) -> Any:
    def _read() -> list[dict[str, Any]]:
        from ..durable import TaskStore
        store = TaskStore(home) if home else None
        if store is None:
            return []
        if store.corrupt:
            return [{"status": "unknown",
                     "detail": f"store fail-closed: {store.corrupt}"}]
        rows = []
        for task in store.list():
            done = sum(1 for s in task.steps
                       if s.state.value == "succeeded")
            rows.append({"task_id": task.task_id,
                         "title": task.title[:120],
                         "state": task.state.value,
                         "progress": f"{done}/{len(task.steps)}"})
        return rows[-20:]
    return _safe(_read, {"status": "unknown"})


def _voice_info(jarvis: Any) -> dict[str, Any]:
    def _read() -> dict[str, Any]:
        cfg = jarvis.config.voice
        return {"provider": str(getattr(cfg, "tts_provider",
                                       "unknown"))[:40],
                "profile": str(getattr(cfg, "profile", ""))[:40],
                "style": str(getattr(cfg, "style", ""))[:40]}
    return _safe(_read, {"status": "unknown"})


def _missions_info(jarvis: Any) -> Any:
    def _read() -> Any:
        from ..missions.hud import HudContext, build_snapshot
        world = getattr(jarvis, "world", None)
        policy = getattr(jarvis, "policy", None)
        return build_snapshot(HudContext(
            missions=getattr(jarvis, "missions", None),
            dots=getattr(jarvis, "dots", None),
            tasks=getattr(jarvis, "tasks", None),
            notifier=getattr(jarvis, "notifier", None),
            policy=policy,
            system_state=_safe(
                lambda: world.system_state, None),
            emergency_engaged=_safe(
                lambda: bool(policy._emergency_stop()), False),
            proposals=getattr(jarvis, "missions", None)))
    return _safe(_read, {"status": "unknown"})


def _approvals(policy: Any) -> list[dict[str, Any]]:
    def _read() -> list[dict[str, Any]]:
        records = getattr(policy, "approvals", None)
        if not isinstance(records, dict):
            return []
        out = []
        for token, record in records.items():
            if not isinstance(record, dict):
                continue
            if record.get("status") != "pending":
                continue
            out.append({"action": str(record.get("action", ""))[:120],
                        "requested_at": record.get("requested_at", 0.0),
                        "token_hint": str(token)[:8] + "…"})
        return out[:10]
    return _safe(_read, [])


def build_board(jarvis: Any) -> dict[str, Any]:
    """Assemble the snapshot. Never raises; unknowns are explicit."""
    try:
        home = _home(jarvis)
        policy = getattr(jarvis, "policy", None)
        events = getattr(jarvis, "events", None)
        snapshot = {
            "board": BOARD_VERSION,
            "generated_at": time.time(),
            "service": _service_info(home),
            "presence": _presence_info(home),
            "system": _safe(lambda: jarvis.status(),
                            {"status": "unknown"}),
            "missions": _missions_info(jarvis),
            "durable": _durable_info(home),
            "voice": _voice_info(jarvis),
            "approvals": _approvals(policy),
            "events": _safe(lambda: {
                "count": events.count(),
                "types": events.types()}, {"status": "unknown"}),
            "policy": {
                "emergency": _safe(
                    lambda: bool(policy._emergency_stop()), "unknown"),
                "conflicts": _safe(lambda: policy.conflicts(),
                                   "unknown"),
            },
        }
        return _scrub(snapshot)
    except Exception as exc:
        return {"board": BOARD_VERSION, "status": "unknown",
                "error": f"{type(exc).__name__}"}


BOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS &mdash; Status Board</title>
<style>
:root { color-scheme: dark; --bg: #0b0e14; --card: #141925;
--line: #263049; --txt: #dbe4f5; --dim: #8b96ad; --ok: #3fd68f;
--warn: #e6b34d; --bad: #e5635e; --acc: #5eb1ef; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--txt);
font: 14px/1.45 system-ui, sans-serif; padding: 20px; }
header { display: flex; gap: 12px; align-items: baseline;
flex-wrap: wrap; margin-bottom: 16px; }
h1 { font-size: 20px; margin: 0; letter-spacing: 1px; }
#meta { color: var(--dim); font-size: 12px; }
#estop { display: none; background: #3a1414; border: 1px solid var(--bad);
color: #ffb3b0; padding: 8px 12px; border-radius: 8px; width: 100%; }
.grid { display: grid; grid-template-columns: repeat(auto-fill,
minmax(300px, 1fr)); gap: 12px; }
.card { background: var(--card); border: 1px solid var(--line);
border-radius: 10px; padding: 12px 14px; min-height: 120px; }
.card h2 { font-size: 12px; text-transform: uppercase;
letter-spacing: 1.5px; color: var(--dim); margin: 0 0 8px; }
.row { display: flex; justify-content: space-between; gap: 8px;
padding: 3px 0; border-top: 1px dotted #223; }
.row:first-of-type { border-top: 0; }
.k { color: var(--dim); } .v { text-align: right; word-break: break-word; }
.ok { color: var(--ok); } .warn { color: var(--warn); }
.bad { color: var(--bad); } .acc { color: var(--acc); }
#tick { font-size: 12px; color: var(--dim); max-height: 150px;
overflow: auto; } #tick div { padding: 2px 0;
border-top: 1px dotted #223; }
#gate { position: fixed; inset: 0; background: rgba(0,0,0,.7);
display: none; align-items: center; justify-content: center; }
#gate div { background: var(--card); padding: 24px; border-radius: 12px;
border: 1px solid var(--line); }
#gate input { width: 280px; padding: 8px; margin-right: 8px; }
button { padding: 8px 14px; cursor: pointer; }
</style>
</head>
<body>
<header><h1>JARVIS // STATUS BOARD</h1><span id="meta">…</span>
<div id="estop">EMERGENCY STOP ENGAGED — actions paused, read-only.</div>
</header>
<div class="grid" id="grid"></div>
<div class="card" style="margin-top:12px"><h2>live events</h2>
<div id="tick"><div>connecting…</div></div></div>
<div id="gate"><div><h2>API token</h2>
<p>This server requires a bearer token (see <code>jarvis serve
--token</code>). It stays in this tab only.</p>
<input id="tok" type="password" placeholder="token">
<button onclick="saveTok()">Unlock</button></div></div>
<script>
let token = sessionStorage.getItem("jarvis-token") || "";
function saveTok() { token = document.getElementById("tok").value;
sessionStorage.setItem("jarvis-token", token);
document.getElementById("gate").style.display = "none"; refresh(); }
function authz() { return token ? {"Authorization": "Bearer " + token} : {}; }
function esc(s) { return String(s).replace(/[&<>"]/g,
c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function pill(s) { s = String(s);
if (/^(ok|true|running|ready|completed|succeeded|verified)$/i.test(s))
return '<span class="ok">' + esc(s) + "</span>";
if (/^(fail|failed|error|false|unknown)$/i.test(s))
return '<span class="warn">' + esc(s) + "</span>";
return '<span class="v">' + esc(s) + "</span>"; }
function card(title, rows) { return '<div class="card"><h2>' + esc(title) +
"</h2>" + rows.map(r => '<div class="row"><span class="k">' + esc(r[0]) +
"</span><span>" + pill(r[1]) + "</span></div>").join("") + "</div>"; }
async function refresh() {
let r; try { r = await fetch("api/board", {headers: authz()}); }
catch (e) { document.getElementById("meta").textContent = "unreachable";
return; }
if (r.status === 401) { document.getElementById("gate").style.display =
"flex"; return; }
let b; try { b = await r.json(); } catch (e) { return; }
document.getElementById("meta").textContent = "updated " +
new Date(b.generated_at * 1000).toLocaleTimeString();
let es = b.policy && b.policy.emergency;
document.getElementById("estop").style.display = es === true ?
"block" : "none";
let g = [];
let s = b.service || {};
let svcRows = [["running", s.running], ["pid", s.pid ?? "—"],
["heartbeat", s.heartbeat_state ?? "?"]];
if (s.running !== true) svcRows.push(["hint",
"jarvis service start"]);
g.push(card("service", svcRows));
let sys = b.system || {};
let ag = sys.agents;
let agentRows = [];
if (ag && Array.isArray(ag.agents)) {
agentRows = ag.agents.slice(0, 8).map(a => [(a.name || "?"),
(a.state || "?") + " · done " + (a.tasks_done ?? 0)]);
if (ag.delegations !== undefined) agentRows.push(["delegations",
ag.delegations]);
} else {
agentRows = Object.entries(ag || sys).slice(0, 8).map(([k, v]) =>
[k, typeof v === "object" ? JSON.stringify(v).slice(0, 60) : v]);
}
g.push(card("agents / mesh", agentRows.length ? agentRows :
[["agents", "none"]]));
let m = b.missions || {};
g.push(card("missions", [["missions",
(m.missions || []).length], ["objectives",
(m.objectives || []).length], ["dots", (m.dots || []).length],
["blockers", (m.blockers || []).length]]));
let d = Array.isArray(b.durable) ? b.durable : [];
g.push(card("durable tasks", d.length ? d.slice(0, 6).map(t =>
[t.task_id, t.state + " " + (t.progress || "")]) : [["tasks", "none"]]));
let a = b.approvals || [];
g.push(card("approvals", a.length ? a.slice(0, 6).map(x =>
[x.action.slice(0, 40), x.token_hint]) : [["pending", "none"]]));
let v = b.voice || {};
g.push(card("voice", [["provider", v.provider ?? "?"],
["profile", v.profile ?? "—"], ["style", v.style ?? "—"]]));
let e = b.events || {};
g.push(card("events", [["count", e.count ?? "?"],
["types", e.types ? Object.keys(e.types).length : "?"]]));
let p = b.policy || {};
g.push(card("policy", [["conflicts", p.conflicts ?? "?"],
["emergency", p.emergency]]));
document.getElementById("grid").innerHTML = g.join("");
}
function live() {
let el = document.getElementById("tick");
function note(t) { el.innerHTML = "<div>" + esc(t) + "</div>"; }
function connect() {
let proto = location.protocol === "https:" ? "wss" : "ws";
let ws; try { ws = new WebSocket(proto + "://" + location.host +
location.pathname.replace(/board.*$/, "")); }
catch (e) { note("live feed unavailable — retrying…");
setTimeout(connect, 5000); return; }
ws.onopen = () => note("live — waiting for events…");
ws.onmessage = ev => { let m;
try { m = JSON.parse(ev.data); } catch (e) { return; }
if (el.children.length === 1 &&
/live|waiting|retrying/.test(el.textContent)) el.innerHTML = "";
let d = document.createElement("div");
d.textContent = (m.type || "?") + " #" + (m.seq ?? "?");
el.prepend(d); while (el.children.length > 30) el.lastChild.remove(); };
let retry = () => { note("live feed lost — retrying…");
try { ws.close(); } catch (e) {}
setTimeout(connect, 5000); };
ws.onerror = retry; ws.onclose = retry;
}
connect();
}
refresh(); setInterval(refresh, 5000); live();
</script>
</body>
</html>
"""


__all__ = ["build_board", "BOARD_HTML", "BOARD_VERSION"]
