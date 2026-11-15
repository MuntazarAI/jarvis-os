"""The public JARVIS chat page.

One file, no CDN, no external fonts: it works on a plane, on a phone
and behind a slow connection.

The shape is the one people already know: a list of conversations on
the left, the conversation in the middle, a box to type in at the
bottom. What is inside the box is JARVIS — the same brain and the
same British voice as the command line, with this person's own
memory.
"""

from __future__ import annotations

CHAT_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>JARVIS</title>
<style>
:root {
  --bg: #0b0e14; --panel: #11151d; --card: #161b25; --line: #232a36;
  --text: #e8edf5; --dim: #8b95a7; --accent: #4d8df6; --accent-soft: #1d2b45;
  --good: #46c46a; --warn: #e0a83c; --bad: #f26d6d;
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15.5px/1.6 -apple-system, "Segoe UI", Roboto, "Helvetica Neue",
        Arial, sans-serif;
  overflow: hidden;
}
button { font: inherit; }
a { color: var(--accent); }

/* ---------- layout ---------- */
.app { display: flex; height: 100vh; }

.sidebar {
  width: 272px; flex: 0 0 272px; background: var(--panel);
  border-right: 1px solid var(--line); display: flex; flex-direction: column;
  transition: transform .18s ease;
}
.brand {
  display: flex; align-items: center; gap: 10px; padding: 16px 16px 12px;
}
.brand .mark {
  width: 30px; height: 30px; border-radius: 9px; background: var(--accent);
  color: #fff; font-weight: 800; font-size: 15px; display: flex;
  align-items: center; justify-content: center; letter-spacing: .5px;
}
.brand .name { font-weight: 700; letter-spacing: 3px; font-size: 15px; }
.newchat {
  margin: 4px 12px 10px; padding: 10px 13px; background: var(--accent-soft);
  border: 1px solid var(--line); color: var(--text); border-radius: 10px;
  cursor: pointer; text-align: left; width: calc(100% - 24px);
}
.newchat:hover { border-color: var(--accent); }
.convos { flex: 1; overflow-y: auto; padding: 0 8px 10px; }
.convo {
  display: flex; align-items: center; gap: 8px; padding: 8px 10px;
  border-radius: 9px; cursor: pointer; color: var(--dim); font-size: 14px;
}
.convo:hover { background: var(--card); color: var(--text); }
.convo.active { background: var(--card); color: var(--text); }
.convo .t { flex: 1; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.convo .x { opacity: 0; border: 0; background: none; color: var(--dim);
  cursor: pointer; font-size: 15px; padding: 0 4px; }
.convo:hover .x { opacity: 1; }
.sidefoot {
  border-top: 1px solid var(--line); padding: 10px 12px; color: var(--dim);
  font-size: 13px; display: flex; align-items: center; gap: 8px;
}
.sidefoot .mail { flex: 1; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.sidefoot button { background: none; border: 1px solid var(--line);
  color: var(--dim); border-radius: 7px; padding: 4px 8px; cursor: pointer;
  font-size: 12px; }
.sidefoot button:hover { color: var(--text); border-color: var(--accent); }

.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.topbar {
  display: flex; align-items: center; gap: 10px; padding: 11px 16px;
  border-bottom: 1px solid var(--line); background: var(--panel);
}
.topbar .title { font-weight: 600; }
.topbar .spacer { flex: 1; }
.topbar button {
  background: var(--card); border: 1px solid var(--line); color: var(--text);
  border-radius: 8px; padding: 6px 11px; cursor: pointer; font-size: 13px;
}
.topbar button.on { border-color: var(--accent); color: var(--accent); }
.topbar button:hover { border-color: var(--accent); }
#menu { display: none; }

.log { flex: 1; overflow-y: auto; padding: 26px 18px 150px; }
.wrap { max-width: 820px; margin: 0 auto; }

.msg { display: flex; gap: 13px; margin-bottom: 26px; }
.msg .avatar {
  flex: 0 0 30px; height: 30px; border-radius: 9px; font-size: 12px;
  display: flex; align-items: center; justify-content: center;
  background: var(--line); color: var(--dim); font-weight: 700; margin-top: 2px;
}
.msg.me .avatar { background: var(--accent); color: #fff; }
.msg.ai .avatar { background: var(--good); color: #06240e; }
.bubble { flex: 1; min-width: 0; }
.bubble p { margin: 0 0 12px; }
.bubble p:last-child { margin-bottom: 0; }
.bubble ul, .bubble ol { margin: 0 0 12px; padding-left: 22px; }
.bubble li { margin-bottom: 5px; }
.bubble h1, .bubble h2, .bubble h3 { font-size: 17px; margin: 16px 0 8px; }
.bubble code {
  background: var(--card); border: 1px solid var(--line); border-radius: 5px;
  padding: 1px 5px; font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 13px;
}
.bubble pre {
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; overflow-x: auto; margin: 0 0 12px;
}
.bubble pre code { background: none; border: 0; padding: 0; }
.bubble .tools {
  color: var(--dim); font-size: 13px; margin-bottom: 8px;
}
.copy {
  opacity: 0; background: var(--card); border: 1px solid var(--line);
  color: var(--dim); border-radius: 6px; padding: 3px 8px; font-size: 12px;
  cursor: pointer; margin-top: 4px;
}
.msg:hover .copy { opacity: 1; }
.copy:hover { color: var(--text); }

.approval {
  border: 1px solid var(--warn); border-radius: 12px; padding: 13px 15px;
  background: rgba(224,168,60,.08); margin: 0 0 12px;
}
.approval .what { font-weight: 600; margin-bottom: 4px; }
.approval .risk { color: var(--warn); font-size: 12px; text-transform:
  uppercase; letter-spacing: 1px; margin-bottom: 9px; }
.approval button {
  background: var(--accent); color: #fff; border: 0; border-radius: 8px;
  padding: 7px 15px; cursor: pointer; margin-right: 8px;
}
.approval button.no { background: var(--card); color: var(--text);
  border: 1px solid var(--line); }

.empty { text-align: center; padding: 46px 10px 20px; }
.empty .big { font-size: 26px; font-weight: 300; letter-spacing: 6px;
  margin-bottom: 8px; }
.empty p { color: var(--dim); }
.chips { display: flex; gap: 9px; flex-wrap: wrap; justify-content: center;
  margin-top: 22px; }
.chips button {
  background: var(--card); border: 1px solid var(--line); color: var(--text);
  border-radius: 999px; padding: 8px 15px; cursor: pointer; font-size: 13.5px;
}
.chips button:hover { border-color: var(--accent); }

.composer {
  border-top: 1px solid var(--line); background: var(--panel);
  padding: 12px 16px 16px;
}
.composer .row { display: flex; gap: 9px; align-items: flex-end;
  max-width: 820px; margin: 0 auto; }
textarea {
  flex: 1; resize: none; background: var(--bg); color: var(--text);
  border: 1px solid var(--line); border-radius: 13px; padding: 13px 15px;
  font: inherit; max-height: 220px; min-height: 50px; outline: none;
}
textarea:focus { border-color: var(--accent); }
.iconbtn {
  background: var(--bg); border: 1px solid var(--line); color: var(--text);
  border-radius: 13px; width: 50px; height: 50px; cursor: pointer;
  font-size: 18px; display: flex; align-items: center; justify-content: center;
}
.iconbtn:hover { border-color: var(--accent); }
.iconbtn.live { border-color: var(--bad); color: var(--bad); }
.send { background: var(--accent); color: #fff; border: 0; }
.send:disabled { opacity: .45; }
.hint { color: var(--dim); font-size: 12.5px; text-align: center;
  margin-top: 8px; }
.dots span {
  display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: var(--dim); margin-right: 4px; animation: bounce 1.2s infinite;
}
.dots span:nth-child(2) { animation-delay: .15s; }
.dots span:nth-child(3) { animation-delay: .3s; }
@keyframes bounce { 0%,60%,100% { opacity: .25; } 30% { opacity: 1; } }

/* ---------- sign in ---------- */
#gate {
  position: fixed; inset: 0; background: var(--bg); z-index: 20;
  display: flex; align-items: center; justify-content: center; padding: 24px;
  overflow-y: auto;
}
.gate {
  width: 100%; max-width: 400px; text-align: center;
}
.gate .mark {
  width: 56px; height: 56px; border-radius: 16px; background: var(--accent);
  color: #fff; font-weight: 800; font-size: 26px; display: flex;
  align-items: center; justify-content: center; margin: 0 auto 18px;
}
.gate h1 { font-size: 27px; letter-spacing: 7px; font-weight: 400;
  margin: 0 0 6px; }
.gate .tag { color: var(--dim); margin: 0 0 26px; }
.gate ul { text-align: left; color: var(--dim); font-size: 14px;
  line-height: 1.9; list-style: none; padding: 0; margin: 0 0 24px; }
.gate li::before { content: "\\2713"; color: var(--good); margin-right: 9px; }
.gate input {
  width: 100%; background: var(--card); color: var(--text);
  border: 1px solid var(--line); border-radius: 11px; padding: 13px 15px;
  font: inherit; margin-bottom: 10px;
}
.gate input:focus { border-color: var(--accent); outline: none; }
.gate button.go {
  width: 100%; background: var(--accent); color: #fff; border: 0;
  border-radius: 11px; padding: 13px; font-size: 15px; cursor: pointer;
  margin-top: 4px;
}
.gate .switch { color: var(--dim); font-size: 14px; margin-top: 16px;
  cursor: pointer; }
.gate .switch:hover { color: var(--text); }
#err { color: var(--bad); font-size: 14px; min-height: 20px; }
.scrim { display: none; }

/* ---------- account panel ---------- */
#sheet {
  position: fixed; inset: 0; background: rgba(0,0,0,.55); z-index: 30;
  display: none; align-items: center; justify-content: center; padding: 24px;
}
#sheet .panel {
  background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 24px; width: 100%; max-width: 380px;
}
#sheet h3 { margin: 0 0 14px; font-size: 17px; }
#sheet input {
  width: 100%; background: var(--bg); color: var(--text);
  border: 1px solid var(--line); border-radius: 10px; padding: 11px 13px;
  font: inherit; margin-bottom: 10px;
}
#sheet button {
  background: var(--accent); color: #fff; border: 0; border-radius: 9px;
  padding: 10px 15px; cursor: pointer; margin-right: 8px;
}
#sheet button.ghost { background: var(--card); color: var(--text);
  border: 1px solid var(--line); }
