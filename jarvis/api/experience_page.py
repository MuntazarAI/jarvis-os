"""Experience command-center page (Experience Layer 1.0).

Single offline file: no CDN, no fetches beyond this server. Every
pixel comes from `/api/experience` (existing subsystems only) or the
live event socket. Actions POST to gated endpoints that reuse the
existing runner/policy authorities — the page holds no authority of
its own and never echoes secrets (approval tokens are pasted, never
rendered).
"""

from __future__ import annotations

EXPERIENCE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS &mdash; Experience</title>
<style>
:root { color-scheme: dark; --bg: #0a0d13; --card: #131926;
--line: #263049; --txt: #dbe4f5; --dim: #8b96ad; --ok: #3fd68f;
--warn: #e6b34d; --bad: #e5635e; --acc: #5eb1ef; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--txt);
font: 14px/1.45 system-ui, sans-serif; padding: 18px; }
header { display: flex; gap: 14px; align-items: center;
flex-wrap: wrap; margin-bottom: 14px; }
h1 { font-size: 19px; margin: 0; letter-spacing: 1px; }
#meta { color: var(--dim); font-size: 12px; }
#core { width: 54px; height: 54px; border-radius: 50%;
border: 2px solid var(--acc); position: relative; flex: none; }
#core::after { content: attr(data-state); position: absolute;
top: 60px; left: 50%; transform: translateX(-50%);
font-size: 10px; color: var(--dim); white-space: nowrap; }
#core.IDLE { animation: pulse 4s infinite; }
#core.EXECUTING, #core.THINKING { animation: pulse 1s infinite;
border-color: var(--ok); }
#core.WAITING { animation: pulse 2s infinite; border-color: var(--warn); }
#core.ALERT, #core.ERROR { border-color: var(--bad); animation: none; }
#core.E_STOP { border-color: var(--bad); background: #3a1414;
animation: none; }
@keyframes pulse { 0%,100% { opacity: .55; } 50% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { #core { animation: none; } }
body.still #core { animation: none; }
.grid { display: grid; grid-template-columns: repeat(auto-fill,
minmax(300px, 1fr)); gap: 12px; }
.card { background: var(--card); border: 1px solid var(--line);
border-radius: 10px; padding: 12px 14px; min-height: 110px; }
.card h2 { font-size: 12px; text-transform: uppercase;
letter-spacing: 1.5px; color: var(--dim); margin: 0 0 8px; }
.row { display: flex; justify-content: space-between; gap: 8px;
padding: 3px 0; border-top: 1px dotted #223; font-size: 13px; }
.k { color: var(--dim); } .v { text-align: right;
word-break: break-word; }
.ok { color: var(--ok); } .warn { color: var(--warn); }
.bad { color: var(--bad); }
.btns { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
button, input, select { font-size: 13px; padding: 6px 10px;
background: #0d1320; color: var(--txt); border: 1px solid var(--line);
border-radius: 8px; }
button { cursor: pointer; }
button:hover { border-color: var(--acc); }
#cmd { display: flex; gap: 8px; margin: 0 0 12px; }
#cmd input { flex: 1; padding: 10px 12px; font-size: 15px; }
#reply { white-space: pre-wrap; word-break: break-word; }
#tick { font-size: 12px; color: var(--dim); max-height: 130px;
overflow: auto; }
#appr input { width: 220px; }
.toolbar { display: flex; gap: 8px; align-items: center;
margin-left: auto; font-size: 12px; color: var(--dim); }
#gate { position: fixed; inset: 0; background: rgba(0,0,0,.7);
display: none; align-items: center; justify-content: center; }
#gate div { background: var(--card); padding: 24px; border-radius: 12px;
border: 1px solid var(--line); }
canvas#sky { width: 100%; height: 120px; background: #0d1320;
border-radius: 8px; }
.note { color: var(--dim); font-size: 12px; }
</style>
</head>
<body>
<header><div id="core" class="IDLE" data-state="IDLE"></div>
<div><h1>JARVIS // EXPERIENCE</h1><span id="meta">…</span></div>
<div class="toolbar"><label><input type="checkbox" id="still">
reduce motion</label></div></header>
<div id="cmd"><input id="box" placeholder="command — routed through Conductor…"
autocomplete="off"><button onclick="sendCmd()">Send</button></div>
<div class="card" style="margin-bottom:12px"><h2>response</h2>
<div id="reply">Results appear here. Commands run the real loop —
policy, approvals and verification still apply.</div></div>
<div class="grid" id="grid"></div>
<div class="card" style="margin-top:12px"><h2>activity timeline</h2>
<div id="tick"><div>connecting…</div></div></div>
<div id="gate"><div><h2>API token</h2>
<p>Same token as <code>serve --token</code>. Kept in this tab only,
sent as a header — never in URLs (except the live socket).</p>
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
if (/^(ok|true|running|ready|completed|succeeded|verified|safe|pass)$/i.test(s))
return '<span class="ok">' + esc(s) + "</span>";
if (/^(fail|failed|error|false|alert|e_stop|e-stop|denied)$/i.test(s))
return '<span class="bad">' + esc(s) + "</span>";
if (/^(unknown|waiting|pending|degraded|partial|none|—|\\?)$/i.test(s))
return '<span class="warn">' + esc(s) + "</span>";
return '<span class="v">' + esc(s) + "</span>"; }
function card(title, inner) { return '<div class="card"><h2>' + esc(title) +
"</h2>" + inner + "</div>"; }
function rows(pairs) { return pairs.map(r =>
'<div class="row"><span class="k">' + esc(r[0]) + "</span><span>" +
pill(r[1]) + "</span></div>").join(""); }
async function api(path, opts) {
let r = await fetch(path, Object.assign({headers: authz()}, opts || {}));
if (r.status === 401) { document.getElementById("gate").style.display =
"flex"; throw new Error("locked"); }
return r.json(); }
async function sendCmd() {
let box = document.getElementById("box"); let text = box.value.trim();
if (!text) return; box.value = "";
let el = document.getElementById("reply"); el.textContent = "thinking…";
try { let out = await api("cycle", {method: "POST",
headers: Object.assign({"Content-Type": "application/json"}, authz()),
body: JSON.stringify({input: text})});
el.textContent = out.response || out.error || "(no reply)"; }
catch (e) { el.textContent = "unreachable or locked."; } }
document.getElementById("box").addEventListener("keydown", e => {
if (e.key === "Enter") sendCmd(); });
async function taskOp(btn) {
let id = btn.dataset.id, verb = btn.dataset.verb;
let opts = {method: "POST",
headers: Object.assign({"Content-Type": "application/json"}, authz()),
body: "{}"};
if (verb === "cancel") { let reason = prompt("Cancel reason:", "");
if (reason === null) return;
opts.body = JSON.stringify({reason: reason}); }
try { let out = await api("api/tasks/" + encodeURIComponent(id) + "/" +
verb, opts);
document.getElementById("reply").textContent =
"task " + id + " → " + (out.state || out.error || "?"); refresh(); }
catch (e) { /* gate shown by api() */ } }
async function decide(approve) {
let box = document.getElementById("appr-token");
let tok = box.value.trim(); if (!tok) return; box.value = "";
try { let out = await api("api/approvals/decision", {method: "POST",
headers: Object.assign({"Content-Type": "application/json"}, authz()),
body: JSON.stringify({token: tok, approve: approve})});
document.getElementById("reply").textContent = out.ok ?
("approval " + (out.approved ? "granted" : "denied") + ".") :
("not decided: " + (out.reason || out.error || "?")); refresh(); }
catch (e) { /* gate shown by api() */ } }
function drawSky(topics) {
let el = document.getElementById("sky"); if (!el) return;
let g = el.getContext("2d");
let W = el.width = el.offsetWidth || 260; let H = 120;
g.fillStyle = "#0d1320"; g.fillRect(0, 0, W, H);
g.fillStyle = "#263049";
for (let gx = 0; gx < W; gx += 14) for (let gy = 0; gy < H; gy += 14)
g.fillRect(gx, gy, 1, 1);
g.fillStyle = "#5eb1ef"; let n = Math.min((topics || []).length, 24);
for (let i = 0; i < n; i++) { let px = (i * 97) % W; let py = (i * 53) % H;
g.beginPath(); g.arc(px, py, 3, 0, 7); g.fill(); }
g.fillStyle = "#8b96ad"; g.font = "11px sans-serif";
g.fillText("schematic — topics as blips, not geography", 8, H - 8); }
async function refresh() {
let b; try { b = await api("api/experience"); } catch (e) { return; }
document.getElementById("meta").textContent = "updated " +
new Date(b.generated_at * 1000).toLocaleTimeString();
let core = document.getElementById("core");
core.className = b.presence || "IDLE";
core.dataset.state = b.presence || "IDLE";
let g = [];
g.push(card("policy", rows([["indicator",
b.policy.indicator || "?"], ["conflicts", b.policy.conflicts ?? "?"],
["emergency", b.policy.emergency]]) +
'<div class="note">PolicyEngine is authoritative; this only displays.</div>'));
let mesh = (b.mesh || []).slice(0, 8).map(a =>
[a.name, a.state + " · done " + (a.tasks_done ?? 0)]);
g.push(card("agent mesh", mesh.length ? rows(mesh) : "no agents"));
let d = Array.isArray(b.durable) ? b.durable : [];
let dt = d.slice(0, 5).map(t =>
'<div class="row"><span class="k">' + esc(t.task_id) + " " +
esc(t.state) + " " + esc(t.progress || "") + "</span><span class='btns'>" +
["advance", "pause", "resume", "recover", "cancel"].map(v =>
'<button data-id="' + esc(t.task_id) + '" data-verb="' + v +
'" onclick="taskOp(this)">' + v + "</button>").join("") +
"</span></div>").join("");
g.push(card("durable tasks", (dt || "none") +
'<div class="note">Actions reuse the existing runner + policy checks.</div>'));
let a = b.approvals || [];
g.push(card("approval center", (a.length ? a.slice(0, 5).map(x =>
'<div class="row"><span class="k">' + esc(x.action.slice(0, 44)) +
"</span><span>" + esc(x.token_hint) + "</span></div>").join("") :
"no pending approvals") +
'<div class="btns" id="appr"><input id="appr-token" placeholder="paste approval token">' +
'<button onclick="decide(true)">approve</button>' +
'<button onclick="decide(false)">deny</button></div>' +
'<div class="note">Tokens are pasted, never displayed. Single-use.</div>'));
let ev = (b.missions && b.missions.evidence) || null;
g.push(card("evidence", (ev && ev.note ? esc(ev.note) :
"Evidence unavailable — use `jarvis proof &lt;claim&gt;`.") +
'<div class="note">Claims ship with sources or not at all.</div>'));
let s = b.security || {};
let scans = (s.recent_scans || []).slice(-5).reverse().map(r =>
[r.target + " [" + r.mode + "]", r.status]);
g.push(card("security", rows([["dynamic scans",
s.dynamic_available ? "available" : "not installed"]])
+ (scans.length ? rows(scans) : "") +
'<div class="note">Static: `security review` (offline). ' +
'Dynamic needs the scanner + authorization.</div>'));
let w = b.world || {};
g.push(card("world intel", '<canvas id="sky"></canvas>' +
rows([["topics", (w.topics || []).length],
["sources", w.sources_configured ?? "?"]]) +
'<div class="note">' + esc(w.live || "") + "</div>"));
let v = b.voice || {};
g.push(card("voice", rows([["provider", v.provider ?? "?"],
["profile", v.profile ?? "—"], ["style", v.style ?? "—"]]) +
'<div class="note">No live mic here — text degrades gracefully.</div>'));
let sv = b.service || {};
g.push(card("service", rows([["running", sv.running],
["heartbeat", sv.heartbeat_state ?? "?"]]) +
'<div class="note">One daemon only — this page never starts one.</div>'));
let dv = b.devices || {};
g.push(card("devices", rows([["state", dv.state || "?"]]) +
(dv.summary ? '<div class="note">' + esc(dv.summary) + "</div>" : "") +
'<div class="note">Absent backends show as unavailable, never faked.</div>'));
let n = b.notifications || [];
g.push(card("notifications", n.length ? n.slice(0, 8).map(x =>
'<div class="row"><span class="k">' + esc(x.category) +
"</span><span>" + esc(x.text).slice(0, 60) + "</span></div>").join("") :
"quiet"));
g.push(card("settings", '<div class="note">' +
esc(b.settings_mode || "read-only") + "</div>"));
document.getElementById("grid").innerHTML = g.join("");
drawSky(w.topics);
let tl = document.getElementById("tick");
tl.innerHTML = (b.timeline || []).slice().reverse().map(e =>
"<div>#" + e.seq + " " + esc(e.type) + " — " +
esc(e.summary).slice(0, 90) + "</div>").join("") || "<div>no events</div>";
}
function live() {
if (!token) return;
let proto = location.protocol === "https:" ? "wss" : "ws";
let base = location.pathname.replace(/experience.*$/, "");
let ws; try { ws = new WebSocket(proto + "://" + location.host + base +
"?token=" + encodeURIComponent(token)); }
catch (e) { setTimeout(live, 5000); return; }
ws.onmessage = ev => { let el = document.getElementById("tick");
let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
let d = document.createElement("div");
d.textContent = "#" + (m.seq ?? "?") + " " + (m.type || "?");
el.prepend(d); while (el.children.length > 30) el.lastChild.remove(); };
ws.onclose = () => setTimeout(live, 5000);
ws.onerror = () => { try { ws.close(); } catch (e) {} };
}
document.getElementById("still").addEventListener("change", e => {
document.body.classList.toggle("still", e.target.checked); });
refresh(); setInterval(refresh, 5000); live();
</script>
</body>
</html>
"""


__all__ = ["EXPERIENCE_HTML"]
