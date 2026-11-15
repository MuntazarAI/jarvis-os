/* The Command Centre: fills itself with this person's real JARVIS.
 *
 * Nothing here is invented. Every number comes from /api/home, which
 * reads the same subsystems the assistant itself uses.
 */

const $ = (id) => document.getElementById(id);
let gateMode = "signup";

function go(path) { location.href = path; }
function esc(s) {
  return String(s === undefined || s === null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ---------- sign in ---------- */
function toggleMode() {
  gateMode = gateMode === "signup" ? "login" : "signup";
  $("err").textContent = "";
  $("gatebtn").textContent = gateMode === "signup" ? "Create account" : "Log in";
  $("switch").textContent = gateMode === "signup"
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
  try {
    const res = await fetch("/api/" + gateMode, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({email: email, password: password}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      $("err").textContent = data.error || "Something went wrong.";
      return;
    }
    $("gate").style.display = "none";
    $("avatar").textContent = (data.email || "?").charAt(0).toUpperCase();
    load();
  } catch (e) {
    $("err").textContent = "Cannot reach the server.";
  } finally {
    $("gatebtn").disabled = false;
  }
}

/* ---------- the ask box ---------- */
function askBox() {
  const input = $("ask");
  input.focus();
  input.scrollIntoView({behavior: "smooth", block: "center"});
}

async function ask() {
  const input = $("ask");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  $("answer").textContent = "Thinking…";
  $("answer").style.color = "#8fb8cf";
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: text}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      $("answer").textContent = data.error || "Something went wrong.";
      $("answer").style.color = "#ff6874";
      return;
    }
    $("answer").textContent = data.reply || "";
    $("answer").style.color = "#cbe7f5";
    load();
  } catch (e) {
    $("answer").textContent = "Cannot reach the server.";
    $("answer").style.color = "#ff6874";
  }
}

/* ---------- filling the room ---------- */
function fillAgents(agents) {
  agents.forEach((agent, index) => {
    const card = document.querySelector('[data-agent="' + (index + 1) + '"]');
    if (!card) return;
    const label = card.querySelector(".agent-label");
    if (!label) return;
    const state = String(agent.state || "idle").toLowerCase();
    const busy = state !== "idle" && state !== "unknown" && state !== "";
    label.querySelector(".who").textContent =
      (agent.role || "") + " · " + (busy ? "WORKING" : "IDLE");
    label.querySelector(".who").style.color = busy ? "#61d7c0" : "#7d95a8";
    label.querySelector(".about").textContent = agent.about || "";
    const stateLine = label.querySelector(".state");
    stateLine.textContent = busy ? "● Active" : "○ Idle";
    stateLine.style.color = busy ? "#21e5a1" : "#7d95a8";
    const task = label.querySelector(".task");
    task.textContent = agent.task
      ? "Task: " + agent.task
      : (busy ? "Task: working" : "Task: waiting");
    task.style.color = agent.task ? "#e3a746" : "#6f899b";
  });
}

function fillMission(mission) {
  const progress = Math.max(0, Math.min(100, Number(mission.progress) || 0));
  $("mission-title").textContent = mission.title || "No mission yet";
  $("mission-pct").textContent = progress + "%";
  $("mission-bar").style.width = progress + "%";
  $("mc-title").textContent = mission.title || "No mission yet";
  $("mc-pct").textContent = progress + "%";
  $("mc-bar").style.width = progress + "%";
  $("mc-state").textContent = progress ? "ACTIVE" : "IDLE";
  $("mc-priority").textContent = mission.priority || "—";
  $("mc-eta").textContent = mission.eta || "—";
  const steps = mission.steps || [];
  $("mc-desc").textContent = mission.description ||
    (steps.length ? "Steps: " + steps.map((s) => s.text).join(" · ")
                   : "Nothing is running yet. Ask JARVIS for something to do.");
  $("mc-list").innerHTML = steps.map((step) => {
    const cls = step.state === "done" ? "done"
      : (step.state === "active" ? "active" : "");
    const mark = step.state === "done" ? "✓ Completed"
      : (step.state === "active" ? "● In progress" : "Pending");
    const colour = step.state === "done" ? "#5fe6b7"
      : (step.state === "active" ? "#36cfff" : "#8ba0b0");
    return '<div class="check ' + cls + '"><i></i>' + esc(step.text) +
      '<span style="color:' + colour + '">' + mark + '</span></div>';
  }).join("");
}

function fillTasks(tasks, counts) {
  const tabs = [["Running", counts.tasks_running || 0],
                ["Queued", counts.tasks_queued || 0],
                ["Paused", 0], ["Failed", 0], ["Total", tasks.length]];
  $("queue-tabs").innerHTML = tabs.map((t, i) =>
    '<span' + (i === 0 ? ' style="color:#48d8ff;background:#0a2337"' : "") + ">" +
    t[0] + " " + t[1] + "</span>").join("");
  const rows = (tasks || []).slice(0, 4).map((task) =>
    '<div class="metric"><i class="mi"></i><b>' + esc(task.title || "Task") +
    '<br><small>' + esc(task.role || "") + '</small></b><small>' +
    (task.progress || 0) + '%</small><div class="tiny"><i style="width:' +
    (task.progress || 0) + '%"></i></div></div>').join("");
  $("queue").innerHTML = rows ||
    '<div class="metric"><i class="mi" style="background:#5a6b7a"></i><b>Nothing running</b></div>';
}