#sheet .danger { color: var(--bad); }

/* ---------- phone ---------- */
@media (max-width: 780px) {
  .sidebar {
    position: fixed; z-index: 25; top: 0; bottom: 0; left: 0;
    transform: translateX(-100%); box-shadow: 0 0 40px rgba(0,0,0,.5);
  }
  body.nav-open .sidebar { transform: translateX(0); }
  body.nav-open .scrim {
    display: block; position: fixed; inset: 0; background: rgba(0,0,0,.5);
    z-index: 24;
  }
  #menu { display: inline-flex; }
  .log { padding: 18px 13px 140px; }
  .topbar .title { font-size: 14px; }
}
</style>
</head>
<body>

<div class="app">
  <div class="scrim" onclick="document.body.classList.remove('nav-open')"></div>

  <aside class="sidebar">
    <div class="brand"><div class="mark">J</div><div class="name">JARVIS</div></div>
    <button class="newchat" onclick="newChat()">+ &nbsp;New chat</button>
    <div class="convos" id="convos"></div>
    <div class="sidefoot">
      <span class="mail" id="mail"></span>
      <button onclick="openSheet()">Account</button>
      <button onclick="logout()">Exit</button>
    </div>
  </aside>

  <main class="main">
    <div class="topbar">
      <button id="menu" onclick="document.body.classList.toggle('nav-open')">☰</button>
      <span class="title" id="chatname">New chat</span>
      <span class="spacer"></span>
      <button id="voicebtn" class="on" onclick="toggleVoice()">🔊 Voice</button>
    </div>

    <div class="log" id="log"><div class="wrap" id="logwrap"></div></div>

    <div class="composer">
      <div class="row">
        <button class="iconbtn" id="mic" title="Talk">&#9675;</button>
        <textarea id="input" rows="1"
                  placeholder="Message JARVIS…"></textarea>
        <button class="iconbtn send" id="send">➤</button>
      </div>
      <div class="hint">JARVIS can make mistakes. Check anything important.</div>
    </div>
  </main>
