"""Agent reach: permission map, reachability health, and roster.

Three read-only views assembled from the registries that already exist:

* ``permission_map`` - what each role declares (skills/tools), what the
  PolicyEngine actually grants, and which device grants apply. It never
  grants, approves, or dispatches anything.
* ``reachability_health`` - which executors and devices can act right
  now. Missing subsystems are reported as ``unknown``, never as ``ok``.
* ``registry_roster`` - searchable identities (roles, executors, named
  personas, ECC harness agents/skills) plus the exact dispatch command.

Reuse only: ``AgentCard``/``SkillRegistry``, the supervisor's
``AgentRegistry``, ``PolicyEngine`` grants, ``DeviceGrantStore``,
``DeviceFabric``, the Stark roster, and the OpenCode harness files under
``.opencode/``. No second registry, scheduler, or authority exists here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.types import now
from .contract import SkillRegistry, role_cards

REACH_VERSION = 1
MAX_ENTRIES = 200
_TERMINAL_AGENT_STATES = frozenset({"shutdown", "disabled"})


def _safe(fn: Any, fallback: Any) -> Any:
    try:
        return fn()
    except Exception:
        return fallback


def _default_harness_root() -> Path:
    return Path(__file__).resolve().parents[2] / ".opencode"


def _frontmatter(path: Path) -> dict[str, str]:
    """Read simple ``key: value`` frontmatter without a YAML dependency."""
    try:
        text = path.read_text(encoding="utf-8")[:4000]
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    lines = text.splitlines()
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def harness_inventory(root: str | Path | None = None) -> dict[str, Any]:
    """Inventory the OpenCode/ECC assets available to this checkout."""
    base = Path(root) if root is not None else _default_harness_root()
    skills: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    for skill_file in sorted(base.glob("skills/*/SKILL.md")):
        fields = _frontmatter(skill_file)
        skills.append({
            "id": skill_file.parent.name,
            "name": fields.get("name", skill_file.parent.name),
            "description": fields.get("description", ""),
            "origin": fields.get("origin") or fields.get("metadata", ""),
            "source": "ecc",
        })
    agent_dir = base / "agents"
    for agent_file in sorted(agent_dir.glob("*.md")) if agent_dir.is_dir() else []:
        fields = _frontmatter(agent_file)
        agents.append({
            "id": agent_file.stem,
            "name": fields.get("name", agent_file.stem),
            "description": fields.get("description", ""),
            "mode": fields.get("mode", "subagent"),
            "source": "ecc",
        })
    return {
        "root": str(base),
        "available": base.is_dir(),
        "skills": skills[:MAX_ENTRIES],
        "agents": agents[:MAX_ENTRIES],
        "skill_count": len(skills),
        "agent_count": len(agents),
    }


# -- permission reach --------------------------------------------------------

def _role_cards(orchestrator: Any | None) -> dict[str, Any]:
    cards = getattr(orchestrator, "cards", None) if orchestrator else None
    if isinstance(cards, dict) and cards:
        return cards
    return {card.role_id: card for card in role_cards()}


def _skill_registry(orchestrator: Any | None) -> SkillRegistry:
    skills = getattr(orchestrator, "skills", None) if orchestrator else None
    return skills if skills is not None else SkillRegistry()


def _policy_grants(policy: Any | None, actor: str) -> tuple[list[str] | None, str]:
    if policy is None:
        return None, "no policy bound"
    try:
        getter = getattr(policy, "get_grant", None)
        if callable(getter):
            grants = list(getter(actor))
        else:
            lister = getattr(policy, "list_grants", None)
            if not callable(lister):
                return None, "policy has no grant reader"
            grants = list((lister(actor) or {}).get(actor, []))
    except Exception as exc:
        return None, f"grant read failed: {type(exc).__name__}"
    error = str(getattr(policy, "_grants_error", "") or "")
    if error:
        return None, f"grant store error: {error[:120]}"
    return sorted(set(grants)), ""


def _load_device_grants(store: Any | None, registry: Any | None
                        ) -> tuple[list[dict[str, Any]] | None, dict[str, Any], str]:
    if store is None:
        return None, {}, "no device grant store"
    try:
        records = store.all_grants()
        suspended = store.suspended_devices()
    except Exception as exc:
        return None, {}, f"device grant read failed: {type(exc).__name__}"
    out: list[dict[str, Any]] = []
    stamp = now()
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "active":
            continue
        expires = float(record.get("expires_at") or 0.0)
        if expires and stamp >= expires:
            continue
        device_id = str(record.get("device_id", ""))
        device = None
        if registry is not None:
            device = _safe(lambda: registry.get(device_id), None)
        out.append({
            "device_id": device_id,
            "device_name": getattr(device, "name", "") if device else "",
            "capability": str(record.get("capability", "")),
            "grant_actor": str(record.get("actor", "*")),
            "expires_at": expires,
            "suspended": device_id in suspended,
            "executable": bool(getattr(device, "can_execute", lambda: False)())
            if device is not None else None,
        })
    return out, suspended, ""


def _device_grants_for(records: list[dict[str, Any]] | None,
                       actor: str, may_act: bool) -> list[dict[str, Any]] | None:
    if records is None:
        return None
    found = [dict(record) for record in records
             if record["grant_actor"] in (actor, "*")]
    for record in found:
        record["reachable"] = bool(
            may_act and record.get("executable") is not False
            and not record.get("suspended"))
    return found


def permission_map(*, orchestrator: Any | None = None,
                   policy: Any | None = None, tools: Any | None = None,
                   grant_store: Any | None = None,
                   registry: Any | None = None) -> dict[str, Any]:
    """Return the enforced/declared permission reach for every role.

    ``reachable`` is true only when the role is allowed to act, the tool
    is registered, and the PolicyEngine grants every required permission.
    ``None`` means the answer is unknown (no policy/tool registry), never
    a guess. Device grants are shown separately and also fail closed.
    """
    cards = _role_cards(orchestrator)
    skills = _skill_registry(orchestrator)
    device_records, suspended, device_error = _load_device_grants(
        grant_store, registry)
    roles: list[dict[str, Any]] = []
    policy_known = policy is not None
    tools_known = tools is not None
    acting = 0
    reachable_tools = 0
    for role_id in sorted(cards):
        card = cards[role_id]
        grants, grant_error = _policy_grants(policy, role_id)
        if grants is None:
            policy_known = False
        role_skills = [skills.get(name) for name in card.skills]
        declared_tools = sorted({
            tool
            for skill in role_skills if skill is not None
            for tool in skill.tools
        })
        tool_rows: list[dict[str, Any]] = []
        for name in declared_tools:
            tool = tools.get(name) if tools is not None else None
            required = list(getattr(getattr(tool, "spec", None),
                                    "required_permissions", []) or [])
            if grants is None:
                policy_ok: bool | None = None
            else:
                policy_ok = all(
                    permission in grants or "*" in grants
                    for permission in required)
            registered: bool | None = bool(tool is not None) \
                if tools is not None else None
            if not card.may_act:
                reachable: bool | None = False
                reason = "reasoning-only by contract"
            elif registered is False:
                reachable = False
                reason = "tool is not registered"
            elif policy_ok is False:
                reachable = False
                reason = "policy permission not granted"
            elif policy_ok is None or registered is None:
                reachable = None
                reason = "unknown (policy or tool registry unavailable)"
            else:
                reachable = True
                reason = "declared and policy-granted"
            if reachable:
                reachable_tools += 1
            tool_rows.append({
                "name": name,
                "required_permissions": required,
                "registered": registered,
                "policy_granted": policy_ok,
                "reachable": reachable,
                "reason": reason,
            })
        if card.may_act:
            acting += 1
        roles.append({
            "role_id": role_id,
            "role": card.role,
            "executor": card.executor,
            "may_act": card.may_act,
            "skills": list(card.skills),
            "declared_permissions": list(card.permissions),
            "policy_grants": grants,
            "grant_error": grant_error,
            "tools": tool_rows,
            "device_grants": _device_grants_for(
                device_records, role_id, card.may_act),
        })
    return {
        "view": "permissions",
        "version": REACH_VERSION,
        "policy_known": policy_known,
        "tools_known": tools_known,
        "device_grants_known": device_records is not None,
        "device_grants_error": device_error,
        "roles": roles,
        "summary": {
            "roles": len(roles),
            "acting_roles": acting,
            "reasoning_only": len(roles) - acting,
            "declared_tools": len({row["name"] for role in roles
                                   for row in role["tools"]}),
            "reachable_tools": reachable_tools,
            "device_grants": len(device_records or []),
            "suspended_devices": len(suspended),
        },
    }


# -- reachability health -----------------------------------------------------

def _agent_rows(supervisor: Any | None) -> tuple[list[dict[str, Any]], bool]:
    registry = getattr(supervisor, "registry", None) if supervisor else None
    if registry is None:
        return [], False
    agents = _safe(lambda: registry.list_agents(), [])
    rows = []
    for agent in agents:
        state = str(getattr(agent, "state", "unknown"))
        rows.append({
            "agent_id": getattr(agent, "agent_id", ""),
            "name": getattr(agent, "name", ""),
            "role": getattr(agent, "role", ""),
            "state": state,
            "reachable": state not in _TERMINAL_AGENT_STATES,
            "tasks_done": int(getattr(agent, "tasks_done", 0) or 0),
            "tasks_failed": int(getattr(agent, "tasks_failed", 0) or 0),
        })
    return rows, True


def _device_rows(registry: Any | None,
                 suspended: dict[str, Any] | None) -> tuple[list[dict[str, Any]], bool]:
    if registry is None:
        return [], False
    devices = _safe(lambda: registry.list(), [])
    suspended = suspended or {}
    rows = []
    for device in devices:
        device_id = getattr(device, "device_id", "")
        capabilities = getattr(device, "capabilities", {}) or {}
        rows.append({
            "device_id": device_id,
            "name": getattr(device, "name", ""),
            "device_type": getattr(device, "device_type", ""),
            "lifecycle": getattr(getattr(device, "lifecycle", ""), "value", ""),
            "trust": getattr(getattr(device, "trust", ""), "value", ""),
            "connectivity": getattr(device, "connectivity", "unknown"),
            "executable": bool(getattr(device, "can_execute",
                                       lambda: False)()),
            "block_reason": getattr(device, "block_reason", lambda: "")() or "",
            "capabilities": sorted(capabilities)[:64],
            "suspended": device_id in suspended,
        })
    return rows, True


def reachability_health(*, supervisor: Any | None = None,
                        fabric: Any | None = None,
                        policy: Any | None = None,
                        grant_store: Any | None = None,
                        orchestrator: Any | None = None,
                        harness_root: str | Path | None = None
                        ) -> dict[str, Any]:
    """Report live reachability for agents, devices, policy, and harness.

    A missing subsystem is ``unknown``. An engaged emergency stop is a
    ``degraded`` reachability state (deliberate, but nothing can act).
    """
    registry = getattr(fabric, "registry", None) if fabric else None
    if grant_store is None and fabric is not None:
        grant_store = getattr(fabric, "grant_store", None) or getattr(
            getattr(fabric, "router", None), "grant_store", None)
    suspended = _safe(lambda: grant_store.suspended_devices(), {}) \
        if grant_store is not None else {}
    agents, agents_known = _agent_rows(supervisor)
    devices, devices_known = _device_rows(registry, suspended)
    cards = _safe(role_cards, [])
    inventory = _safe(lambda: harness_inventory(harness_root),
                      {"available": False, "skills": [], "agents": [],
                       "skill_count": 0, "agent_count": 0, "root": ""})
    emergency = _safe(lambda: bool(policy._emergency_stop()),
                      None) if policy is not None else None
    grant_error = str(getattr(policy, "_grants_error", "") or "") \
        if policy is not None else ""

    checks = [
        {"name": "agent-registry", "ok": agents_known if agents_known else None,
         "detail": f"{len(agents)} executor(s)" if agents_known
         else "no supervisor bound"},
        {"name": "role-contracts", "ok": bool(cards),
         "detail": f"{len(cards)} role contract(s)"},
        {"name": "device-registry", "ok": devices_known if devices_known else None,
         "detail": f"{len(devices)} device(s)" if devices_known
         else "no device fabric bound"},
        {"name": "device-grants", "ok": True if grant_store is not None else None,
         "detail": "grant store readable" if grant_store is not None
         else "no device grant store bound"},
        {"name": "policy", "ok": False if grant_error else
         (None if policy is None else not bool(emergency)),
         "detail": grant_error or (
             "emergency stop engaged — actions blocked" if emergency
             else "policy readable" if policy is not None
             else "no policy bound")},
        {"name": "ecc-harness", "ok": True if inventory.get("available") else None,
         "detail": f"{inventory.get('skill_count', 0)} skill(s), "
                   f"{inventory.get('agent_count', 0)} agent(s)"
         if inventory.get("available") else "no .opencode harness assets"},
    ]
    if any(check["ok"] is False for check in checks):
        status = "degraded"
    elif any(check["ok"] is None for check in checks):
        status = "unknown"
    else:
        status = "ok"
    states: dict[str, int] = {}
    for agent in agents:
        states[agent["state"]] = states.get(agent["state"], 0) + 1
    lifecycles: dict[str, int] = {}
    trusts: dict[str, int] = {}
    for device in devices:
        lifecycles[device["lifecycle"]] = lifecycles.get(
            device["lifecycle"], 0) + 1
        trusts[device["trust"]] = trusts.get(device["trust"], 0) + 1
    return {
        "view": "health",
        "version": REACH_VERSION,
        "status": status,
        "generated_at": now(),
        "emergency_stop": emergency,
        "agents": {
            "known": agents_known,
            "total": len(agents),
            "reachable": sum(1 for agent in agents if agent["reachable"]),
            "by_state": states,
            "items": agents,
            "roles": len(cards),
            "acting_roles": sum(1 for card in cards if card.may_act),
        },
        "devices": {
            "known": devices_known,
            "total": len(devices),
            "executable": sum(1 for device in devices
                              if device["executable"]),
            "suspended": len(suspended),
            "by_lifecycle": lifecycles,
            "by_trust": trusts,
            "items": devices,
        },
        "harness": inventory,
        "checks": checks,
    }


# -- registry / roster --------------------------------------------------------

def _matches(query: str, *values: Any) -> bool:
    if not query:
        return True
    needle = query.strip().lower()
    haystack = " ".join(str(value) for value in values).lower()
    return needle in haystack


def registry_roster(*, supervisor: Any | None = None,
                    orchestrator: Any | None = None,
                    query: str = "",
                    harness_root: str | Path | None = None
                    ) -> dict[str, Any]:
    """Searchable identities and their exact dispatch path.

    Personas and harness agents add no authority: every dispatch still
    runs through the orchestrator and PolicyEngine, and every tool call
    is gated exactly as before.
    """
    from .orchestrator import TEAMS
    from .stark import STARK_ROSTER

    cards = _role_cards(orchestrator)
    teams_for_role: dict[str, list[str]] = {}
    for team, stages in TEAMS.items():
        for role_id, _purpose in stages:
            teams_for_role.setdefault(role_id, []).append(team)

    roles = []
    for role_id in sorted(cards):
        card = cards[role_id]
        teams = teams_for_role.get(role_id, [])
        if teams:
            dispatch = f'jarvis agents run "<goal>" --team {teams[0]}'
        else:
            dispatch = 'jarvis agents run "<goal>"'
        if not _matches(query, role_id, card.role, card.executor,
                        card.skills, card.capabilities):
            continue
        roles.append({
            "id": role_id,
            "name": card.role,
            "kind": "role",
            "executor": card.executor,
            "may_act": card.may_act,
            "skills": list(card.skills),
            "teams": teams,
            "dispatch": dispatch,
        })

    executors, executors_known = _agent_rows(supervisor)
    executor_rows = []
    for agent in executors:
        if not _matches(query, agent["name"], agent["role"], agent["state"]):
            continue
        executor_rows.append({
            "id": agent["name"],
            "name": agent["name"],
            "kind": "executor",
            "role": agent["role"],
            "state": agent["state"],
            "reachable": agent["reachable"],
            "dispatch": 'jarvis agents run "<goal>"',
        })

    named = []
    for profile in STARK_ROSTER:
        if not _matches(query, profile.ai_id, profile.name, profile.title,
                        profile.duties, profile.role_ids, profile.team):
            continue
        named.append({
            "id": profile.ai_id,
            "name": profile.name,
            "title": profile.title,
            "kind": "persona",
            "roles": list(profile.role_ids),
            "team": profile.team,
            "may_act": profile.may_act,
            "dispatchable": profile.dispatchable,
            "dispatch": (f'jarvis agents ask {profile.ai_id} "<goal>"'
                         if profile.dispatchable
                         else "main loop (not a sub-AI)"),
        })

    inventory = _safe(lambda: harness_inventory(harness_root),
                      {"skills": [], "agents": [], "skill_count": 0,
                       "agent_count": 0, "available": False, "root": ""})
    harness: list[dict[str, Any]] = []
    for skill in inventory.get("skills", []):
        if not _matches(query, skill["id"], skill.get("name", ""),
                        skill.get("description", "")):
            continue
        harness.append({
            "id": skill["id"],
            "name": skill.get("name", skill["id"]),
            "kind": "ecc-skill",
            "source": "ecc",
            "description": skill.get("description", ""),
            "dispatch": f"load skill `{skill['id']}` (or @{skill['id']})",
        })
    for agent in inventory.get("agents", []):
        if not _matches(query, agent["id"], agent.get("name", ""),
                        agent.get("description", "")):
            continue
        harness.append({
            "id": agent["id"],
            "name": agent.get("name", agent["id"]),
            "kind": "ecc-agent",
            "source": "ecc",
            "description": agent.get("description", ""),
            "dispatch": f"ask the primary agent to use the {agent['id']} subagent",
        })

    team_rows = []
    for team, stages in TEAMS.items():
        if not _matches(query, team, [role for role, _ in stages]):
            continue
        team_rows.append({
            "id": team,
            "name": team,
            "kind": "team",
            "stages": [{"role_id": role, "purpose": purpose}
                       for role, purpose in stages],
            "dispatch": f'jarvis agents run "<goal>" --team {team}',
        })

    matches = len(roles) + len(executor_rows) + len(named) + len(harness) \
        + len(team_rows)
    return {
        "view": "registry",
        "version": REACH_VERSION,
        "query": query,
        "matches": matches,
        "roles": roles,
        "executors": executor_rows,
        "executors_known": executors_known,
        "named": named,
        "harness": harness,
        "teams": team_rows,
        "counts": {
            "roles": len(cards),
            "executors": len(executors),
            "named": len(STARK_ROSTER),
            "ecc_skills": inventory.get("skill_count", 0),
            "ecc_agents": inventory.get("agent_count", 0),
            "teams": len(TEAMS),
        },
    }


# -- assembly ----------------------------------------------------------------

def _stores(jarvis: Any | None) -> tuple[Any, Any, Any, Any, Any]:
    policy = getattr(jarvis, "policy", None) if jarvis else None
    supervisor = getattr(jarvis, "supervisor", None) if jarvis else None
    orchestrator = getattr(jarvis, "orchestrator", None) if jarvis else None
    fabric = getattr(jarvis, "device_fabric", None) if jarvis else None
    tools = getattr(jarvis, "tools", None) if jarvis else None
    return policy, supervisor, orchestrator, fabric, tools


def _grant_store(jarvis: Any | None, fabric: Any | None,
                 supplied: Any | None) -> Any | None:
    if supplied is not None:
        return supplied
    store = getattr(fabric, "grant_store", None) if fabric else None
    if store is None and fabric is not None:
        store = getattr(getattr(fabric, "router", None), "grant_store", None)
    if store is not None:
        return store
    home = getattr(getattr(getattr(jarvis, "config", None), "paths", None),
                   "home", None) if jarvis else None
    if not home:
        return None
    try:
        from ..device.authz import DeviceGrantStore
        return DeviceGrantStore(home)
    except Exception:
        return None


def build_reach(jarvis: Any | None = None, *, query: str = "",
                view: str = "all", harness_root: str | Path | None = None,
                grant_store: Any | None = None) -> dict[str, Any]:
    """Build one, or all three, reach views. Read-only and defensive."""
    policy, supervisor, orchestrator, fabric, tools = _stores(jarvis)
    registry = getattr(fabric, "registry", None) if fabric else None
    store = _grant_store(jarvis, fabric, grant_store)
    payload: dict[str, Any] = {}
    wanted = view if view in ("map", "permissions", "health", "registry",
                              "roster", "all") else "all"
    if wanted in ("map", "permissions", "all"):
        payload["permissions"] = permission_map(
            orchestrator=orchestrator, policy=policy, tools=tools,
            grant_store=store, registry=registry)
    if wanted in ("health", "all"):
        payload["health"] = reachability_health(
            supervisor=supervisor, fabric=fabric, policy=policy,
            grant_store=store, orchestrator=orchestrator,
            harness_root=harness_root)
    if wanted in ("registry", "roster", "all"):
        payload["registry"] = registry_roster(
            supervisor=supervisor, orchestrator=orchestrator, query=query,
            harness_root=harness_root)
    payload["view"] = "all" if wanted == "all" else wanted
    payload["version"] = REACH_VERSION
    return payload


def reach_summary(jarvis: Any | None = None) -> dict[str, Any]:
    """Small, scrub-friendly summary for the read-only status board."""
    try:
        policy, supervisor, orchestrator, fabric, _tools = _stores(jarvis)
        registry = getattr(fabric, "registry", None) if fabric else None
        store = _grant_store(jarvis, fabric, None)
        health = reachability_health(
            supervisor=supervisor, fabric=fabric, policy=policy,
            grant_store=store, orchestrator=orchestrator)
        cards = _role_cards(orchestrator)
        return {
            "status": health["status"],
            "roles": len(cards),
            "acting_roles": sum(1 for card in cards.values() if card.may_act),
            "agents": health["agents"]["reachable"],
            "devices": health["devices"]["executable"],
            "device_total": health["devices"]["total"],
            "ecc_skills": health["harness"].get("skill_count", 0),
            "ecc_agents": health["harness"].get("agent_count", 0),
        }
    except Exception:
        return {"status": "unknown"}