function fillEvents(events) {
  $("activity").innerHTML = (events || []).map((event) =>
    '<div class="row"><span class="blue">● ' + esc(event.type) +
    '</span><small>' + (event.count || 0) + '</small></div>').join("") ||
    '<div class="row"><span>Nothing yet</span></div>';
  $("live-list").innerHTML = (events || []).slice(0, 4).map((event) =>
    '<div>🟢 ' + esc(event.type) + '</div>').join("") ||
    '<div>waiting…</div>';
}

function fillMemory(memory) {
  // The palace's rooms are the real areas of this person's memory.
  const rooms = memory.rooms || {};
  const tiers = memory.tiers || {};
  const rows = Object.keys(rooms).slice(0, 8);
  let html = rows.map((name) =>
    '<span>' + esc(name) + ' · ' + esc(rooms[name]) + '</span>').join("");
  if (!html) {
    html = Object.keys(tiers).slice(0, 8).map((name) =>
      '<span>' + esc(name) + ' · ' + esc(tiers[name]) + '</span>').join("");
  }
  if (!html) html = '<span>Empty</span>';
  $("memory").innerHTML = html;
}

function fillGraph(graph) {
  const rows = [
    ["Nodes", graph.nodes], ["Edges", graph.edges],
    ["Identities", graph.identities],
  ].filter((row) => row[1] !== undefined);
  $("graph").innerHTML = rows.map((row) =>
    '<div class="row"><span>' + esc(row[0]) + '</span><b>' +
    esc(row[1]) + '</b></div>').join("") ||
    '<div class="row"><span>No graph yet</span></div>';
}

function fillTools(tools) {
  $("tools").innerHTML = (tools || []).map((tool) =>
    '<div class="row"><span>◉ ' + esc(tool.name) + '<br><small>' +
    esc(tool.detail || "") + '</small></span><b class="' +
    (tool.online ? "green" : "red") + '">' +
    (tool.online ? "● Online" : "● Offline") + '</b></div>').join("");
}

function fillSystem(system) {
  const rows = [
    ["CPU", system.cpu + "%", system.cpu],
    ["Memory", system.memory + "%", system.memory],
    ["Disk", system.disk + "%", system.disk],
  ];
  let html = rows.map((row) =>
    '<div class="metric"><i class="mi"></i><b>' + row[0] +
    '</b><div class="tiny"><i style="width:' + row[2] +
    '%"></i></div><small>' + row[1] + '</small></div>').join("");
  html += '<div class="metric"><i class="mi"></i><b>Network</b><small>' +
    esc(system.network) + '</small></div>';
  html += '<div class="metric"><i class="mi"></i><b>Temperature</b><small>' +
    esc(system.temperature) + '</small></div>';
  html += '<div class="metric"><i class="mi"></i><b>Uptime</b><small>' +
    esc(system.uptime) + '</small></div>';
  $("system").innerHTML = html;
}

async function load() {
  let data;
  try {
    const res = await fetch("/api/home");
    if (res.status === 401) {
      $("gate").style.display = "flex";
      return;
    }
    if (!res.ok) return;
    data = await res.json();
  } catch (e) {
    $("operational").textContent = "● Server unreachable";
    $("operational").style.color = "#ff6874";
    return;
  }
  const counts = data.counts || {};
  $("headline").innerHTML = "<b>" + (counts.agents_active || 0) +
    " active agents</b>　•　" + (counts.tasks_running || 0) +
    " tasks running　•　" + (counts.tasks_queued || 0) + " queued";
  $("operational").textContent = "● All Systems Operational";
  $("operational").style.color = "#43edb0";
  $("online").textContent = data.service && data.service.running === false
    ? "System Offline" : "System Online";
  fillAgents(data.agents || []);
  fillMission(data.mission || {});
  fillTasks(data.tasks || [], counts);
  fillEvents(data.events || []);
  fillMemory(data.memory || {});
  fillGraph(data.graph || {});
  fillTools(data.tools || []);
  fillSystem(data.system || {});
}

function tickClock() {
  const now = new Date();
  $("time").textContent = String(now.getHours()).padStart(2, "0") + ":" +
    String(now.getMinutes()).padStart(2, "0");
  $("date").textContent = now.toLocaleDateString(undefined,
    {weekday: "short", day: "numeric", month: "short", year: "numeric"});
}

(async () => {
  tickClock();
  setInterval(tickClock, 20000);
  try {
    const res = await fetch("/api/me");
    if (res.ok) {
      const data = await res.json();
      $("avatar").textContent = (data.email || "?").charAt(0).toUpperCase();
      $("gate").style.display = "none";
    } else {
      $("gate").style.display = "flex";
    }
  } catch (e) {
    $("gate").style.display = "flex";
  }
  load();
  setInterval(load, 5000);
})();
