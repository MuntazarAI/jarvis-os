"""Phone/local remote: speak-or-type from another device.

A single offline HTML shell (public, holds no data) that POSTs to the
existing token-gated `/cycle` endpoint. Same trust model as the board:
the shell is public, every action requires the bearer token as a
header, tokens live in sessionStorage, never URLs.

Serve LAN-only by binding `serve --host <lan-ip>`; the page prints a
reminder. Default stays localhost.
"""

from __future__ import annotations

REMOTE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS &mdash; Remote</title>
<style>
:root { color-scheme: dark; --bg: #0b0e14; --card: #141925;
--line: #263049; --txt: #dbe4f5; --dim: #8b96ad; --acc: #5eb1ef; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--txt);
font: 16px/1.5 system-ui, sans-serif; padding: 16px;
max-width: 700px; margin: 0 auto; }
h1 { font-size: 18px; letter-spacing: 1px; }
#warn { color: var(--dim); font-size: 12px; }
#log { display: flex; flex-direction: column; gap: 8px;
margin: 12px 0; min-height: 200px; }
.msg { background: var(--card); border: 1px solid var(--line);
border-radius: 10px; padding: 10px 12px; white-space: pre-wrap;
word-break: break-word; }
.me { border-color: var(--acc); }
form { display: flex; gap: 8px; }
input { flex: 1; padding: 12px; font-size: 16px;
background: var(--card); color: var(--txt);
border: 1px solid var(--line); border-radius: 10px; }
button { padding: 12px 18px; font-size: 16px; cursor: pointer; }
#gate { position: fixed; inset: 0; background: rgba(0,0,0,.7);
display: none; align-items: center; justify-content: center; }
#gate div { background: var(--card); padding: 24px; border-radius: 12px;
border: 1px solid var(--line); }
</style>
</head>
<body>
<h1>JARVIS // REMOTE</h1>
<div id="warn">Same token as <code>serve</code>. Commands run on your
machine — only use on networks you trust.</div>
<div id="log"><div class="msg">Say it or type it. Replies appear here.
</div></div>
<form onsubmit="return send()">
<input id="box" placeholder="type a command…" autocomplete="off">
<button>Send</button></form>
<div id="gate"><div><h2>API token</h2>
<input id="tok" type="password" placeholder="token">
<button onclick="saveTok()">Unlock</button></div></div>
<script>
let token = sessionStorage.getItem("jarvis-token") || "";
function saveTok() { token = document.getElementById("tok").value;
sessionStorage.setItem("jarvis-token", token);
document.getElementById("gate").style.display = "none"; }
function esc(s) { return String(s).replace(/[&<>"]/g,
c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function add(text, me) { let d = document.createElement("div");
d.className = "msg" + (me ? " me" : ""); d.textContent = text;
let log = document.getElementById("log"); log.appendChild(d);
while (log.children.length > 50) log.firstChild.remove();
window.scrollTo(0, document.body.scrollHeight); }
async function send() {
let box = document.getElementById("box"); let text = box.value.trim();
if (!text) return false; box.value = ""; add(text, true);
add("…", false);
let r; try { r = await fetch("cycle", {method: "POST",
headers: Object.assign({"Content-Type": "application/json"},
token ? {"Authorization": "Bearer " + token} : {}),
body: JSON.stringify({input: text})}); }
catch (e) { add("unreachable — is `serve` running?", false); return false; }
if (r.status === 401) { document.getElementById("gate").style.display =
"flex"; add("locked — enter the API token first.", false); return false; }
let out; try { out = await r.json(); } catch (e) {
add("bad reply from server.", false); return false; }
document.querySelector("#log .msg:last-child").remove();
add(out.response || out.error || "(no reply)", false);
return false; }
if (!token) document.getElementById("gate").style.display = "flex";
</script>
</body>
</html>
"""


__all__ = ["REMOTE_HTML"]
