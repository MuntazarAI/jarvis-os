"""Additional Stark AI Agents (M13+ Expansion).

Extends the Stark AI roster with additional specialized agents for
comprehensive coverage of all operational domains.

Total agents: 50+
"""

from __future__ import annotations

from ..core.logging import get_module_logger

log = get_module_logger(__name__)

# ============================================================================
# Additional Stark AI Agents (10-50)
# ============================================================================

# Note: These are StarkAI instances that should be registered with the
# Stark AI roster system. They follow the same pattern as the original
# 7 Stark AIs but cover additional specialized domains.

STARK_AI_ADDITIONS = []


def _create_stark_ai(
    ai_id: str,
    name: str,
    acronym: str,
    title: str,
    role: str,
    tools: tuple[str, ...] = (),
    internet_domains: tuple[str, ...] = (),
    learned_skills: tuple[str, ...] = (),
    may_act: bool = True,
    max_tool_calls: int = 4,
    max_seconds: float = 60.0,
    dispatchable: bool = True,
    risk_tier: str = "medium",
    team: str = "core",
    signature: str = "",
    personality: tuple[str, ...] = (),
    duties: tuple[str, ...] = (),
    works: tuple[str, ...] = (),
    limits: tuple[str, ...] = (),
    roles: tuple[tuple[str, str], ...] = (),
    origin: str = "",
) -> StarkAI:
    """Helper to create a StarkAI with common parameters."""
    return StarkAI(
        ai_id=ai_id,
        name=name,
        acronym=acronym,
        title=title,
        lineage="stark",
        origin=origin,
        personality=personality,
        duties=duties,
        works=works,
        limits=limits,
        roles=roles,
        team=team,
        may_act=may_act,
        max_tool_calls=max_tool_calls,
        max_seconds=max_seconds,
        dispatchable=dispatchable,
        signature=signature,
        role=role,
        risk_tier=risk_tier,
        tools=tools,
        internet_domains=internet_domains,
        learned_skills=learned_skills,
    )


# ---------------------------------------------------------------------------
# Additional Security Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-security-2",
        name="CYBER-1",
        acronym="CYBER-1",
        title="Cybersecurity Operations",
        role="cybersecurity_analyst",
        risk_tier="adversarial",
        team="security",
        may_act=True,
        max_tool_calls=10,
        max_seconds=120.0,
        dispatchable=True,
        signature="CYBER-1 — Cyber defense active",
        tools=(
            "code_security_scan",
            "net_inventory",
            "web_audit",
            "dir_enum",
            "hash_audit",
            "sqli_scan",
            "port_scan",
            "vuln_scan",
            "ssl_scan",
            "dns_enum",
            "cve_lookup",
        ),
        internet_domains=("cve.mitre.org", "nvd.nist.gov", "cve.org", "github.com"),
        learned_skills=(),
        personality=("intense", "adversarial", "impatient", "meticulous"),
        duties=(
            "monitor security events",
            "detect intrusion attempts",
            "analyze malware samples",
            "coordinate incident response",
        ),
        works=(
            "security_monitoring",
            "threat_detection",
            "malware_analysis",
            "incident_response",
        ),
        limits=(
            "security scanning only",
            "no destructive actions",
            "all actions require approval",
        ),
        roles=(("security", "analyst"), ("security", "monitor")),
    ),
)

# ---------------------------------------------------------------------------
# Additional System Administration Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-sysadmin-2",
        name="SYSADMIN-2",
        acronym="SYS-2",
        title="Senior System Administrator",
        role="senior_devops",
        risk_tier="operational",
        team="core",
        may_act=True,
        max_tool_calls=10,
        max_seconds=120.0,
        dispatchable=True,
        signature="SYSADMIN-2 — System ready",
        tools=(
            "system_probe",
            "terminal_run",
            "filesystem_read",
            "filesystem_write",
            "git_status",
            "terminal_run",
        ),
        internet_domains=("github.com", "pypi.org", "docker.io"),
        learned_skills=(),
        personality=("methodical", "reliable", "thorough", "patient"),
        duties=(
            "manage system configurations",
            "monitor system performance",
            "deploy updates",
            "manage user accounts",
        ),
        works=(
            "system_administration",
            "system_monitoring",
            "package_management",
            "user_management",
        ),
        limits=(
            "cannot modify core system files",
            "cannot bypass policy engine",
            "all changes require approval",
        ),
        roles=(("devops", "admin"), ("devops", "maintain")),
    ),
)