</div>

<div id="sheet"><div class="panel">
  <h3>Your account</h3>
  <p id="sheetmail" style="color:var(--dim);font-size:14px"></p>
  <input id="pwcur" type="password" placeholder="current password">
  <input id="pwnew" type="password" placeholder="new password (10+ chars)">
  <div id="sheeterr" style="color:var(--bad);font-size:13px;min-height:18px"></div>
  <button onclick="changePassword()">Change password</button>
  <button class="ghost danger" onclick="deleteAccount()">Delete account</button>
  <button class="ghost" onclick="closeSheet()">Close</button>
</div></div>

<div id="gate"><div class="gate">
  <div class="mark">J</div>
  <h1>JARVIS</h1>
  <p class="tag">Your own AI assistant. It remembers, it works for you,
     and it speaks.</p>
  <ul>
    <li>Answers questions and does real work with your say-so</li>
    <li>Remembers what you tell it — only you can see it</li>
    <li>Speaks in a natural British voice</li>
  </ul>
  <input id="email" type="email" placeholder="email" autocomplete="email">
  <input id="password" type="password" placeholder="password (10+ characters)"
         autocomplete="current-password">
  <div id="err"></div>
  <button class="go" id="gatebtn" onclick="submitGate()">Create account</button>
  <div class="switch" id="switch" onclick="toggleMode()">
    Already have an account? Log in
  </div>
