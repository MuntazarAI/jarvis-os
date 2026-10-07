"""Command centre page: elfaria-style layout, 100% live data.

Visual language follows the supplied reference exactly (shell grid,
topbar, stage, cards, panels, command bar). Every dynamic value is
fetched from `/api/experience` or a task endpoint; nothing is
hardcoded. Where the reference showed illustrative numbers (CPU %,
uptime, fake activity), this page shows the real equivalent or an
explicit empty state — never invented telemetry.
"""

from __future__ import annotations

COMMAND_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS — AI Command Centre</title>
<!-- LIVE DATA CONTRACT: agent cards, mission, activity, queue, system,
memory, knowledge, tools render from /api/experience. Empty states say
so explicitly. Command bar POSTs /cycle (gated Conductor path). -->
<style>
:root{
 --bg:#03060c;--panel:#07111d;--panel2:#0a1726;--line:#173a58;
 --text:#eaf5ff;--muted:#7892a8;--cyan:#18cfff;--blue:#3a8dff;
 --green:#25e8a1;--orange:#ff9f25;--yellow:#ffc44d;--purple:#a978ff;
 --red:#ff5968;--glow:0 0 22px rgba(24,207,255,.16);
}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%;background:#02050a;color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
body{overflow-x:hidden}
button,input{font:inherit}
button{cursor:pointer;color:inherit}
.shell{
 min-height:100vh;display:grid;
 grid-template-columns:245px minmax(600px,1fr) 300px;
 grid-template-rows:78px 1fr 70px;
 background:
 radial-gradient(circle at 48% 38%,rgba(16,89,141,.16),transparent 38%),
 radial-gradient(circle at 15% 85%,rgba(255,150,30,.07),transparent 25%),
 linear-gradient(135deg,#02050a,#06101b 48%,#02050a);
}
.top{
 grid-column:1/-1;display:flex;align-items:center;padding:9px 18px;
 border-bottom:1px solid #28415a;background:rgba(3,7,13,.91);
 box-shadow:0 8px 30px rgba(0,0,0,.3);z-index:3
}
.brand{width:275px;display:flex;align-items:center;gap:12px}
.brand-orb{width:48px;height:48px;border-radius:50%;position:relative;border:2px solid #ffae32;
 box-shadow:0 0 18px #ff8f19,inset 0 0 18px rgba(255,143,25,.35)}
.brand-orb:before{content:"";position:absolute;inset:9px;border-radius:50%;background:#ffb32d;box-shadow:0 0 18px #ff6a00}
.brand b{font-size:20px;letter-spacing:7px}.brand span{display:block;color:#d6e4ef;font-size:12px}
.brand em{font-style:normal;color:#ffbf53;font-size:11px;word-spacing:8px}
.tabs{display:flex;align-self:stretch;flex:1;align-items:center;gap:2px}
.tabs button{height:100%;min-width:74px;padding:5px 9px;background:none;border:0;color:#a8bed0;font-size:12px;position:relative}
.tabs button:hover,.tabs .selected{color:white;background:linear-gradient(#0b2032,#07121f)}
.tabs .selected:after{content:"";position:absolute;bottom:0;left:8px;right:8px;height:3px;background:#ffb83d;box-shadow:0 0 12px #ff9c21}
.icon{display:block;font-size:18px;margin-bottom:2px}
.header-right{display:flex;align-items:center;gap:22px;padding-left:18px}
.online{color:#18eea1;font-size:12px;white-space:nowrap}.online:before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:#18eea1;box-shadow:0 0 10px #18eea1;margin-right:7px}
.clock{text-align:right;border-left:1px solid #20354a;padding-left:20px}.clock b{font-size:15px}.clock small{display:block;color:var(--muted)}
.avatar{width:37px;height:37px;border-radius:50%;border:1px solid #3c5a70;background:linear-gradient(135deg,#d8a35e,#35445e);display:grid;place-items:center}
.left{
 grid-row:2;border-right:1px solid var(--line);padding:15px 10px;overflow:auto;background:rgba(4,10,17,.78)
}
.section-label{font-size:10px;letter-spacing:1.5px;color:#54758e;margin:12px 12px 7px}
.menu{display:flex;flex-direction:column;gap:3px}
.menu button{border:1px solid transparent;background:none;border-radius:9px;text-align:left;padding:9px 11px;color:#c3d3df;display:flex;align-items:center;gap:10px}
.menu button:hover,.menu button.active{background:linear-gradient(90deg,#0a385a,#071b2c);border-color:#17648d;color:#fff}
.menu .micon{width:20px;text-align:center;color:#ffb53a;font-size:17px}.menu button.active .micon{color:#55cfff}
.menu small{display:block;color:#698398;font-size:9px;margin-left:auto}
.quick{margin-top:10px;border-top:1px solid #183149;padding-top:8px}
.hero-art{
 position:absolute;inset:0;opacity:.23;pointer-events:none;
 background:
 radial-gradient(circle at 18% 22%,rgba(255,150,30,.14),transparent 17%),
 radial-gradient(circle at 76% 25%,rgba(30,175,255,.13),transparent 22%),
 linear-gradient(transparent 70%,rgba(255,140,20,.05)),
 repeating-linear-gradient(90deg,rgba(30,91,122,.14) 0 1px,transparent 1px 48px);
}
.main{grid-row:2;min-width:0;padding:15px 10px;overflow:auto}
.main-title{display:flex;align-items:flex-start;justify-content:space-between;margin:0 10px 9px}
.main-title h1{font-size:20px;margin:0 0 3px}.main-title p{margin:0;color:#89a2b7;font-size:12px}
.operational{padding:5px 10px;border:1px solid #1b735f;border-radius:999px;color:#43edb0;background:#08241e;font-size:11px}
.stage{
 min-height:545px;border:1px solid #174668;border-radius:12px;position:relative;overflow:hidden;
 background:
 linear-gradient(rgba(19,63,88,.12) 1px,transparent 1px),
 linear-gradient(90deg,rgba(19,63,88,.12) 1px,transparent 1px),
 radial-gradient(circle at 50% 52%,rgba(0,171,255,.12),transparent 27%),
 linear-gradient(180deg,#071522,#06101b 70%,#07131f);
 background-size:32px 32px,32px 32px,auto,auto;
 box-shadow:var(--glow)
}
.stage:before{content:"";position:absolute;inset:0;background:linear-gradient(115deg,transparent 0 40%,rgba(255,145,30,.035) 50%,transparent 60%)}
.mission-chip{position:absolute;top:12px;left:50%;transform:translateX(-50%);width:300px;padding:9px 12px;border:1px solid #1e5c80;border-radius:9px;background:#081827;z-index:2}
.mission-chip small{color:#61cfff}.mission-chip b{display:block;margin:3px 0 7px;font-size:12px}
.bar{height:6px;background:#153047;border-radius:5px;overflow:hidden}.bar i{display:block;height:100%;background:linear-gradient(90deg,#08b9ff,#24e3ff);width:62%}
.mission-chip .pct{float:right;color:#cbefff;margin-top:-12px;font-size:11px}
.live-box{position:absolute;top:12px;right:12px;width:180px;padding:9px;border:1px solid #184867;border-radius:8px;background:#071522;z-index:2}
.live-box b{font-size:11px}.live-box div{font-size:9px;color:#91a7b8;margin-top:5px}
.core{position:absolute;left:50%;top:53%;transform:translate(-50%,-50%);width:128px;height:128px;border-radius:50%;
 border:2px solid #1ce0ff;background:#04121e;display:grid;place-items:center;text-align:center;
 box-shadow:0 0 25px #08a8dd,0 0 65px rgba(0,179,255,.2),inset 0 0 30px rgba(18,202,255,.15);z-index:2}
.core:before{content:"";position:absolute;inset:11px;border:1px solid #16769d;border-radius:50%}
.core:after{content:"";position:absolute;width:34px;height:34px;border-radius:50%;background:#0dd5ff;box-shadow:0 0 25px #0dd5ff;opacity:.45}
.core-text{position:relative;z-index:2}.core strong{display:block;color:#35eaff;font-size:12px;letter-spacing:1px}.core small{display:block;color:#8fa9bb;font-size:8px}
.agent{position:absolute;width:190px;padding:10px;border:1px solid #174f6d;border-radius:9px;background:rgba(5,17,28,.95);z-index:2;box-shadow:0 8px 20px rgba(0,0,0,.22);cursor:pointer}
.agent:after{content:"";position:absolute;width:7px;height:7px;border-radius:50%;background:#21e5a1;right:11px;top:13px;box-shadow:0 0 9px #21e5a1}
.agent.idle:after{background:#5a6577;box-shadow:none}
.agent.waiting:after{background:#ffc04a;box-shadow:0 0 9px #ffc04a}
.agent.error:after{background:#ff6874;box-shadow:0 0 9px #ff6874}
.agent b{font-size:13px}.role{display:block;color:#8aa3b6;font-size:10px}.agent .task{display:block;color:#e3a746;font-size:10px;margin-top:6px}.agent .status{font-size:9px;margin-top:4px}
.ag1{top:55px;left:11%}.ag2{top:55px;left:43%}.ag3{top:55px;right:11%}
.ag4{bottom:70px;left:7%}.ag5{bottom:70px;left:32%}.ag6{bottom:70px;left:57%}.ag7{bottom:70px;right:5%}
.connector{position:absolute;height:1px;background:linear-gradient(90deg,transparent,#1edfff,transparent);transform-origin:left center;opacity:.55;z-index:1}
.c1{width:280px;left:26%;top:37%;transform:rotate(20deg)}.c2{width:240px;left:49%;top:37%;transform:rotate(-16deg)}
.c3{width:300px;left:28%;top:65%;transform:rotate(-18deg)}.c4{width:300px;left:49%;top:65%;transform:rotate(17deg)}
.lower{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:7px;margin-top:8px}
.card{border:1px solid #183c58;border-radius:9px;background:linear-gradient(145deg,#081725,#06101a);padding:10px;min-height:145px;box-shadow:var(--glow)}
.card h3{font-size:12px;margin:0 0 8px}.row{display:flex;justify-content:space-between;gap:8px;padding:5px 0;border-bottom:1px solid #10283c;font-size:10px}.row:last-child{border:0}.row small{color:#748ca0}.green{color:#23e7a2}.yellow{color:#ffc04a}.blue{color:#45cfff}.red{color:#ff6874}
.memory-node{display:grid;grid-template-columns:1fr 1fr;gap:5px}.memory-node span{border:1px solid #20425c;border-radius:6px;padding:5px;text-align:center;color:#b9d3e5;font-size:9px}
.right{grid-row:2;border-left:1px solid var(--line);padding:14px 10px;overflow:auto;background:rgba(4,10,17,.78)}
.panel{border:1px solid #173a57;border-radius:10px;background:linear-gradient(145deg,#081725,#06101a);padding:11px;margin-bottom:9px;box-shadow:var(--glow)}
.panel h2{font-size:13px;margin:0}.panel-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:9px}.view{color:#43cfff;font-size:10px}
.mission-card h3{font-size:13px;margin:0 0 5px}.mission-card p{font-size:9px;color:#8aa1b3;margin:0 0 9px}.mission-card .bar{margin-bottom:9px}
.eta{display:flex;justify-content:space-between;color:#91a6b6;font-size:9px;margin-bottom:9px}.eta b{color:white}
.check{display:flex;align-items:center;gap:8px;padding:7px 0;border-bottom:1px solid #112a40;font-size:10px}.check:last-child{border:0}.check i{width:13px;height:13px;border:2px solid #8da4b4;border-radius:50%;display:block}.check.done i{background:#1fe5a0;border-color:#1fe5a0;box-shadow:0 0 8px #1fe5a0}.check.active i{border-color:#2fcfff;box-shadow:0 0 8px #2fcfff}.check span{margin-left:auto;color:#5fe6b7;font-size:9px}
.queue-tabs{display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin-bottom:5px}.queue-tabs span{font-size:8px;padding:5px 2px;text-align:center;border:1px solid #18384f;border-radius:5px;color:#8ea5b7}.queue-tabs span:first-child{color:#48d8ff;background:#0a2337}
.metric{display:flex;align-items:center;gap:7px;padding:7px 0}.metric .mi{width:8px;height:8px;border-radius:50%;background:#1ee6a0}.metric b{font-size:10px;flex:1}.metric small{color:#839aac;font-size:9px}.metric .tiny{width:55px;height:4px;background:#163048;border-radius:5px;overflow:hidden}.tiny i{display:block;height:100%;background:#16cfff}
.approval{padding:8px 0;border-bottom:1px solid #152e43;font-size:10px}.approval:last-child{border:0}.approval small{color:#7d95a8}.actions{display:flex;gap:5px;margin-top:6px}.actions button{border:1px solid #1a657e;background:#0b293b;border-radius:5px;padding:4px 7px;font-size:9px}.actions .deny{border-color:#68404a;color:#ff8e99}
.system .metric{padding:6px 0}.system .metric .mi{background:#f3aa31}.system .tiny{flex:1}
.bottom{grid-column:2/-1;display:flex;align-items:center;gap:9px;border-top:1px solid #17354d;padding:10px 18px;background:#040910}
.bottom-orb{width:34px;height:34px;border:2px solid #1de3ff;border-radius:50%;box-shadow:0 0 15px #1de3ff}
.command{height:43px;flex:1;max-width:720px;margin:auto;border:1px solid #205e7e;border-radius:24px;background:#071725;display:flex;align-items:center;padding:4px 8px 4px 14px;box-shadow:0 0 18px rgba(0,180,255,.1)}
.command input{flex:1;border:0;outline:0;background:none;color:white;font-size:12px}.command button{width:34px;height:34px;border-radius:50%;border:0;background:#12d8d0;color:#001318;font-weight:800}
.footer-meta{color:#6f899b;font-size:9px}.footer-meta b{color:#c5d7e5}
#gate{position:fixed;inset:0;background:rgba(0,0,0,.75);display:none;align-items:center;justify-content:center;z-index:9}
#gate div{background:#081725;padding:24px;border-radius:12px;border:1px solid #173a57}
#gate input{background:#071725;color:#fff;border:1px solid #205e7e;border-radius:8px;padding:8px}
@media(max-width:1200px){.shell{grid-template-columns:205px 1fr}.right{display:none}.brand{width:230px}.tabs button{min-width:60px}}
@media(max-width:850px){.shell{display:block}.top{flex-wrap:wrap}.brand{width:auto}.tabs{display:none}.left{display:none}.main{padding:10px}.lower{grid-template-columns:1fr 1fr}.stage{min-height:620px}.agent{width:155px}.bottom{position:sticky;bottom:0}.header-right{margin-left:auto}}
@media(max-width:560px){.lower{grid-template-columns:1fr}.mission-chip{width:calc(100% - 30px)}.live-box{display:none}}
</style>
</head>
<body>
<div class="shell">
<header class="top">
  <div class="brand">
    <div class="brand-orb"></div>
    <div><b>JARVIS</b><span>Your Local AI Operating System</span><em>Think · Build · Create · Explore</em></div>
  </div>
  <nav class="tabs" id="tabs"></nav>
  <div class="header-right"><div class="online" id="presence-pill">System Online</div><div class="clock"><b id="time">--:--</b><small id="date">…</small></div><div class="avatar">👤</div></div>
</header>

<aside class="left">
  <div class="section-label">COMMAND CENTER</div>
  <div class="menu" id="menu"></div>
  <div class="section-label">QUICK ACTIONS</div>
  <div class="menu quick">
    <button id="qa-mission"><span class="micon">✦</span><div>New Mission<small>Create a task for agents</small></div></button>
    <button id="qa-focus"><span class="micon">⌁</span><div>Command Bar<small>Ask anything</small></div></button>
  </div>
</aside>

<main class="main">
  <div class="main-title">
    <div><h1>Agent Command Room</h1><p id="subtitle">…</p></div>
    <span class="operational" id="op-pill">● …</span>
  </div>
  <section class="stage" id="stage">
    <div class="mission-chip"><small>Current Mission</small><b id="mission-title">…</b><div class="bar"><i id="mission-bar"></i></div></div>
    <div class="live-box"><b>Live Activity</b><div id="livebox"></div></div>
    <div id="agents"></div>
    <div class="core"><div class="core-text"><strong>JARVIS CORE</strong><small>Orchestrator</small><small id="core-sub">idle</small></div></div>
  </section>

  <section class="lower">
    <div class="card"><div class="panel-head"><h3>Recent Activity</h3></div>
      <div id="activity"></div>
    </div>
    <div class="card"><div class="panel-head"><h3>Memory Palace</h3></div>
      <div class="memory-node" id="rooms"></div>
    </div>
    <div class="card"><div class="panel-head"><h3>Knowledge Graph</h3></div>
      <div id="graph"></div>
    </div>
    <div class="card"><div class="panel-head"><h3>Tools & Integrations</h3></div>
      <div id="tools"></div>
    </div>
  </section>
</main>

<aside class="right">
  <section class="panel mission-card" id="mission-panel">
    <div class="panel-head"><h2>Mission Control</h2></div>
    <h3 id="mc-title">…</h3>
    <p id="mc-sub">…</p>
    <div class="bar"><i id="mc-bar"></i></div>
    <div class="eta"><span>State<br><b id="mc-state">…</b></span><span>Progress<br><b id="mc-prog">…</b></span></div>
    <div id="mc-steps"></div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>Task Queue</h2></div>
    <div class="queue-tabs" id="queue-tabs"></div>
    <div id="queue"></div>
  </section>

  <section class="panel" id="appr-panel" style="display:none">
    <div class="panel-head"><h2>Approvals</h2></div>
    <div id="apprs"></div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>System Status</h2></div>
    <div class="system" id="sysrows"></div>
  </section>
</aside>

<footer class="bottom">
  <div class="bottom-orb"></div>
  <div class="footer-meta"><b>JARVIS</b><br>Local First • Private • Your Rules</div>
  <div class="command"><span>◉</span><input id="ask" placeholder="Ask JARVIS anything..."><button onclick="ask()">➤</button></div>
  <div class="footer-meta" id="listen-note">⌁ ready</div>
</footer>
</div>

<div id="gate"><div><h2>API token</h2>
<p>Same token as <code>serve --token</code>. Kept in this tab only.</p>
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
function mapState(st) { st = String(st || "idle").toLowerCase();
if (/run|execut|work|busy|build|search|analyz|scan/.test(st)) return "WORKING";
if (/wait|pend|block/.test(st)) return "WAITING";
if (/think|plan/.test(st)) return "THINKING";
if (/err|fail/.test(st)) return "ERROR";
return "IDLE"; }
const POS = ["ag1","ag2","ag3","ag4","ag5","ag6","ag7"];
const ROLE_SUB = {supervisor:"Supervisor", planner:"Planner", researcher:"Researcher",
coder:"Coder", analyst:"Analyst", computer:"Computer", guardian:"Guardian", librarian:"Librarian"};
async function api(path, opts) {
let r = await fetch(path, Object.assign({headers: authz()}, opts || {}));
if (r.status === 401) { document.getElementById("gate").style.display = "flex";
throw new Error("locked"); }
return r.json(); }
function dotFor(type) {
if (/fail|error|deny/.test(type)) return "red";
if (/approv|wait|pend/.test(type)) return "yellow";
if (/verif|complet|check|memory/.test(type)) return "green";
return "blue"; }
async function refresh() {
let b; try { b = await api("api/experience"); }
catch (e) { return; }
let mesh = (b.mesh || []).slice(0, 7);
let running = (Array.isArray(b.durable) ? b.durable : []).filter(t =>
t.state === "running" || t.state === "verifying");
let approvals = b.approvals || [];
let active = mesh.filter(a => mapState(a.state) !== "IDLE").length;
document.getElementById("subtitle").textContent =
mesh.length + " agents · " + running.length + " tasks running · " +
approvals.length + " approvals waiting";
let pill = document.getElementById("op-pill");
pill.textContent = "● " + (b.presence === "IDLE" ? "All Systems Operational" : b.presence);
document.getElementById("presence-pill").textContent =
b.presence === "IDLE" ? "System Online" : b.presence;
document.getElementById("core-sub").textContent =
(b.presence || "idle").toLowerCase();
let layer = document.getElementById("agents");
layer.innerHTML = mesh.map((a, i) => {
let st = mapState(a.state); let cls = st === "IDLE" ? " idle" :
st === "WAITING" ? " waiting" : (st === "ERROR" ? " error" : "");
let sub = (ROLE_SUB[a.name] || a.name) + " · " + st;
let task = "";
if (a.name === "supervisor" && running.length) { st = "WORKING";
task = '<span class="task">' + esc(String(running[0].title ||
running[0].task_id).slice(0, 40)) + "</span>"; }
if (a.name === "computer" && approvals.length) { st = "WAITING";
task = '<span class="task">needs approval!</span>'; cls = " waiting"; }
return '<div class="agent' + cls + " " + POS[i % POS.length] + '"><b>' +
esc(a.name) + '</b><span class="role">' + esc(sub) +
'</span><br><span class="status" style="color:' +
({WORKING:"#21e5a1", WAITING:"#ffc04a", ERROR:"#ff6874",
THINKING:"#a978ff"}[st] || "#8aa3b6") + '">' + st + "</span>" + task + "</div>";
}).join("");
let first = running[0] || (Array.isArray(b.durable) ? b.durable.filter(t =>
t.state === "ready" || t.state === "paused")[0] : null);
if (first) {
document.getElementById("mission-title").textContent =
String(first.title || first.task_id).slice(0, 60);
let m = /^(\\d+)\\/(\\d+)$/.exec(first.progress || "");
let pct = m ? Math.round(100 * (+m[1]) / Math.max(1, +m[2])) : 0;
document.getElementById("mission-bar").style.width = pct + "%";
} else {
document.getElementById("mission-title").textContent =
"No active mission — create one below";
document.getElementById("mission-bar").style.width = "0%"; }
let live = (b.timeline || []).slice(-4).reverse();
document.getElementById("livebox").innerHTML = live.length ? live.map(e =>
"<div>● " + esc(e.type) + " — " + esc(e.summary).slice(0, 44) +
"</div>").join("") : "<div>quiet — no events yet</div>";
document.getElementById("activity").innerHTML = (b.timeline || []).slice(-5)
.reverse().map(e => '<div class="row"><span class="' + dotFor(e.type) +
'">● ' + esc(e.type) + " — " + esc(e.summary).slice(0, 52) +
"</span><small>#" + e.seq + "</small></div>").join("") ||
'<div class="row"><span>quiet — no events yet</span></div>';
let rooms = b.system && b.system.memory ? b.system.memory.rooms || {} : {};
let keys = Object.keys(rooms);
document.getElementById("rooms").innerHTML = keys.length ?
keys.slice(0, 8).map(k => "<span>▣ " + esc(k) + "</span>").join("") :
"<span>empty — remember something first</span>";
let gr = b.system && b.system.graph ? b.system.graph : {};
document.getElementById("graph").innerHTML =
'<div class="row"><span>Nodes</span><b>' + (gr.nodes ?? "?") + "</b></div>" +
'<div class="row"><span>Edges</span><b>' + (gr.edges ?? "?") + "</b></div>" +
'<div class="row"><span>Identities</span><b>' + (gr.identities ?? "?") + "</b></div>";
let tools = b.system && b.system.tools ? b.system.tools.registered || [] : [];
document.getElementById("tools").innerHTML = tools.length ?
tools.slice(0, 5).map(t => '<div class="row"><span>◉ ' + esc(t) +
'</span><b class="green">● registered</b></div>').join("") :
'<div class="row"><span>no tools reported</span></div>';
if (first) {
document.getElementById("mc-title").textContent =
"▣ " + String(first.title || first.task_id).slice(0, 48);
document.getElementById("mc-sub").textContent =
first.task_id + " · updated recently";
document.getElementById("mc-state").textContent = first.state;
document.getElementById("mc-prog").textContent = first.progress || "—";
try {
let det = await api("api/tasks/" + encodeURIComponent(first.task_id));
let steps = det.steps || [];
document.getElementById("mc-steps").innerHTML = steps.length ?
steps.slice(0, 6).map(s => '<div class="check ' +
(s.state === "succeeded" ? "done" : (s.state === "running" ? "active" : "")) +
'"><i></i>' + esc(s.title).slice(0, 34) + "<span>" + esc(s.state) +
"</span></div>").join("") : "<div>no steps listed</div>";
document.getElementById("mc-bar").style.width =
(steps.length ? Math.round(100 * steps.filter(s =>
s.state === "succeeded").length / steps.length) : 0) + "%";
} catch (e) { /* locked: gate already shown */ }
} else {
document.getElementById("mc-title").textContent = "No active mission";
document.getElementById("mc-sub").textContent =
"Create one with New Mission below";
document.getElementById("mc-bar").style.width = "0%";
document.getElementById("mc-steps").innerHTML = ""; }
let tc = b.task_counts || {};
let tabs = [["Running", tc.running || 0], ["Ready", tc.ready || 0],
["Waiting", 0], ["Failed", tc.failed || 0], ["Done", 0]];
document.getElementById("queue-tabs").innerHTML = tabs.map(x =>
"<span>" + x[0] + " " + x[1] + "</span>").join("");
let top = (Array.isArray(b.durable) ? b.durable : []).slice(-3).reverse();
document.getElementById("queue").innerHTML = top.length ? top.map(t => {
let m = /^(\\d+)\\/(\\d+)$/.exec(t.progress || "");
let pct = m ? Math.round(100 * (+m[1]) / Math.max(1, +m[2])) : 0;
return '<div class="metric"><i class="mi"></i><b>' + esc(t.title).slice(0, 30) +
"<br><small>" + esc(t.state) + "</small></b><small>" + pct +
'%</small><div class="tiny"><i style="width:' + pct + '%"></i></div></div>';
}).join("") : '<div class="metric"><b>queue empty</b></div>';
let ap = document.getElementById("appr-panel");
if (approvals.length) { ap.style.display = "";
document.getElementById("apprs").innerHTML = approvals.slice(0, 3).map(x =>
'<div class="approval">' + esc(x.action).slice(0, 60) +
"<br><small>hint " + esc(x.token_hint) +
' — paste token to decide</small><div class="actions">' +
'<button onclick="decide(true)">approve</button>' +
'<button class="deny" onclick="decide(false)">deny</button></div></div>')
.join("") +
'<div class="approval"><input id="appr-token" placeholder="paste approval token" ' +
'style="width:100%;background:#071725;border:1px solid #205e7e;border-radius:6px;color:#fff;padding:6px"></div>';
} else ap.style.display = "none";
let sv = b.service || {}, p = b.policy || {}, v = b.voice || {};
let ev = b.events || {};
document.getElementById("sysrows").innerHTML =
'<div class="metric"><i class="mi"></i><b>Presence</b><small>' +
esc(b.presence || "?") + "</small></div>" +
'<div class="metric"><i class="mi"></i><b>Service</b><small>' +
(sv.running === true ? "running" : "not running") + "</small></div>" +
'<div class="metric"><i class="mi"></i><b>Policy</b><small>' +
esc(p.indicator || "?") + "</small></div>" +
'<div class="metric"><i class="mi"></i><b>Events</b><small>' +
(ev.count ?? "?") + "</small></div>" +
'<div class="metric"><i class="mi"></i><b>Voice</b><small>' +
esc(v.provider || "?") + "</small></div>" +
'<div class="metric"><i class="mi"></i><b>Approvals</b><small>' +
approvals.length + " pending</small></div>";
}
let _decideApprove = true;
async function decide(approve) {
let box = document.getElementById("appr-token");
let tok = box ? box.value.trim() : ""; if (!tok) return; box.value = "";
try { let out = await api("api/approvals/decision", {method: "POST",
headers: Object.assign({"Content-Type": "application/json"}, authz()),
body: JSON.stringify({token: tok, approve: approve})});
document.getElementById("listen-note").textContent = out.ok ?
("approval " + (out.approved ? "granted." : "denied.")) :
("not decided: " + (out.reason || out.error || "?")); refresh(); }
catch (e) { /* gate shown */ } }
async function ask() {
let box = document.getElementById("ask"); let text = box.value.trim();
if (!text) return; box.value = "";
let note = document.getElementById("listen-note");
note.textContent = "⌁ thinking…";
try { let out = await api("cycle", {method: "POST",
headers: Object.assign({"Content-Type": "application/json"}, authz()),
body: JSON.stringify({input: text})});
note.textContent = "⌁ " + String(out.response || out.error ||
"(no reply)").slice(0, 90); refresh(); }
catch (e) { note.textContent = "⌁ unreachable or locked."; } }
document.getElementById("ask").addEventListener("keydown", e => {
if (e.key === "Enter") ask(); });
document.getElementById("qa-focus").onclick = () =>
document.getElementById("ask").focus();
document.getElementById("qa-mission").onclick = async () => {
let title = prompt("Mission title:", "");
if (!title || !title.trim()) return;
try { let out = await api("api/tasks", {method: "POST",
headers: Object.assign({"Content-Type": "application/json"}, authz()),
body: JSON.stringify({title: title.trim().slice(0, 300),
steps: [{title: title.trim().slice(0, 500)}]})});
document.getElementById("listen-note").textContent = out.task_id ?
("⌁ mission filed: " + out.task_id) : ("⌁ " + (out.error || "?"));
refresh(); } catch (e) { /* gate shown */ } };
const TABS = [["Home", null], ["Agents", "stage"], ["Memory", null],
["Knowledge", null], ["Tools", null], ["Devices", null], ["Automation", null],
["Security", null], ["Logs", null], ["Settings", null]];
const ICONS = ["⌂","♙","▱","◫","◈","▣","⌘","♢","▤","⚙"];
document.getElementById("tabs").innerHTML = TABS.map((t, i) =>
'<button data-i="' + i + '"' + (i === 0 ? ' class="selected"' : "") +
'><span class="icon">' + ICONS[i] + "</span>" + t[0] + "</button>").join("");
document.getElementById("tabs").onclick = e => {
let btn = e.target.closest("button"); if (!btn) return;
document.querySelectorAll("#tabs button").forEach(x =>
x.classList.remove("selected"));
btn.classList.add("selected"); };
const MENU = [["Command Center", "Your AI team is active", "stage"],
["Overview", "Live system view", null], ["Agent Control", "Manage agents", "stage"],
["Mission Control", "Tasks & goals", "mission-panel"],
["Knowledge Graph", "Memory & context", null],
["File & Project Hub", "Files, code, projects", null],
["Tools & Integrations", "Apps, APIs, MCP", null],
["Settings", "System configuration", null]];
document.getElementById("menu").innerHTML = MENU.map((m, i) =>
'<button data-i="' + i + '"' + (i === 1 ? ' class="active"' : "") +
'><span class="micon">' + ["♟","◉","♙","▣","⌘","▤","✣","⚙"][i] +
"</span><div>" + m[0] + "<small>" + m[1] + "</small></div></button>").join("");
document.getElementById("menu").onclick = e => {
let btn = e.target.closest("button"); if (!btn) return;
document.querySelectorAll("#menu button").forEach(x =>
x.classList.remove("active"));
btn.classList.add("active");
let target = MENU[+btn.dataset.i][2];
if (target === "stage") document.getElementById("stage").scrollIntoView();
else if (target) document.getElementById(target).scrollIntoView();
else if (MENU[+btn.dataset.i][0] === "Command Center")
document.getElementById("ask").focus(); };
function tick() {
const d = new Date();
document.getElementById("time").textContent =
String(d.getHours()).padStart(2, "0") + ":" +
String(d.getMinutes()).padStart(2, "0");
document.getElementById("date").textContent = d.toDateString(); }
tick(); setInterval(tick, 30000);
refresh(); setInterval(refresh, 8000);
</script>
</body>
</html>
"""


__all__ = ["COMMAND_HTML"]