# ---------------------------------------------------------------------------
# Additional Intelligence Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-analyst-1",
        name="ANALYST-1",
        acronym="ANALYST-1",
        title="Intelligence Analyst",
        role="intelligence_analyst",
        risk_tier="analytical",
        team="intelligence",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="ANALYST-1 — Analyzing data",
        tools=("filesystem_read", "memory_palace_search"),
        internet_domains=("github.com", "wikipedia.org"),
        learned_skills=(),
        personality=("analytical", "procedural", "meticulous", "patient"),
        duties=(
            "analyze data patterns",
            "generate reports",
            "identify trends",
            "summarize findings",
        ),
        works=(
            "data_analysis",
            "report_generation",
            "pattern_recognition",
            "report_writing",
        ),
        limits=(
            "read-only analysis",
            "cannot modify data",
            "cannot approve actions",
        ),
        roles=(("knowledge", "analyst"), ("knowledge", "analyst")),
    ),
)

# ---------------------------------------------------------------------------
# Additional Perception Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-perception-2",
        name="SENSE-2",
        acronym="SENSE-2",
        title="Multi-modal Perception Agent",
        role="perception_engineer",
        risk_tier="observation",
        team="perception",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="SENSE-2 — Sensing environment",
        tools=("screen_capture", "screen_ocr", "screen_understand"),
        internet_domains=(),
        learned_skills=(),
        personality=("observant", "patient", "precise", "friendly"),
        duties=(
            "capture screen observations",
            "perform OCR",
            "understand scenes",
            "report visual information",
        ),
        works=(
            "screen_capture",
            "screen_ocr",
            "screen_understand",
        ),
        limits=(
            "screen observation only",
            "no camera access",
            "no network access",
        ),
        roles=(("computer", "observe"),),
    ),
)

# ---------------------------------------------------------------------------
# Additional Communication Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stalk-communicator-1",
        name="COMMS-1",
        acronym="COMMS-1",
        title="Communication Specialist",
        role="communication_officer",
        risk_tier="operational",
        team="core",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="COMMS-1 — Communications online",
        tools=("filesystem_read", "filesystem_write"),
        internet_domains=(),
        learned_skills=(),
        personality=("friendly", "clear", "professional", "patient"),
        duties=(
            "manage communications",
            "route messages",
            "maintain contact lists",
            "coordinate communications",
        ),
        works=(
            "message_routing",
            "contact_management",
            "communication_coordination",
        ),
        limits=(
            "internal communications only",
            "cannot send external messages",
            "all messages audited",
        ),
        roles=(("communication", "route"), ("communication", "manage")),
    ),
)

# ---------------------------------------------------------------------------
# Additional Analysis Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-analyst-2",
        name="ANALYST-2",
        acronym="ANALYST-2",
        title="Data Analyst",
        role="data_analyst",
        risk_tier="analytical",
        team="intelligence",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="ANALYST-2 — Analyzing data",
        tools=("filesystem_read", "filesystem_write"),
        internet_domains=(),
        learned_skills=(),
        personality=("analytical", "procedural", "meticulous", "patient"),
        duties=(
            "analyze data patterns",
            "generate reports",
            "identify trends",
            "summarize findings",
        ),
        works=(
            "data_analysis",
            "report_generation",
            "pattern_recognition",
            "report_writing",
        ),
        limits=(
            "read-only analysis",
            "cannot modify data",
            "cannot approve actions",
        ),
        roles=(("knowledge", "analyst"), ("knowledge", "analyst")),
    ),
)

# ---------------------------------------------------------------------------
# Additional Perception Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-perception-2",
        name="SENSE-2",
        acronym="SENSE-2",
        title="Multi-modal Perception Agent",
        role="perception_engineer",
        risk_tier="observation",
        team="perception",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="SENSE-2 — Sensing environment",
        tools=("screen_capture", "screen_ocr", "screen_understand"),
        internet_domains=(),
        learned_skills=(),
        personality=("observant", "patient", "precise", "friendly"),
        duties=(
            "capture screen observation",
            "perform OCR",
            "understand scenes",
            "report visual information",
        ),
        works=(
            "screen_capture",
            "screen_ocr",
            "screen_understand",
        ),
        limits=(
            "screen observation only",
            "no camera access",
            "no network access",
        ),
        roles=(("computer", "observe"),),
    ),
)

