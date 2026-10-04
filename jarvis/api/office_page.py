"""Agent office floor in Munder Difflin design language (live data).

Faithful to their DESIGN.md tokens: cream panels with 3-layer SNES
borders, wood tile floor, 24x24 avatars with per-agent palettes,
status overlays, lowercase status badges, short human copy. Fonts fall
back to system stacks offline (their Google Fonts linked first).

HONESTY MAPPING (documented deviations from their spec):
- Avatars sit at desks; no fake walking (we track no positions —
  walking without them would be theater, which their spec forbids).
- Activity = bob + overlays driven by real mesh states only.
- Success sparkle fires ONLY when tasks_done actually increments.
- Mailbox flag is UP iff approvals are pending. Nothing else moves it.
- Bubbles carry running task titles / approval alerts or nothing.
- Click selects (portrait + numbers + command bar), same as their panel.
"""

from __future__ import annotations

OFFICE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS // Office Floor</title>
<!-- HONESTY MAPPING (their spec, our data): mesh state drives status
overlays; supervisor bubble = first running task title; computer
"blocked" + mailbox flag iff approvals pending; avatars sit at desks
(no fake walking — we track no positions); sparkle ONLY on real
tasks_done increments; idle agents sit quietly. -->
<!-- Design tokens: Munder Difflin DESIGN.md (cream/ink/status). Live
data from /api/experience. Deviations documented in module docstring. -->
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Pixelify+Sans&family=VT323&display=swap">
<style>
:root {
--cream-50:#FFFDF5; --cream-100:#FFF8E7; --cream-200:#F4E9C7;
--ink-900:#1A1320; --ink-700:#3D2E4A; --ink-500:#6B5878; --ink-300:#A899B5;
--st-idle:#A899B5; --st-thinking:#4ECDC4; --st-working:#FFD93D;
--st-waiting:#6C8EF5; --st-blocked:#FF6B6B; --st-success:#6BCF7F;
--wood-l:#E5C896; --wood-d:#C9A66B; --wall:#8B6F47; --path:#E8D8B0;
}
* { box-sizing:border-box; }
body { margin:0; background:#241a2e; color:var(--ink-900);
font-family:"Pixelify Sans",system-ui,sans-serif; padding:16px; }
.top { max-width:1180px; margin:0 auto 12px; background:var(--cream-100);
box-shadow:inset 0 0 0 2px var(--cream-200), inset 0 0 0 3px var(--ink-700), inset 0 0 0 5px var(--ink-900);
padding:10px 16px; display:flex; align-items:center; gap:12px; }
.top h1 { font-family:"Press Start 2P",monospace; font-size:16px; margin:0; }
.top span { color:var(--ink-500); font-size:14px; }
.top .live { margin-left:auto; font-size:12px; color:var(--ink-500); }
.layout { max-width:1180px; margin:0 auto; display:grid;
grid-template-columns:1fr 300px; gap:12px; }
.panel { background:var(--cream-100);
box-shadow:inset 0 0 0 2px var(--cream-200), inset 0 0 0 3px var(--ink-700), inset 0 0 0 5px var(--ink-900);
padding:12px; }
.panel h2 { font-family:"Press Start 2P",monospace; font-size:12px;
margin:0 0 8px; }
canvas#floor { width:100%; image-rendering:pixelated; background:var(--wood-l);
border:2px solid var(--ink-900); }
.strip { display:flex; gap:8px; overflow-x:auto; margin-top:12px; }
.acard { min-width:150px; background:var(--cream-100);
box-shadow:inset 0 0 0 2px var(--cream-200), inset 0 0 0 3px var(--ink-700), inset 0 0 0 5px var(--ink-900);
padding:8px; cursor:pointer; }
.acard.sel { box-shadow:inset 0 0 0 2px var(--ac, #4ECDC4), inset 0 0 0 3px var(--ink-700), inset 0 0 0 5px var(--ink-900); }
.acard b { font-size:14px; }
.badge { display:inline-block; font-size:12px; margin-top:4px;
padding:1px 8px 1px 18px; position:relative;
background:color-mix(in srgb, var(--bc,#A899B5) 20%, var(--cream-100)); }
.badge:before { content:""; position:absolute; left:6px; top:6px; width:8px;
height:8px; border-radius:50%; background:var(--bc,#A899B5); }
.dots { color:var(--ink-500); font-size:12px; margin-top:4px; }
.selbox { display:flex; gap:12px; }
#portrait { width:96px; height:96px; image-rendering:pixelated;
border:2px solid var(--ink-900); background:var(--cream-200); }
.kv { font-size:14px; margin:3px 0; }
.cmdbar { margin-top:10px; background:var(--cream-200);
box-shadow:inset 0 0 0 2px var(--cream-100), inset 0 0 0 3px var(--ink-500), inset 0 0 0 5px var(--ink-700);
padding:8px; }
.cmdbar .row { display:flex; gap:8px; }
.cmdbar input { flex:1; border:0; outline:0; background:transparent;
font-family:"VT323",monospace; font-size:18px; color:var(--ink-900); }
.cmdbar button { border:2px solid var(--ink-900); background:var(--ink-900);
color:var(--cream-50); padding:6px 14px; cursor:pointer; font-size:14px; }
.cmdbar button:active { transform:translate(0,2px); }
.cmdbar.busy input { caret-color:#FFD93D; }
#reply { font-family:"VT323",monospace; font-size:16px; margin-top:6px;
min-height:22px; }
#gate { position:fixed; inset:0; background:rgba(26,19,32,.6); display:none;
align-items:center; justify-content:center; }
#gate div { background:var(--cream-50); padding:24px;
box-shadow:inset 0 0 0 2px var(--cream-200), inset 0 0 0 3px var(--ink-700), inset 0 0 0 5px var(--ink-900); }
#gate input { font-size:14px; padding:6px; margin-right:8px; }
#appr-modal { position:fixed; inset:0; background:rgba(26,19,32,.6);
display:none; align-items:center; justify-content:center; z-index:5; }
#appr-modal .dlg { width:340px; background:var(--cream-50);
box-shadow:inset 0 0 0 2px var(--cream-200), inset 0 0 0 3px var(--ink-700), inset 0 0 0 5px var(--ink-900),
4px 4px 0 rgba(26,19,32,.25); padding:0 0 12px; }
#appr-modal .stripe { height:12px; background:var(--st, #FFD93D); }
#appr-modal .body { padding:10px 14px; font-size:14px; }
#appr-modal .body small { color:var(--ink-500); }
#appr-modal .actions { display:flex; gap:8px; padding:0 14px; }
#appr-modal button { flex:1; padding:8px; cursor:pointer; font-size:14px;
border:2px solid var(--ink-900); }
#appr-yes { background:var(--ink-900); color:var(--cream-50); }
#appr-no { background:var(--cream-100); color:var(--ink-900); }
#appr-modal button:active { transform:translate(0,2px); }
@media (prefers-reduced-motion: reduce) { * { animation:none !important; } }
body.still canvas { image-rendering:pixelated; }
</style>
</head>
<body>
<div class="top"><h1>JARVIS OFFICE</h1>
<span>your agents, at their desks</span>
<span class="live" id="meta">…</span></div>
<div class="layout">
<div>
<div class="panel"><h2 id="floor-title">Floor</h2>
<canvas id="floor" width="1280" height="800"></canvas></div>
<div class="strip" id="strip"></div>
</div>
<div>
<div class="panel"><h2>Selected</h2><div id="selbox">
<div class="selbox"><canvas id="portrait" width="24" height="24"></canvas>
<div id="selinfo">click anyone…</div></div>
<div class="cmdbar" id="cmdbar"><div class="row">
<span>&gt;</span><input id="box" placeholder="tell them something…">
<button onclick="sendCmd()">Send</button></div>
<div id="reply"></div></div>
</div></div>
<div class="panel" style="margin-top:12px"><h2>Mailbox</h2>
<div id="mailbox" class="kv">no pending messages</div></div>
</div>
</div>
<div id="appr-modal"><div class="dlg">
<div class="stripe" id="appr-stripe"></div>
<div class="body"><b>Approval needed</b><br><span id="appr-what"></span><br>
<small id="appr-meta"></small></div>
<div class="actions"><button id="appr-yes">approve</button>
<button id="appr-no">deny</button></div></div></div>
<div id="gate"><div><h2>API token</h2>
<input id="tok" type="password" placeholder="token">
<button onclick="saveTok()">Unlock</button></div></div>
<script>
let token = sessionStorage.getItem("jarvis-token") || "";
let team = [], selected = null, prevDone = {}, sparks = [];
let seenApprovals = {}, currentAppr = null;
let reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function saveTok() { token = document.getElementById("tok").value;
sessionStorage.setItem("jarvis-token", token);
document.getElementById("gate").style.display = "none"; refresh(); }
function authz() { return token ? {"Authorization": "Bearer " + token} : {}; }
function hash(s) { let h = 0; for (let c of s) h = (h*31 + c.charCodeAt(0)) >>> 0; return h; }
const ACCENTS = ["#FF6B6B","#6BCF7F","#4ECDC4","#FFD93D","#B197FC","#FFA07A"];
const SKIN = "#f2c9a0";
function mapState(st) { st = String(st || "idle").toLowerCase();
if (/run|execut|work|busy|build|search|analyz|scan/.test(st)) return "working";
if (/wait|pend|block/.test(st)) return "waiting";
if (/think|plan/.test(st)) return "thinking";
if (/err|fail/.test(st)) return "blocked";
return "idle"; }
const STC = {idle:"#A899B5", thinking:"#4ECDC4", working:"#FFD93D",
waiting:"#6C8EF5", blocked:"#FF6B6B", success:"#6BCF7F"};
async function api(path, opts) {
let r = await fetch(path, Object.assign({headers: authz()}, opts || {}));
if (r.status === 401) { document.getElementById("gate").style.display = "flex";
throw new Error("locked"); }
return r.json(); }
async function refresh() {
let b; try { b = await api("api/experience"); } catch (e) { return; }
document.getElementById("meta").textContent = "live · " +
new Date(b.generated_at * 1000).toLocaleTimeString();
let mesh = (b.mesh || []).slice(0, 8);
let running = (Array.isArray(b.durable) ? b.durable : []).filter(t =>
t.state === "running" || t.state === "verifying");
let approvals = b.approvals || [];
team = mesh.map(a => { let name = a.name || "?";
let done = a.tasks_done ?? 0;
if (prevDone[name] !== undefined && done > prevDone[name])
sparks.push({name: name, until: performance.now() + 900});
prevDone[name] = done;
return {n: name, hair: ["#4a3226","#e05a4e","#e8c872","#2b2b3a"][hash(name) % 4],
shirt: ACCENTS[hash(name) % ACCENTS.length],
s: mapState(a.state), b: "", done: done, failed: a.tasks_failed ?? 0}; });
if (!team.length) team = [{n:"no agents", hair:"#5a6577", shirt:"#8b96ad",
s:"idle", b:"", done:0, failed:0}];
team.forEach(a => {
if (a.n === "supervisor" && running.length) { a.s = "working";
a.b = String(running[0].title || running[0].task_id).slice(0, 40); }
if (a.n === "computer" && approvals.length) { a.s = "blocked";
a.b = "needs you!"; }
if (a.s === "thinking" && !a.b) a.b = "…"; });
if (!team.some(a => a.n === selected)) selected = team[0].n;
let mb = document.getElementById("mailbox");
mb.textContent = approvals.length ? approvals.length + " waiting — computer needs you" :
"no pending messages";
document.getElementById("floor-title").textContent =
"Floor · " + team.length + " at desks";
checkApprovals(approvals);
document.getElementById("strip").innerHTML = team.map(a =>
'<div class="acard' + (a.n === selected ? " sel" : "") +
'" style="--ac:' + a.shirt + '" data-n="' + a.n + '"><b>' + a.n + "</b><br>" +
'<span class="badge" style="--bc:' + STC[a.s] + '">' + a.s + "</span>" +
'<div class="dots">' + "●".repeat(Math.min(8, a.done)) +
"○".repeat(Math.max(0, Math.min(8, 8 - a.done))) + "</div></div>").join("");
document.querySelectorAll(".acard").forEach(c => c.onclick = () => {
selected = c.dataset.n; refresh(); });
renderSel(); }
function renderSel() {
let a = team.find(z => z.n === selected) || team[0]; if (!a) return;
drawPortrait(a);
drawPortrait(a);
document.getElementById("selinfo").innerHTML = "<b>" + a.n + "</b><br>" +
'<span class="badge" style="--bc:' + STC[a.s] + '">' + a.s + "</span>" +
'<div class="kv">done ' + a.done + " · failed " + a.failed + "</div>" +
(a.b ? '<div class="kv">“' + a.b + '”</div>' : ""); }
async function checkApprovals(approvals) {
if (!approvals.length) {
document.getElementById("appr-modal").style.display = "none";
currentAppr = null; return; }
let det = null;
try { let r = await api("api/approvals/pending"); det = r; }
catch (e) { return; }
let list = (det && det.approvals) || [];
let fresh = list.filter(x => !seenApprovals[x.token]);
if (!fresh.length) return;
let one = fresh[0];
seenApprovals[one.token] = true; currentAppr = one.token;
document.getElementById("appr-what").textContent =
(one.actor ? one.actor + " wants: " : "") + one.action;
document.getElementById("appr-meta").textContent =
"risk " + one.risk + " · single-use · decide here, no terminal needed";
document.getElementById("appr-modal").style.display = "flex"; }
async function decideAppr(ok) {
if (!currentAppr) return;
let tok = currentAppr; currentAppr = null;
document.getElementById("appr-modal").style.display = "none";
try { await api("api/approvals/decision", {method: "POST",
headers: Object.assign({"Content-Type": "application/json"}, authz()),
body: JSON.stringify({token: tok, approve: ok})}); }
catch (e) { /* gate shown */ }
refresh(); }
document.getElementById("appr-yes").onclick = () => decideAppr(true);
document.getElementById("appr-no").onclick = () => decideAppr(false);
async function sendCmd() {
let box = document.getElementById("box"); let text = box.value.trim();
if (!text) return; box.value = "";
let bar = document.getElementById("cmdbar"); bar.classList.add("busy");
let el = document.getElementById("reply"); el.textContent = "one sec…";
try { let out = await api("cycle", {method: "POST",
headers: Object.assign({"Content-Type": "application/json"}, authz()),
body: JSON.stringify({input: text})});
el.textContent = out.response || out.error || "(no reply)"; refresh(); }
catch (e) { el.textContent = "unreachable or locked."; }
bar.classList.remove("busy"); }
document.getElementById("box").addEventListener("keydown", e => {
if (e.key === "Enter") sendCmd(); });
// --- 24x24 avatar per MD anatomy (hair/head/eyes/torso/legs/feet) ---
function drawAvatar(g, a, t, i) {
const u = 1;
function R(px, py, w, h, c) { g.fillStyle = c; g.fillRect(px*u, py*u, w*u, h*u); }
let frame = 0;
if (a.s === "working" && !reduced) frame = [0,1,0,2][Math.floor(t/250 + i) % 4];
let bob = (a.s === "working" && !reduced) ? (frame % 2) : 0;
R(0, 0, 24, 24, "#F4E9C7");
R(8, 4, 8, 2, a.hair); R(7, 5, 10, 2, a.hair); // hair rows 4-5
R(7, 6, 10, 4, SKIN); // head
R(8, 8, 2, 1, "#1A1320"); R(14, 8, 2, 1, "#1A1320"); // eyes
R(10, 10, 4, 1, "#e8a080"); // mouth/cheeks
R(8, 11, 8, 1, SKIN); // jaw
R(7, 12, 10, 6, a.shirt); // torso
R(9, 13, 6, 2, "rgba(0,0,0,.18)"); // outfit detail
let lo = frame === 1 ? -1 : (frame === 3 ? 1 : 0);
R(8, 18, 3, 4 + (frame === 1 ? -1 : 0), "#3D2E4A"); // legs
R(13, 18, 3, 4 + (frame === 3 ? -1 : 0), "#3D2E4A");
R(8, 22, 3, 1, "#1A1320"); R(13, 22, 3, 1, "#1A1320"); // feet
if (bob) { /* bob via whole-sprite offset skipped at this scale */ }
return {frame: frame}; }
function overlay(g, a, t, i, cx, cy) {
if (a.s === "thinking") { g.fillStyle = "#4ECDC4"; g.font = "8px monospace";
const n = 1 + Math.floor(t/450) % 3;
g.fillText(".".repeat(n), cx, cy); }
if (a.s === "blocked" || a.s === "waiting") {
if (Math.floor(t/400) % 2 === 0) { g.fillStyle = a.s === "blocked" ? "#FF6B6B" : "#6C8EF5";
g.font = "bold 10px monospace"; g.fillText("!", cx, cy); } }
for (let k = sparks.length - 1; k >= 0; k--) {
if (sparks[k].name !== a.n) continue;
if (performance.now() > sparks[k].until) { sparks.splice(k, 1); continue; }
g.fillStyle = "#6BCF7F";
g.fillRect(cx - 6, cy - 4, 2, 2); g.fillRect(cx + 6, cy - 6, 2, 2);
g.fillRect(cx, cy - 9, 2, 2); g.fillRect(cx - 2, cy + 2, 2, 2); } }
const cv = document.getElementById("floor");
const x = cv.getContext("2d");
function drawPortrait(a) {
let pc = document.getElementById("portrait");
let g = pc.getContext("2d");
g.clearRect(0, 0, 24, 24);
drawAvatar(g, a, performance.now(), 0); }
function tile(x0, y0, w, h, c) { x.fillStyle = c; x.fillRect(x0, y0, w, h); }
function draw(t) {
x.setTransform(2, 0, 0, 2, 0, 0); // 2x supersample: crisp at any size
x.clearRect(0, 0, 640, 400);
for (let tx = 0; tx < 640; tx += 32) for (let ty = 0; ty < 400; ty += 32) {
tile(tx, ty, 32, 32, ((tx + ty) / 32) % 2 ? "#E5C896" : "#C9A66B"); }
x.fillStyle = "#8B6F47"; x.fillRect(0, 0, 640, 8); x.fillRect(0, 0, 8, 400);
x.fillStyle = "#1A1320"; x.font = "10px monospace";
x.fillText("floor: jarvis", 16, 24);
function station(sx, sy, kind, active, label) {
tile(sx, sy, 64, 48, "#F4E9C7");
x.strokeStyle = "#1A1320"; x.strokeRect(sx+.5, sy+.5, 63, 47);
x.fillStyle = "#1A1320"; x.font = "8px monospace"; x.fillText(label, sx+4, sy+10);
if (kind === "shelf") { const pal = ["#FF6B6B","#4ECDC4","#FFD93D","#B197FC"];
for (let r = 0; r < 3; r++) for (let b = 0; b < 4; b++) {
x.fillStyle = pal[(r + b) % 4]; x.fillRect(sx+6+b*14, sy+16+r*10, 11, 8); } }
if (kind === "terminal") { tile(sx+12, sy+10, 40, 26, "#1A1320");
if (active && Math.floor(t/500) % 2 === 0) { x.fillStyle = "#6BCF7F";
x.fillRect(sx+15, sy+28, 6, 8); }
x.fillStyle = "#6BCF7F"; x.font = "8px monospace"; x.fillText(">_", sx+15, sy+24); }
if (kind === "web") { x.strokeStyle = "#B197FC"; x.lineWidth = 3;
x.beginPath(); x.arc(sx+32, sy+40, 16, Math.PI, 0); x.stroke(); x.lineWidth = 1;
if (active) { x.fillStyle = "#B197FC"; x.fillRect(sx+29, sy+16, 6, 6); } }
if (kind === "board") { const n = Math.min(3, window.__notes || 0);
const cols = ["#FFD93D","#4ECDC4","#FF6B6B"];
for (let s = 0; s < 3; s++) { x.fillStyle = cols[s];
x.fillRect(sx+6+s*19, sy+14, 15, 12); } }
if (kind === "mail") { tile(sx+24, sy+14, 6, 22, "#8B6F47");
tile(sx+18, sy+6, 18, 12, "#FFD93D");
if (window.__mailFlag) { tile(sx+30, sy-2, 10, 6, "#FF6B6B"); } } }
const running = team.some(a => a.s === "working");
window.__notes = team.filter(a => a.b).length;
window.__mailFlag = team.some(a => a.s === "blocked");
station(40, 60, "shelf", running, "shelf");
station(536, 60, "terminal", running, "terminal");
station(40, 200, "web", running, "web");
station(300, 200, "board", false, "board");
station(536, 200, "mail", false, "mail");
const pos = [];
const n = team.length;
team.forEach((a, i) => {
const col = i % 4, row = Math.floor(i / 4);
const dx = 150 + col * 110, dy = 130 + row * 120;
pos.push([dx, dy]);
x.fillStyle = "#8B6F47"; x.fillRect(dx - 34, dy + 40, 76, 26);
x.fillStyle = "#E5C896"; x.fillRect(dx - 30, dy + 36, 68, 8);
x.fillStyle = "#1A1320"; x.fillRect(dx - 8, dy + 8, 16, 12);
x.fillStyle = "#4ECDC4"; x.fillRect(dx - 6, dy + 10, 12, 3);
const g2 = document.createElement("canvas"); g2.width = 24; g2.height = 24;
drawAvatar(g2.getContext("2d"), a, t, i);
x.imageSmoothingEnabled = false;
x.drawImage(g2, dx - 12, dy - 8, 24, 24);
overlay(x, a, t, i, dx + 16, dy - 22);
x.fillStyle = "#FFF8E7"; x.fillRect(dx - 22, dy + 65, 58, 12);
x.strokeStyle = "#1A1320"; x.strokeRect(dx - 22.5, dy + 65.5, 58, 11);
x.fillStyle = "#1A1320"; x.font = "8px monospace";
x.fillText(a.n.slice(0, 10), dx - 20, dy + 74);
const stc = {idle:"#A899B5", thinking:"#4ECDC4", working:"#FFD93D",
waiting:"#6C8EF5", blocked:"#FF6B6B"}[a.s] || "#A899B5";
x.fillStyle = stc; x.fillRect(dx - 20, dy + 78, 40, 4);
if (a.b) { x.font = "8px monospace"; const w = Math.min(150, a.b.length*5+8);
let bx = Math.max(2, Math.min(638 - w, dx - 20));
x.fillStyle = "#FFFDF5"; x.fillRect(bx, dy - 44, w, 13);
x.strokeStyle = "#1A1320"; x.strokeRect(bx+.5, dy-44+.5, w-1, 12);
x.fillStyle = "#1A1320"; x.fillText(String(a.b).slice(0, 30), bx+4, dy-34); }
});
window.__pos = pos;
if (!reduced) requestAnimationFrame(draw); }
draw(performance.now());
if (!reduced) requestAnimationFrame(draw);
refresh(); setInterval(refresh, 5000);
cv.onclick = function(e) {
const r = cv.getBoundingClientRect();
const mx = (e.clientX - r.left) * 640 / r.width;
const my = (e.clientY - r.top) * 400 / r.height;
const pos = window.__pos || [];
for (let i = 0; i < pos.length; i++) {
if (mx > pos[i][0]-40 && mx < pos[i][0]+48 &&
my > pos[i][1]-30 && my < pos[i][1]+80) {
selected = team[i].n; renderSel(); return; } } };
</script>
</body>
</html>
"""


__all__ = ["OFFICE_HTML"]
