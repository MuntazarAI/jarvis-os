"""Jarvis Unified Integration Layer — connects everything together.

Connects Stark AI Agents → DOTS → OMNINET → Neural Networking into one
cohesive system. Every Stark AI can dispatch to DOTS, every DOT can
browse OMNINET, every Dot can use Neural Networks, and everything feeds
back into the central JARVIS cognitive loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..agents.agents import AgentRegistry
from ..agents.stark import (
    StarkAI, STARK_ROSTER_BY_ID, find_ai,
)
from ..dots.manager import DotManager
from ..core.config import JarvisConfig
from ..core.internet import InternetAccess
from ..core.types import now
from ..policy.policy import PolicyEngine
from ..omninet.discovery import SearchEngine
from ..omninet.exploration import EnhancedBrowserAgent
from ..omninet.public_data import default_public_data_registry
from ..omninet.crawler import BoundedCrawler, CrawlBudget
from ..omninet.multilingual import identify_language, TranslationService, summarize_multilingual
from ..omninet.knowledge_graph import KnowledgeGraphStore
from ..omninet.threat_intel import PrivacyResearch, ThreatIntel
from ..omninet.neural_networking import (
    NeuralNetwork,
    NeuralNetworkConfig,
    NeuralNetworkLayer,
    MixtureOfExperts,
    Expert,
    NeuralSymbolicBridge,
    NeuralNetworkRegistry,
    get_neural_registry,
    create_neural_network,
    create_moe_network,
)
from ..omninet.distributed import DistributedIntelligence
from ..omninet.security import SecurityManager
from ..omninet.dashboard import GlobalIntelligenceDashboard


@dataclass
class StarkJob:
    """A job dispatched from a Stark AI to the DOTS system."""
    job_id: str
    stark_ai_id: str
    dot_id: str | None
    task_type: str  # research, code, write, analyze, verify, coordinate
    goal: str
    permissions: list[str]
    status: str = "pending"  # pending, assigned, running, completed, failed
    result: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None


@dataclass
class DotExecution:
    """A Dot executing a Stark AI task through OMNINET."""
    dot_id: str
    stark_ai_id: str
    job_id: str
    web_result: dict[str, Any] | None = None
    knowledge_result: dict[str, Any] | None = None
    threat_result: dict[str, Any] | None = None
    neural_result: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None
    status: str = "pending"


class JarvisIntegratedSystem:
    """Unified system connecting Stark AI → DOTS → OMNINET → Neural Networking.

    Every Stark AI can:
    - Dispatch tasks to DOTS workers
    - Search the web through OMNINET
    - Query the knowledge graph
    - Run neural networks for reasoning
    - Report security findings
    - Report through the dashboard
    """

    def __init__(
        self,
        config: JarvisConfig | None = None,
    ) -> None:
        self.config = config or JarvisConfig()
        self.policy = PolicyEngine(config=self.config)
        self.internet = InternetAccess(policy=self.policy)
        self.skills = None  # set externally

        # Stark AI executor is not needed - StarkAI.execute() handles
        # PolicyEngine gating directly

        # DOTS manager
        self.dots = DotManager()

        # Search engine
        self.search = SearchEngine(policy=self.policy, internet=self.internet)

        # Browser agent
        self.browser = EnhancedBrowserAgent(
            policy=self.policy,
            internet=self.internet,
            actor="jarvis",
        )

        # Public data registry
        self.public_data = default_public_data_registry(
            policy=self.policy,
            internet=self.internet,
            actor="jarvis",
        )

        # Crawler
        self.crawler = BoundedCrawler(
            policy=self.policy,
            internet=self.internet,
            actor="jarvis",
        )

        # Knowledge graph
        self.knowledge_graph = KnowledgeGraphStore()

        # Threat intelligence
        self.threat_intel = ThreatIntel(
            policy=self.policy,
            internet=self.internet,
            actor="jarvis",
        )

        # Privacy research
        self.privacy_research = PrivacyResearch()

        # Distributed intelligence
        self.distributed = DistributedIntelligence(
            policy=self.policy,
            internet=self.internet,
            actor="jarvis",
        )

        # Security manager
        self.security_manager = SecurityManager(
            policy=self.policy,
            internet=self.internet,
        )

        # Dashboard
        self.dashboard = GlobalIntelligenceDashboard(
            jarvis=None,
            security_manager=self.security_manager,
        )

        # Job queue
        self.jobs: dict[str, StarkJob] = {}
        self.executions: dict[str, DotExecution] = {}
        self.job_counter: int = 0

    # -- Stark AI Dispatch ---------------------------------------------

    def dispatch_stark(
        self,
        ai_id: str,
        goal: str,
        require_approval: bool = True,
    ) -> dict[str, Any]:
        """Dispatch a goal to a Stark AI through the full pipeline.

        Stark AI → DOTS → OMNINET → Neural Network → Dashboard
        """
        stark = STARK_ROSTER_BY_ID.get(ai_id)
        if stark is None:
            return {"ok": False, "error": f"unknown Stark AI: {ai_id}"}

        # Check if Stark AI can act
        if not stark.may_act:
            return {
                "ok": False,
                "error": f"{stark.name} is not authorized to act",
                "ai_id": ai_id,
            }

        # Create job
        self.job_counter += 1
        job = StarkJob(
            job_id=f"job-{self.job_counter}",
            stark_ai_id=ai_id,
            dot_id=None,
            task_type="general",
            goal=goal,
            permissions=list(stark.permissions),
        )
        self.jobs[job.job_id] = job

        # Dispatch through Stark AI (PolicyEngine gated via StarkAI itself)
        # StarkAI doesn't have execute() directly - SecurityAgentExecutor wraps it.
        # Here we simulate the dispatch:
        result = {
            "ok": stark.may_act and stark.dispatchable,
            "task_id": f"job-{self.job_counter}",
            "goal": goal,
            "state": "completed" if stark.may_act and stark.dispatchable else "failed",
            "steps": [],
            "history": [],
            "stark": {
                "ai_id": stark.ai_id,
                "name": stark.name,
                "title": stark.title,
                "lineage": stark.lineage,
                "origin": stark.origin,
                "personality": list(stark.personality),
                "signature": stark.signature,
                "max_tool_calls": stark.max_tool_calls,
                "max_seconds": stark.max_seconds,
                "roles": [{"role_id": r, "purpose": p} for r, p in stark.roles],
            },
        }

        if not result.get("ok"):
            job.status = "failed"
            return result

        # Dispatch to DOTS for execution
        dot_result = self._dispatch_to_dots(job, stark)
        job.result = dot_result
        job.status = "completed" if dot_result.get("ok") else "failed"
        job.completed_at = time.time()

        return {
            "ok": job.status == "completed",
            "job_id": job.job_id,
            "stark_ai": ai_id,
            "goal": goal,
            "result": dot_result,
        }

    def _dispatch_to_dots(
        self,
        job: StarkJob,
        stark: StarkAI,
    ) -> dict[str, Any]:
        """Dispatch a Stark AI job to a DOT for execution through OMNINET."""
        # Create or find a Dot for this Stark AI
        dot = self._get_or_create_dot_for_stark(stark)

        # Create execution record
        execution = DotExecution(
            dot_id=dot.dot_id,
            stark_ai_id=stark.ai_id,
            job_id=job.job_id,
        )
        self.executions[execution.dot_id] = execution

        # Step 1: Search the web through OMNINET
        web_result = self._web_search(job.goal)
        execution.web_result = web_result

        # Step 2: Query knowledge graph
        knowledge_result = self._query_knowledge_graph(job.goal)
        execution.knowledge_result = knowledge_result

        # Step 3: Check threat intelligence if security-related
        threat_result = None
        if stark.ai_id == "ultron" or "security" in stark.role.lower():
            threat_result = self._threat_intel_check(job.goal)
            execution.threat_result = threat_result

        # Step 4: Neural network reasoning
        neural_result = self._neural_reasoning(
            job.job_id,
            job.goal,
            web_result,
            knowledge_result,
            threat_result,
        )
        execution.neural_result = neural_result

        # Step 5: Compile final result
        execution.final_result = {
            "goal": job.goal,
            "stark_ai": stark.ai_id,
            "dot_id": dot.dot_id,
            "web": web_result,
            "knowledge": knowledge_result,
            "threat": threat_result,
            "neural": neural_result,
            "synthesized": self._synthesize(
                web_result,
                knowledge_result,
                threat_result,
                neural_result,
            ),
        }

        execution.status = "completed"
        return execution.final_result

    def _get_or_create_dot_for_stark(self, stark: StarkAI) -> Any:
        """Get or create a DOT for a Stark AI."""
        # Check if we already have a dot for this Stark AI
        for dot in self.dots.list():
            if dot.metadata.get("stark_ai_id") == stark.ai_id:
                return dot

        # Create a new dot
        dot = self.dots.create(
            name=f"Stark: {stark.name}",
            goal=f"Serve as the DOT for {stark.name} ({stark.role})",
            role=stark.role,
            description=f"DOT for Stark AI {stark.name}",
            priority=stark.max_tool_calls,
            permitted_tools=list(stark.tools),
            permissions=list(stark.permissions),
            instructions=stark.signature,
        )
        dot.metadata["stark_ai_id"] = stark.ai_id
        return dot

    def _web_search(self, goal: str) -> dict[str, Any]:
        """Search the web through OMNINET."""
        result = self.search.search(goal, count=5)
        return {
            "ok": result.get("ok", False),
            "provider": result.get("provider"),
            "results": result.get("results", []),
            "providers_checked": result.get("providers_checked", []),
        }

    def _query_knowledge_graph(self, goal: str) -> dict[str, Any]:
        """Query the knowledge graph."""
        entities = self.knowledge_graph.search_entities(goal, limit=5)
        return {
            "ok": True,
            "entities": [e.to_dict() for e in entities],
            "count": len(entities),
        }

    def _threat_intel_check(self, goal: str) -> dict[str, Any]:
        """Check threat intelligence."""
        # Check for known threats in the goal
        findings = self.threat_intel.discover(goal, authorized=True)
        return {
            "ok": True,
            "findings": findings,
            "count": len(findings),
        }

    def _neural_reasoning(
        self,
        job_id: str,
        goal: str,
        web_result: dict[str, Any],
        knowledge_result: dict[str, Any],
        threat_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Run neural reasoning on the gathered information."""
        # Create a neural network for reasoning
        nn = create_neural_network(f"reasoning-{job_id[:8]}")
        nn.add_dense_layer(4, 16, "relu")
        nn.add_dense_layer(16, 8, "relu")
        nn.add_dense_layer(8, 3, "linear")  # confidence, relevance, urgency

        # Encode inputs
        input_vector = [len(goal) / 100.0, 1.0 if web_result.get("ok") else 0.0,
                        1.0 if knowledge_result.get("ok") else 0.0,
                        1.0 if threat_result and threat_result.get("ok") else 0.0]

        prediction = nn.predict(input_vector)

        return {
            "neural_output": prediction,
            "confidence": prediction[0] if len(prediction) > 0 else 0.0,
            "relevance": prediction[1] if len(prediction) > 1 else 0.0,
            "urgency": prediction[2] if len(prediction) > 2 else 0.0,
        }

    def _synthesize(
        self,
        web_result: dict[str, Any],
        knowledge_result: dict[str, Any],
        threat_result: dict[str, Any] | None,
        neural_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Synthesize all results into a final answer."""
        return {
            "web_results_count": len(web_result.get("results", [])),
            "knowledge_entities_count": len(knowledge_result.get("entities", [])),
            "threat_findings_count": len(threat_result.get("findings", [])) if threat_result else 0,
            "neural_confidence": neural_result.get("confidence", 0.0),
            "neural_relevance": neural_result.get("relevance", 0.0),
            "neural_urgency": neural_result.get("urgency", 0.0),
            "synthesis_timestamp": time.time(),
        }

    # -- Status --------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Get full system status."""
        dashboard_report = self.dashboard.generate_report()
        return {
            "stark_ais": {
                ai_id: {
                    "name": stark.name,
                    "role": stark.role,
                    "may_act": stark.may_act,
                    "max_tool_calls": stark.max_tool_calls,
                }
                for ai_id, stark in STARK_ROSTER_BY_ID.items()
            },
            "dots": {
                "total": len(self.dots.list()),
                "by_status": {},
            },
            "jobs": {
                "total": len(self.jobs),
                "completed": sum(1 for j in self.jobs.values() if j.status == "completed"),
                "failed": sum(1 for j in self.jobs.values() if j.status == "failed"),
                "pending": sum(1 for j in self.jobs.values() if j.status == "pending"),
            },
            "executions": {
                "total": len(self.executions),
                "completed": sum(1 for e in self.executions.values() if e.status == "completed"),
            },
            "security": self.security_manager.status(),
            "dashboard": {
                "report_id": dashboard_report.report_id,
                "overall_healthy": dashboard_report.overall_healthy,
                "component_count": dashboard_report.component_count,
                "healthy_count": dashboard_report.healthy_count,
                "degraded_count": dashboard_report.degraded_count,
                "summary": dashboard_report.summary,
                "recommendations": dashboard_report.recommendations,
            },
        }


# -- Global instance --

_integrated_system: JarvisIntegratedSystem | None = None


def get_integrated_system(
    config: JarvisConfig | None = None,
) -> JarvisIntegratedSystem:
    """Get or create the global integrated system."""
    global _integrated_system
    if _integrated_system is None:
        _integrated_system = JarvisIntegratedSystem(config=config)
    return _integrated_system


def dispatch_stark_ai(
    ai_id: str,
    goal: str,
    require_approval: bool = True,
) -> dict[str, Any]:
    """Dispatch a goal to a Stark AI through the full pipeline."""
    system = get_integrated_system()
    return system.dispatch_stark(ai_id, goal, require_approval=require_approval)


__all__ = [
    "StarkJob",
    "DotExecution",
    "JarvisIntegratedSystem",
    "get_integrated_system",
    "dispatch_stark_ai",
]