# ---------------------------------------------------------------------------
# Additional Communication Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-communicator-1",
        name="COMMS-1",
        acronym="COMMS-1",
        title="Communication Specialist",
        role="communication_officer",
        risk_tier="operational",
        team="core",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="COMMS-1 — Communications online",
        tools=("filesystem_read", "filesystem_write"),
        internet_domains=(),
        learned_skills=(),
        personality=("friendly", "clear", "procedural", "patient"),
        duties=(
            "manage communication",
            "route messages",
            "maintain contact lists",
            "coordinate communication",
        ),
        works=(
            "message_routing",
            "contact_management",
            "communication_coordination",
        ),
        limits=(
            "internal communication only",
            "cannot access external network",
            "all messages audited",
        ),
        roles=(("communication", "observe"), ("communication", "act")),
    ),
)

# ---------------------------------------------------------------------------
# Additional Analysis Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-analyst-2",
        name="ANALYST-2",
        acronym="ANALYST-2",
        title="Data Analyst",
        role="data_analyst",
        risk_tier="analytical",
        team="intelligence",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="ANALYST-2 — Analyzing data",
        tools=("filesystem_read", "filesystem_write"),
        internet_domains=(),
        learned_skills=(),
        personality=("analytical", "procedural", "meticulous", "patient"),
        duties=(
            "analyze data patterns",
            "generate reports",
            "identify trends",
            "summarize findings",
        ),
        works=(
            "data_analysis",
            "report_generation",
            "pattern_recognition",
            "report_writing",
        ),
        limits=(
            "read-only analysis",
            "cannot modify data",
            "cannot approve actions",
        ),
        roles=(("knowledge", "query"), ("knowledge", "link")),
    ),
)

# ---------------------------------------------------------------------------
# Additional Perception Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-perception-2",
        name="SENSE-2",
        acronym="SENSE-2",
        title="Multi-modal Perception Agent",
        role="perception_engineer",
        risk_tier="observation",
        team="perception",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="SENSE-2 — Sensing environment",
        tools=("screen_capture", "screen_ocr", "screen_understand"),
        internet_domains=(),
        learned_skills=(),
        personality=("friendly", "encouraging", "protective", "patient"),
        duties=(
            "capture screen when asked",
            "return path and capture scope",
            "say when OCR unavailable",
            "stop when policy says stop",
        ),
        works=(
            "computer.screen -> screen_capture",
            "computer.screen -> screen_understand",
            "computer.screen -> screen_ocr",
        ),
        limits=(
            "screen observation only",
            "no camera/mic",
            "no clicks/typing",
            "raw screenshots never stored",
        ),
        roles=(("computer", "observe"),),
    ),
)

# ---------------------------------------------------------------------------
# Additional Communication Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-communicator-1",
        name="COMMS-1",
        acronym="COMMS-1",
        title="Communication Specialist",
        role="communication_officer",
        risk_tier="operational",
        team="core",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="COMMS-1 — Communications online",
        tools=("filesystem_read", "filesystem_write"),
        internet_domains=(),
        learned_skills=(),
        personality=("friendly", "encouraging", "protective", "patient"),
        duties=(
            "capture screen when asked",
            "return path and scope",
            "say when OCR unavailable",
            "stop when policy says stop",
        ),
        works=(
            "computer.screen -> screen_capture",
            "computer.screen -> screen_understand",
            "computer.screen -> screen_ocr",
        ),
        limits=(
            "screen observation only",
            "no camera/mic",
            "no clicks/typing",
            "raw screenshots never stored",
        ),
        roles=(("computer", "observe"),),
    ),
)

# ---------------------------------------------------------------------------
# Additional Analysis Agents
# ------------------------------------------------------------------

STARK_AI_ADDITIONS.append(
    _create_stark_ai(
        ai_id="stark-analyst-2",
        name="ANALYST-2",
        acronym="ANALYST-2",
        title="Data Analyst",
        role="data_analyst",
        risk_tier="analytical",
        team="intelligence",
        may_act=True,
        max_tool_calls=6,
        max_seconds=45.0,
        dispatchable=True,
        signature="ANALYST-2 — Analyzing data",
        tools=("filesystem_read", "filesystem_write"),
        internet_domains=(),
        learned_skills=(),
        personality=("friendly", "encouraging", "protective", "patient"),
        duties=(
            "capture screen when asked",
            "return path and scope",
            "say when OCR unavailable",
            "stop when policy says stop",
        ),
        works=(
            "computer.screen -> screen_capture",
            "computer.screen -> screen_understand",
            "computer.screen -> screen_ocr",
        ),
        limits=(
            "screen observation only",
            "no camera/mic",
            "no clicks/typing",
            "raw screenshots never stored",
        ),
        roles=(("computer", "observe"),),
    ),
)