</div></div>

<script>
let mode = "signup";
let busy = false;
let voice = true;
let current = null;
let controller = null;

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);

function esc(s) {
  return String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* A small markdown renderer. The text is escaped first, so nothing
   from the model can become HTML. */
function md(text) {
  let out = esc(text);
  const blocks = [];
  out = out.replace(/```([\\s\\S]*?)```/g, (m, code) => {
    blocks.push(code.replace(/^[ \\t]*\\n/, ""));
    return "\\u0000CODE" + (blocks.length - 1) + "\\u0000";
  });
  out = out.replace(/^### (.*)$/gm, "<h3>$1</h3>")
           .replace(/^## (.*)$/gm, "<h2>$1</h2>")
           .replace(/^# (.*)$/gm, "<h1>$1</h1>");
  out = out.replace(/`([^`\\n]+)`/g, "<code>$1</code>");
  out = out.replace(/\\*\\*([^*]+)\\*\\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\\*([^*\\n]+)\\*/g, "$1<em>$2</em>");
  out = out.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^)\\s]+)\\)/g,
                    '<a href="$2" target="_blank" rel="noopener">$1</a>');
  out = out.split("\\n");
  const lines = [];
  let list = null;
  for (const line of out) {
    const bullet = line.match(/^\\s*[-*]\\s+(.*)$/);
    const numbered = line.match(/^\\s*\\d+[.)]\\s+(.*)$/);
    if (bullet || numbered) {
      const tag = bullet ? "ul" : "ol";
      if (list !== tag) { if (list) lines.push("</" + list + ">");
        list = tag; lines.push("<" + tag + ">"); }
      lines.push("<li>" + (bullet ? bullet[1] : numbered[1]) + "</li>");
      continue;
    }
    if (list) { lines.push("</" + list + ">"); list = null; }
    if (line.trim() === "") { lines.push(""); continue; }
    lines.push("<p>" + line + "</p>");
  }
  if (list) lines.push("</" + list + ">");
  out = lines.join("\\n").replace(/<p>\\s*<\\/p>/g, "");
  out = out.replace(/\\u0000CODE(\\d+)\\u0000/g,
                    (m, i) => "<pre><code>" + blocks[Number(i)] + "</code></pre>");
  return out;
}

async function api(path, data) {
  const opts = { headers: {"Content-Type": "application/json"} };
  if (data !== undefined) {
    opts.method = "POST";
    opts.body = JSON.stringify(data);
  }
  const res = await fetch(path, opts);
  let payload = {};
  try { payload = await res.json(); } catch (e) {}
  return { ok: res.ok, status: res.status, data: payload };
}

/* ---------- sign in ---------- */
function toggleMode() {
  mode = mode === "signup" ? "login" : "signup";
  $("err").textContent = "";
  $("gatebtn").textContent = mode === "signup" ? "Create account" : "Log in";
  $("switch").textContent = mode === "signup"
    ? "Already have an account? Log in"
    : "New here? Create an account";
}

async function submitGate() {
  const email = $("email").value.trim();
  const password = $("password").value;
  $("err").textContent = "";
  if (!email || !password) {
    $("err").textContent = "Enter your email and password.";
    return;
  }
  $("gatebtn").disabled = true;
  const res = await api("/api/" + mode, {email: email, password: password});
  $("gatebtn").disabled = false;
  if (!res.ok) {
    $("err").textContent = res.data.error || "Something went wrong.";
    return;
  }
  $("gate").style.display = "none";
  await start(res.data.email);
}

async function logout() {
  try { await api("/api/logout", {}); } catch (e) {}
  location.reload();
}

/* ---------- conversations ---------- */
async function loadConversations() {
  const res = await api("/api/conversations");
  const box = $("convos");
  box.innerHTML = "";
  (res.data.conversations || []).forEach((c) => {
    const row = document.createElement("div");
    row.className = "convo" + (current && c.id === current ? " active" : "");
    row.innerHTML = '<div class="t"></div><button class="x" title="Delete">×</button>';
    row.querySelector(".t").textContent = c.title || "New chat";
    row.onclick = (e) => {
      if (e.target.classList.contains("x")) { deleteConv(c.id); return; }
      openConv(c.id);
    };
    box.appendChild(row);
  });
}

async function newChat() {
  const res = await api("/api/conversations", {title: ""});
  current = res.data.conversation ? res.data.conversation.id : null;
  $("logwrap").innerHTML = welcome();
  $("chatname").textContent = "New chat";
  await loadConversations();
  $("input").focus();
}

async function openConv(id) {
  current = id;
  const res = await api("/api/conversations/" + id);
  if (!res.ok) return;
  const conv = res.data.conversation || {};
  $("chatname").textContent = conv.title || "New chat";
  const wrap = $("logwrap");
  wrap.innerHTML = "";
  const turns = res.data.turns || [];
  if (!turns.length) { wrap.innerHTML = welcome(); }
  turns.forEach((t) => addTurn(t.role === "user" ? "me" : "ai", t.text));
  await loadConversations();
  $("input").focus();
}

async function deleteConv(id) {
  await api("/api/conversations/" + id, {});
  if (current === id) { current = null; $("logwrap").innerHTML = welcome(); }
  await loadConversations();
}

function welcome() {
  return '<div class="empty"><div class="big">JARVIS</div>' +
    '<p>Ask anything. I remember what you tell me and I can work for you.</p>' +
    '<div class="chips">' +
    '<button onclick="ask(\\'What can you do for me?\\')">What can you do?</button>' +
    '<button onclick="ask(\\'Help me plan my day\\')">Plan my day</button>' +
    '<button onclick="ask(\\'Remember that my favourite number is 42\\')">Test my memory</button>' +
    '<button onclick="ask(\\'Research the latest news in AI\\')">Research something</button>' +
    '</div></div>';
}

function ask(text) { $("input").value = text; send(); }

/* ---------- messages ---------- */
function addTurn(kind, text, tools) {
  const wrap = $("logwrap");
  const empty = wrap.querySelector(".empty");
  if (empty) empty.remove();
  const div = document.createElement("div");
  div.className = "msg " + kind;
  const who = kind === "me" ? "You" : "JARVIS";
  div.innerHTML = '<div class="avatar"></div><div class="bubble"></div>';
  div.querySelector(".avatar").textContent = who === "You" ? "Y" : "J";
  const bubble = div.querySelector(".bubble");
  if (tools && tools.length) {
    const t = document.createElement("div");
    t.className = "tools";
    t.textContent = "Used: " + tools.join(", ");
    bubble.appendChild(t);
  }
  const body = document.createElement("div");
  body.innerHTML = md(text);
  bubble.appendChild(body);
  if (kind === "ai") {
    const copy = document.createElement("button");
    copy.className = "copy";
    copy.textContent = "Copy";
    copy.onclick = async () => {
      try { await navigator.clipboard.writeText(text); copy.textContent = "Copied"; }
      catch (e) { copy.textContent = "Copy"; }
      setTimeout(() => { copy.textContent = "Copy"; }, 1400);
    };
    bubble.appendChild(copy);
  }
  wrap.appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
  return div;
}

function addApproval(a) {
  const wrap = $("logwrap");
  const div = document.createElement("div");
  div.className = "approval";
  div.innerHTML = '<div class="risk"></div><div class="what"></div>';
  div.querySelector(".risk").textContent = "Needs your approval · " + (a.risk || "?");
  div.querySelector(".what").textContent = a.action || "an action";
  const yes = document.createElement("button");
  yes.textContent = "Allow";
  yes.onclick = () => decide(a.token, "approve", div);
  const no = document.createElement("button");
  no.className = "no";
  no.textContent = "Deny";
  no.onclick = () => decide(a.token, "deny", div);
  div.appendChild(yes); div.appendChild(no);
  wrap.appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
}

async function decide(token, decision, node) {
  const res = await api("/api/approvals", {token: token, decision: decision});
  node.innerHTML = decision === "approve"
    ? '<div class="what">Approved.</div>'
    : '<div class="what">Denied.</div>';
}

/* ---------- sending ---------- */
async function send() {
  const input = $("input");
  const text = input.value.trim();
  if (!text || busy) return;
  busy = true;
  $("send").disabled = false;
  input.value = "";
  input.style.height = "auto";
  addTurn("me", text);
  const pending = addTurn("ai", '<span class="dots"><span></span>' +
    '<span></span><span></span></span>');
  controller = new AbortController();
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: text}),
      signal: controller.signal,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      pending.querySelector(".bubble").innerHTML =
        md(data.error || "Something went wrong.");
      return;
    }
    pending.querySelector(".bubble").innerHTML = md(data.reply || "");
    if (data.tools && data.tools.length) {
      const t = document.createElement("div");
      t.className = "tools";
      t.textContent = "Used: " + data.tools.join(", ");
      pending.querySelector(".bubble").prepend(t);
    }
    (data.approvals || []).forEach(addApproval);
    if (voice && data.speak !== false) speak(data.reply || "");
    await loadConversations();
  } catch (e) {
    if (e.name === "AbortError") {
      pending.querySelector(".bubble").textContent = "Stopped.";
    } else {
      pending.querySelector(".bubble").textContent =
        "Cannot reach the server. Check your connection.";
    }
  } finally {
    busy = false;
    controller = null;
    $("input").focus();
  }
}

function toggleVoice() {
  voice = !voice;
  $("voicebtn").classList.toggle("on", voice);
}

/* ---------- speech ---------- */
async function speak(text) {
  if (!text) return;
  try {
    const res = await fetch("/api/speak", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: text}),
    });
    if (!res.ok) return;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.play().catch(() => {});
    audio.onended = () => URL.revokeObjectURL(url);
  } catch (e) { /* speaking is a bonus, never a failure */ }
}

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!SR) {
  $("mic").style.display = "none";
} else {
  const rec = new SR();
  rec.lang = "en-GB";
  rec.interimResults = false;
  rec.continuous = false;
  rec.onresult = (e) => {
    $("input").value = ($("input").value + " " +
      e.results[0][0].transcript).trim();
  };
  rec.onend = () => $("mic").classList.remove("live");
  $("mic").onclick = () => {
    if (rec.state === "listening") { rec.stop(); return; }
    try { rec.start(); $("mic").classList.add("live"); } catch (e) {}
  };
}

/* ---------- account ---------- */
function openSheet() {
  $("sheetmail").textContent = $("mail").textContent;
  $("sheet").style.display = "flex";
}
function closeSheet() { $("sheet").style.display = "none"; }

async function changePassword() {
  $("sheeterr").textContent = "";
  const res = await api("/api/account/password", {
    current: $("pwcur").value, new: $("pwnew").value});
  if (!res.ok) { $("sheeterr").textContent = res.data.error || "Failed."; return; }
  $("pwcur").value = ""; $("pwnew").value = "";
  $("sheeterr").style.color = "var(--good)";
  $("sheeterr").textContent = "Password changed.";
}

async function deleteAccount() {
  if (!confirm("Delete your account and everything JARVIS remembers? " +
               "This cannot be undone.")) return;
  await api("/api/account/delete", {});
  location.reload();
}

/* ---------- wiring ---------- */
$("send").onclick = send;
$("input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});
$("input").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(220, e.target.scrollHeight) + "px";
});

async function start(email) {
  $("mail").textContent = email || "";
  $("gate").style.display = "none";
  const res = await api("/api/conversations");
  const list = res.data.conversations || [];
  if (list.length) {
    await openConv(list[0].id);
  } else {
    await newChat();
  }
}

(async () => {
  const res = await api("/api/me");
  if (res.ok) { await start(res.data.email); }
  else { $("gate").style.display = "flex"; }
})();
</script>
</body>
</html>
"""

__all__ = ["CHAT_HTML"]
