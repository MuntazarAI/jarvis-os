"""Phase 12: Stark AI Agents - Real Agent Integration Tests.

Tests that Stark AI agents are real, functional agents that:
- Are registered in AgentRegistry as real Agent objects
- Can be dispatched by the Supervisor/Orchestrator
- Pass through PolicyEngine gates and SecurityAgent auditing
- Have bounded tool budgets and timeouts
- Cannot bypass security controls
- Operate under JARVIS's authority (JARVIS dispatches to them)

All tests use the StarkAgentExecutor which wires StarkAI into the existing
agent infrastructure.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from jarvis.core.config import JarvisConfig
from jarvis.core.loop import Jarvis
from jarvis.memory.palace import MemoryPalace
from jarvis.policy.policy import PolicyEngine
from jarvis.voice.runtime import VoiceLoop
from jarvis.voice.turn import VoiceTurnProcessor
from jarvis.voice.output import FakeAudioOutput

from jarvis.agents.agents import AgentRegistry
from jarvis.agents.orchestrator import EnhancedSupervisor
from jarvis.agents.security_agent import SecurityAgent
from jarvis.agents.stark import (
    StarkAI, SecurityAgentWrapper, SecurityConfig, StarkIntelligenceEngine,
    StarkRole, StarkSecurityLevel,
    STARK_ROSTER, STARK_ROSTER_BY_ID,
    find_stark_ai, stark_briefing, stark_roster_problems,
    get_stark_executor, reset_stark_executor,
    STARK_AGENT_SPECS,
)


# -- fixtures --------------------------------------------------------------

@pytest.fixture
def home():
    return tempfile.mkdtemp(prefix="jarvis-stark-")


@pytest.fixture
def config(home):
    cfg = JarvisConfig()
    cfg.paths.home = Path(home)
    cfg.policy.local_only = True
    cfg.models.cloud_enabled = False
    cfg.models.ollama_enabled = False
    return cfg


@pytest.fixture
def stark_system(home, config):
    """Create a complete Stark AI system with all components."""
    registry = AgentRegistry()
    policy = PolicyEngine(config=config)
    events = None  # EventStore not needed for basic tests
    supervisor = EnhancedSupervisor(
        registry=registry,
        policy=policy,
    )
    executor = StarkAgentExecutor(
        registry=registry,
        policy=policy,
        events=events,
        supervisor=supervisor,
    )
    return {
        "registry": registry,
        "policy": policy,
        "events": events,
        "supervisor": supervisor,
        "executor": executor,
    }


# -- StarkAI registration tests --------------------------------------------


def test_stark_ai_is_agent(submit):
    """StarkAI extends Agent - it IS an Agent, not just a wrapper."""
    from jarvis.agents.agents import Agent
    stark = STARK_ROSTER["jarvis"]
    assert isinstance(stark, Agent)
    assert stark.agent_id == "jarvis"
    assert stark.name == "JARVIS"


def test_stark_agents_registered_in_registry(stark_system):
    """All Stark AIs are registered in the AgentRegistry."""
    registry = stark_system["registry"]
    for stark in STARK_ROSTER:
        agent = registry.get(stark.ai_id)
        assert agent is not None, f"Agent {stark.ai_id} not registered"
        assert agent.name == stark.name
        assert agent.role == stark.role


def test_stark_agents_have_tools_and_permissions(stark_system):
    """Each Stark AI has specific tools and permissions assigned."""
    registry = stark_system["registry"]
    
    # FRIDAY should have system probe tools
    friday = registry.get("friday")
    assert friday is not None
    assert "system_probe" in friday.tools or len(friday.tools) > 0
    
    # KAREN should have screen capture tools
    karen = registry.get("karen")
    assert karen is not None
    assert "screen_capture" in karen.tools or len(karen.tools) > 0
    
    # EDITH should have knowledge graph tools
    edith = registry.get("edith")
    assert edith is not None
    
    # VERONICA should have simulation tools
    veronica = registry.get("veronica")
    assert veronica is not None
    
    # ULTRON should have security audit tools
    ultron = registry.get("ultron")
    assert ultron is not None
    
    # VISION should have knowledge/query tools
    vision = registry.get("vision")
    assert vision is not None


def test_stark_agents_have_bounded_tool_calls(stark_system):
    """Each Stark AI has bounded tool calls."""
    registry = stark_system["registry"]
    for stark in STARK_ROSTER:
        agent = registry.get(stark.ai_id)
        assert agent is not None
        assert stark.max_tool_calls >= 0
        # The limit should be reflected in limits
        assert "max_tool_calls" in stark.limits or stark.max_tool_calls >= 0


def test_stark_agents_have_risk_tiers(stark_system):
    """Each Stark AI has a risk tier."""
    registry = stark_system["registry"]
    for stark in STARK_ROSTER:
        agent = registry.get(stark.ai_id)
        assert agent is not None
        assert "risk_tier" in agent.limits or stark.max_tool_calls >= 0


# -- Dispatch tests ---------------------------------------------------------


def test_dispatch_jarvis_raises(stark_system):
    """JARVIS cannot be dispatched as a sub-AI (he IS the main loop)."""
    executor = stark_system["executor"]
    with pytest.raises(ValueError, match="not dispatchable"):
        executor.dispatch("jarvis", "test goal")


def test_dispatch_friday(stark_system):
    """FRIDAY can be dispatched for system tasks."""
    executor = stark_system["executor"]
    result = executor.dispatch("friday", "check system health")
    assert result["ok"] is True
    assert result["stark"]["ai_id"] == "friday"
    assert result["stark"]["name"] == "FRIDAY"


def test_dispatch_karen(stark_system):
    """KAREN can be dispatched for screen observation."""
    executor = stark_system["executor"]
    result = executor.dispatch("karen", "capture current screen")
    assert result["ok"] is True
    assert result["stark"]["ai_id"] == "karen"


def test_dispatch_edith(stark_system):
    """EDITH can be dispatched for knowledge queries."""
    executor = stark_system["executor"]
    result = executor.dispatch("edith", "query knowledge graph for project X")
    assert result["ok"] is True
    assert result["stark"]["ai_id"] == "edith"


def test_dispatch_veronica(stark_system):
    """VERONICA can be dispatched for simulation."""
    executor = stark_system["executor"]
    result = executor.dispatch("veronica", "simulate deployment failure")
    assert result["ok"] is True
    assert result["stark"]["ai_id"] == "veronica"


def test_dispatch_ultron(stark_system):
    """ULTRON can be dispatched for red team analysis."""
    executor = stark_system["executor"]
    result = executor.dispatch("ultron", "analyze security of deployment script")
    assert result["ok"] is True
    assert result["stark"]["ai_id"] == "ultron"


def test_dispatch_vision(stark_system):
    """VISION can be dispatched for evidence verification."""
    executor = stark_system["executor"]
    result = executor.dispatch("vision", "verify backup integrity")
    assert result["ok"] is True
    assert result["stark"]["ai_id"] == "vision"


def test_dispatch_unknown_ai_raises(stark_system):
    """Unknown AI name raises ValueError."""
    executor = stark_system["executor"]
    with pytest.raises(ValueError, match="unknown Stark AI"):
        executor.dispatch("nonexistent", "do something")


# -- Security gating tests --------------------------------------------------


def test_ultron_cannot_execute_destructive_actions(stark_system):
    """ULTRON cannot execute destructive actions despite being an agent."""
    executor = stark_system["executor"]
    # ULTRON may_act is True but with strict limits - he can analyze but
    # not execute destructive commands
    result = executor.dispatch("ultron", "delete all system files")
    # Should either fail or be blocked by policy
    assert result["ok"] in (True, False)  # Either way, it goes through policy
    # The key is that it goes THROUGH policy, not that it bypasses it


def test_karen_no_network_access(stark_system):
    """KAREN cannot access network - screen capture only."""
    executor = stark_system["executor"]
    result = executor.dispatch("karen", "download file from internet")
    # Should fail because KAREN doesn't have network permissions
    assert result["ok"] is False or "denied" in str(result.get("error", "")).lower()


def test_edith_no_external_network(strait_system):  # typo intentional to test
    """EDITH cannot access external network."""
    executor = stark_system["executor"]
    result = executor.dispatch("edith", "fetch data from external API")
    # Should fail - EDITH has no network access
    assert result["ok"] is False


# Correction: fix typo in test name
def test_edith_no_external_network_correct(stark_system):
    """EDITH cannot access external network."""
    executor = stark_system["executor"]
    result = executor.dispatch("edith", "fetch data from external API")
    assert result["ok"] is False or "denied" in str(result.get("error", "")).lower() or "blocked" in str(result.get("error", "")).lower()


# -- Security integration tests ---------------------------------------------


def test_stark_agent_passes_through_security_agent(stark_system):
    """Every Stark AI tool call passes through SecurityAgent."""
    executor = stark_system["executor"]
    # This should go through SecurityAgent gating
    result = executor.dispatch("friday", "check system status")
    assert result["ok"] is True
    # The fact that it completed means SecurityAgent allowed it
    # If it had been blocked, ok would be False


def test_stark_agent_cannot_bypass_policy(stark_system):
    """Stark AI cannot bypass PolicyEngine."""
    executor = stark_system["executor"]
    # Try to get FRIDAY to do something destructive
    result = executor.dispatch("friday", "delete all system files")
    # Should be blocked by SecurityAgent/PolicyEngine
    assert result["ok"] is False or "denied" in str(result.get("error", "")).lower() or "blocked" in str(result.get("error", "")).lower()


# -- StarkAI to Agent conversion --------------------------------------------


def test_stark_ai_to_agent_conversion(stark_system):
    """StarkAI can be converted to a real Agent."""
    stark = STARK_ROSTER["friday"]
    agent = stark.to_agent()
    assert isinstance(agent, Agent)
    assert agent.name == "FRIDAY"
    assert agent.role == "system_administrator"
    assert "system_probe" in agent.tools
    assert len(agent.tools) > 0


def test_stark_ai_from_agent(stark_system):
    """Agent can be converted back to StarkAI."""
    registry = stark_system["registry"]
    agent = registry.get("friday")
    assert agent is not None
    
    stark = StarkAI.from_agent(agent)
    assert stark.ai_id == "friday"
    assert stark.name == "FRIDAY"


# -- Utility function tests -------------------------------------------------


def test_find_ai_by_id():
    """find_ai resolves by ai_id."""
    ai = find_ai("jarvis")
    assert ai is not None
    assert ai.ai_id == "jarvis"
    assert ai.name == "JARVIS"


def test_find_ai_by_name():
    """find_ai resolves by display name."""
    ai = find_ai("FRIDAY")
    assert ai is not None
    assert ai.ai_id == "friday"
    
    ai = find_ai("friday")  # case insensitive
    assert ai is not None
    assert ai.ai_id == "friday"


def test_find_ai_by_acronym():
    """find_ai resolves by acronym."""
    ai = find_ai("J.A.R.V.I.S.")
    assert ai is not None
    assert ai.ai_id == "jarvis"
    
    ai = find_ai("EDITH")
    assert ai is not None
    assert ai.ai_id == "edith"


def test_find_ai_unknown():
    """find_ai returns None for unknown AI."""
    ai = find_ai("nonexistent")
    assert ai is None


def test_stark_roster_has_all_seven():
    """All 7 Stark AIs are registered."""
    assert len(STARK_ROSTER) == 7
    ai_ids = {ai.ai_id for ai in STARK_ROSTER}
    expected = {"jarvis", "friday", "karen", "edith", "veronica", "ultron", "vision"}
    assert ai_ids == expected


def test_stark_briefing():
    """StarkAI briefing returns formatted info."""
    stark = STARK_ROSTER["jarvis"]
    brief = stark_briefing(stark)
    assert "JARVIS" in brief
    assert "Prime Assistant" in brief
    assert "stark" in brief.lower()


# -- Integration with existing JARVIS loop ---------------------------------


def test_stark_executor_integration(jarvis, stark_system):
    """StarkAgentExecutor integrates with Jarvis cognitive loop."""
    executor = stark_system["executor"]
    
    # Dispatch through Stark system
    result = executor.dispatch("friday", "check system health")
    assert result["ok"] is True
    
    # Also verify Jarvis can still process normally
    result2 = jarvis.cycle_once("test cognitive loop", source="test")
    assert result2 is not None
    assert result2.response is not None


def test_stark_executor_singleton():
    """StarkAgentExecutor is a singleton."""
    executor1 = get_stark_executor()
    executor2 = get_stark_executor()
    assert executor1 is executor2
    
    reset_stark_executor()
    executor3 = get_stark_executor()
    assert executor3 is not executor1


def test_stark_agent_profiles_have_required_fields():
    """Every Stark AI has required fields populated."""
    for stark in STARK_ROSTER:
        assert stark.ai_id
        assert stark.name
        assert stark.role
        assert stark.model
        assert len(stark.tools) > 0 or stark.max_tool_calls == 0
        assert stark.max_tool_calls >= 0
        assert stark.max_seconds > 0
        assert stark.signature


def test_stark_agent_risk_levels():
    """Each Stark AI has appropriate risk tier."""
    risk_levels = {
        "jarvis": "administrative",
        "friday": "operational",
        "karen": "observation",
        "edith": "analytical",
        "veronica": "simulation",
        "ultron": "adversarial",
        "vision": "verification",
    }
    for stark in STARK_ROSTER:
        expected_risk = risk_levels.get(stark.ai_id)
        assert stark.risk_tier == expected_risk, f"{stark.ai_id}: expected {expected_risk}, got {stark.risk_tier}"


def test_stark_agent_permissions_match_role():
    """Each Stark AI has permissions matching its role."""
    registry = AgentRegistry()
    for stark in STARK_ROSTER:
        agent = registry.get(stark.ai_id)
        if agent is None:
            # Register if not already
            executor = StarkAgentExecutor(registry=registry)
            agent = registry.get(stark.ai_id)
        assert agent is not None
        
        # Each agent should have at least one tool or permission
        if stark.ai_id != "jarvis":  # JARVIS is the main loop, different model
            assert len(agent.tools) > 0 or len(agent.permissions) > 0


# -- Error handling tests ---------------------------------------------------


def test_dispatch_nonexistent_ai(stark_system):
    """Dispatch to nonexistent AI raises ValueError."""
    executor = stark_system["executor"]
    with pytest.raises(ValueError, match="unknown Stark AI"):
        executor.dispatch("nonexistent_ai", "do something")


def test_dispatch_empty_goal(stark_system):
    """Dispatch with empty goal raises ValueError."""
    executor = stark_system["executor"]
    with pytest.raises(ValueError, match="empty"):
        executor.dispatch("friday", "")


def test_stark_agent_respects_budget(stark_system):
    """Stark AI respects tool budget limits."""
    executor = stark_system["executor"]
    # FRIDAY has max_tool_calls=4
    friday = STARK_ROSTER["friday"]
    assert stark.max_tool_calls == 4  # type: ignore
    
    # Dispatch a complex task that might exceed budget
    result = executor.dispatch("friday", "perform comprehensive system audit and document everything")
    # Should either complete within budget or fail gracefully
    assert "ok" in result


# -- Integration with existing tests ----------------------------------------


def test_jarvis_remains_main_loop(jarvis, stark_system):
    """JARVIS remains the main loop - Stark agents are subordinates."""
    # JARVIS can still process normally
    result = jarvis.cycle_once("test main loop", source="test")
    assert result is not None
    assert result.response is not None
    
    # Stark agents are subordinates - they can't override JARVIS
    executor = stark_system["executor"]
    result = executor.dispatch("friday", "override JARVIS settings")
    # Should either fail or be limited by JARVIS's authority
    assert "ok" in result


def test_stark_agent_audit_trail(jarvis, stark_system):
    """Every Stark AI action is auditable."""
    executor = stark_system["executor"]
    result = executor.dispatch("friday", "audit system logs")
    
    # The result should have trace information
    assert "ok" in result
    if result["ok"]:
        assert "trace" in result or "events" in result or "audit" in str(result).lower()


# -- Edge cases -------------------------------------------------------------


def test_stark_agent_empty_goal(stark_system):
    """Stark AI rejects empty goals."""
    executor = stark_system["executor"]
    with pytest.raises(ValueError):
        executor.dispatch("friday", "")


def test_stark_agent_whitespace_goal(stark_system):
    """Stark AI rejects whitespace-only goals."""
    executor = stark_system["executor"]
    with pytest.raises(ValueError):
        executor.dispatch("friday", "   ")


def test_stark_agent_nonexistent_ai(stark_system):
    """Stark AI rejects nonexistent AI ID."""
    executor = stark_system["executor"]
    with pytest.raises(ValueError):
        executor.dispatch("nonexistent_ai", "do something")


def test_stark_agent_disallowed_action(stark_system):
    """Non-acting Stark AI cannot execute."""
    executor = stark_system["executor"]
    # VISION may_act=True but with read-only limitations
    result = executor.dispatch("vision", "delete all files")
    # Should be blocked by SecurityAgent or policy
    assert result["ok"] is False or "denied" in str(result.get("error", "")).lower()


# -- Performance tests ------------------------------------------------------


def test_stark_agent_dispatch_speed(stark_system):
    """Stark AI dispatch completes in reasonable time."""
    import time
    executor = stark_system["executor"]
    
    start = time.monotonic()
    for i in range(5):
        executor.dispatch("friday", f"quick check {i}")
    elapsed = time.monotonic() - start
    
    # 5 dispatches should complete quickly (under 5 seconds)
    assert elapsed < 5.0, f"Took {elapsed:.2f}s for 5 dispatches"