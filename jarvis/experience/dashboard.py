"""Dashboard HTML generation from real JARVIS state.

Renders an ExperienceView into a dark-themed HTML dashboard. All data comes
from the structured snapshot — no secrets, tokens, or raw credentials.
"""

from __future__ import annotations

from html import escape
from typing import Any

from .view import ExperienceView


def render_dashboard(view: ExperienceView) -> str:
    """Render an HTML dashboard from an ExperienceView snapshot.

    All values are HTML-escaped. No secrets, approval tokens, or credentials
    are ever included.
    """
    s = view.to_dict()
    posture_class = {
        "clear": "posture-clear",
        "review": "posture-review",
        "attention": "posture-attention",
        "critical": "posture-critical",
    }.get(s["posture"], "posture-unknown")

    health = s.get("health", {}) if isinstance(s.get("health"), dict) else {}
    checks = health.get("subsystems", {}) if isinstance(health, dict) else {}

    rows: list[str] = []
    rows.append(
        f'<tr><td class="label">Memory total</td><td class="value">{s["memory_total"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Memory live</td><td class="value">{s["memory_live"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Memory archived</td><td class="value">{s["memory_archived"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">World entities</td><td class="value">{s["world_entities"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">World events</td><td class="value">{s["world_events"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">World rooms</td><td class="value">{s["world_rooms"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Agents total</td><td class="value">{s["agents_total"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Agents idle</td><td class="value">{s["agents_idle"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Agents working</td><td class="value">{s["agents_working"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Agents failed</td><td class="value">{s["agents_failed"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Tasks total</td><td class="value">{s["tasks_total"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Tasks queued</td><td class="value">{s["tasks_queued"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Tasks running</td><td class="value">{s["tasks_running"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Tasks completed</td><td class="value">{s["tasks_completed"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Tasks failed</td><td class="value">{s["tasks_failed"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Pending approvals</td><td class="value">{s["pending_approvals"]}</td></tr>'
    )
    rows.append(
        f'<tr><td class="label">Emergency stop</td><td class="value">{bool(s["emergency_stop"])}</td></tr>'
    )

    check_rows: list[str] = []
    if isinstance(checks, dict):
        for name, ok in checks.items():
            status = "ok" if ok else "missing"
            check_rows.append(
                f'<tr><td class="label">{escape(str(name))}</td>'
                f'<td class="value status-{status}">{status}</td></tr>'
            )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS-OS · Experience</title>
<style>
:root{{color-scheme:dark;font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
body{{margin:0;background:#07090d;color:#eef1f5;line-height:1.55}}
a{{color:#ffbf4a}}a:hover{{color:#ffd98a}}
header{{padding:36px 0 24px;border-bottom:1px solid #242933}}
.eyebrow{{color:#ffbf4a;text-transform:uppercase;letter-spacing:.16em;font-size:.75rem;font-weight:700}}
h1{{font-size:clamp(2.4rem,6vw,4.6rem);margin:8px 0}}
.muted{{color:#9da7b5}}
.wrap{{max-width:1100px;margin:auto;padding:28px 20px 70px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin:22px 0}}
.card{{background:#0d1118;border:1px solid #242933;border-radius:14px;padding:18px}}
.pill{{display:inline-block;border:1px solid #303744;border-radius:999px;padding:4px 9px;font-size:.78rem;margin:3px}}
table{{width:100%;border-collapse:collapse}}
td{{padding:10px;border-bottom:1px solid #242933}}
td.label{{color:#9da7b5;white-space:nowrap}}
td.value{{text-align:right;white-space:nowrap}}
td.value.status-ok{{color:#3fb950}}
td.value.status-missing{{color:#f85149}}
.posture-badge{{display:inline-block;padding:4px 10px;border-radius:999px;font-weight:700;font-size:.78rem}}
.posture-clear{{background:#1b4332;color:#d1fae5}}
.posture-review{{background:#451a03;color:#fde68a}}
.posture-attention{{background:#7c2d12;color:#fed7aa}}
.posture-critical{{background:#450a0a;color:#fecaca}}
.posture-unknown{{background:#1f2937;color:#e5e7eb}}
.nav{{display:flex;flex-wrap:wrap;gap:14px;margin-top:24px}}
.nav a{{padding:8px 13px;border:1px solid #3b3322;border-radius:999px;text-decoration:none;color:#eef1f5}}
.nav a:hover{{border-color:#ffbf4a}}
footer{{border-top:1px solid #242933;margin-top:64px;padding:32px 24px;color:#8993a3}}
</style>
</head>
<body>
<div class="wrap">
<header>
<div class="eyebrow">JARVIS-OS experience layer</div>
<h1>System Dashboard</h1>
<p class="muted">A consumer view of live JARVIS state — all data read from existing subsystems.</p>
<p><a href="https://github.com/MuntazarAI/jarvis-os">GitHub</a> · <a href="index.html">Documentation home</a></p>
</header>

<h2>System Posture<span class="posture-badge posture-{s["posture"]}">{s["posture"]}</span></h2>

<table>
<tr><td class="label">Pending approvals</td><td class="value">{s["pending_approvals"]}</td></tr>
<tr><td class="label">Emergency stop</td><td class="value">{bool(s["emergency_stop"])}</td></tr>
</table>

<h2>Subsystem health</h2>
<table>
{"".join(check_rows)}
</table>

<h2>Memory</h2>
<table>
{"".join(rows[:3])}
</table>

<h2>World Model</h2>
<table>
{"".join(rows[3:6])}
</table>

<h2>Agents</h2>
<table>
{"".join(rows[6:9])}
</table>

<h2>Tasks</h2>
<table>
{"".join(rows[9:13])}
</table>

<h2>Security</h2>
<table>
{"".join(rows[13:15])}
</table>

<footer>
<p>JARVIS-OS · MuntazarAI · Open-source AI systems engineering</p>
<p class="muted">All data read from existing subsystems via public APIs. No secrets or approval tokens exposed.</p>
</footer>
</div>
</body>
</html>
"""


def render_from_manager(manager) -> str:
    """Convenience: render a dashboard from an ExperienceManager."""
    return render_dashboard(manager.snapshot())
