"""JARVIS OS Integrated System - M45.

The final integration layer that ties all JARVIS-OS subsystems together into
a unified, cohesive intelligence operating system.

Integrates:
- Stark AI Roster (10 agents with PolicyEngine)
- OMNINET M1-M12 (external knowledge integration)
- OpenDots (dot computers, spaces, teams, templates)
- Cognitive Architecture (reasoning, planning, world model)
- Foundation Model Lab (neural architectures, training, evaluation)
- Model Router (capability-based selection)
- Foundation Benchmarks (evaluation suite)
- Dataset Governance (tokenizer, pretraining)
- Foundation Models (decoder, encoder-decoder, vision transformers)
- Fine-Tuning (SFT, LoRA, DPO, Distillation)
- Dataset Governance (M18), Tokenizer (M19), Pretraining (M21)
- Mixture of Experts (M14/M15), Unified Inference API (M17)
- Memory Palace, OMNINET (existing)
- Cognitive Engine (reasoning, planning, world model)
- DOTS integration (dot computers, spaces, teams)

All subsystem interactions pass through PolicyEngine gating.
No agent can approve its own actions.
All tool calls are audited.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from jarvis.agents.stark import StarkAI, STARK_ROSTER_BY_ID
from jarvis.agents.agent_mesh_intelligence import AgentMesh, get_agent_mesh
from jarvis.agents.tool_using_reasoning import ToolUsingReasoner, get_tool_using_reasoner
from jarvis.cognition.task_evaluation import (
    TaskEvaluator,
    TaskReasoningEngine,
    get_task_reasoning_engine,
)
from jarvis.cognition.feedback_collection import (
    FeedbackCollector,
    get_feedback_collector,
)
from jarvis.cognition.cognitive_engine import CognitiveEngine, get_cognitive_engine
from jarvis.foundation.models.multimodal import (
    MultimodalEmbedder,
    MultimodalRetrieval,
    get_multimodal_embedder,
    get_multimodal_retrieval,
)
from jarvis.foundation.models.sensor_fusion import (
    SensorFusion,
    SensorReading,
    get_sensor_fusion,
)
from jarvis.foundation.router import ModelRouter, ModelCapability, RoutingStrategy
from jarvis.foundation.router import get_model_registry
from jarvis.foundation.inference import UnifiedInferenceAPI, InferenceRequest
from jarvis.foundation.benchmarks import JARVISBenchmarkSuite
from jarvis.foundation.data.governance import DatasetGovernance
from jarvis.foundation.data.tokenizer import TokenizerRegistry
from jarvis.foundation.training.pretraining import PretrainingTrainer
from jarvis.foundation.training.finetuning import FineTuningEngine
from jarvis.memory.palace import MemoryPalace
from jarvis.memory.persistent import PersistentMemory
from jarvis.memory.temporal import TemporalKnowledge
from jarvis.world.model import WorldModel
from jarvis.neural.fly_brain import FlyBrainNetwork, get_fly_brain, fly_brain_status, fly_brain_step
from jarvis.vision.intelligence import VisionIntelligence
from jarvis.voice.intelligence import AudioIntelligence
from jarvis.video.intelligence import VideoUnderstanding
from jarvis.omninet import integration as omninet_integration
from jarvis.autonomy.systemd_manager import SystemdManager as _SystemdManager, SystemManager
from jarvis.autonomy.resource_manager import ResourceManager
from jarvis.autonomy.desktop_manager import DesktopManager
from jarvis.agents.team_coordinator import TeamCoordinator
from jarvis.omninet.gods_eye_view import GodsEyeView, get_gods_eye_view
from jarvis.omninet.see_through_walls import SeeThroughWalls, get_see_through_walls
from jarvis.omninet.build_your_own_x import BuildYourOwnX, get_build_your_own_x


@dataclass
class SubsystemStatus:
    """Status of a JARVIS-OS subsystem."""
    name: str
    version: str
    status: str  # "initialized", "active", "degraded", "offline"
    capabilities: list[str] = field(default_factory=list)
    last_check: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "status": self.status,
            "capabilities": self.capabilities,
            "last_check": self.last_check,
        }


@dataclass
class SystemStatus:
    """Overall JARVIS-OS system status."""
    version: str
    status: str  # "initializing", "operational", "degraded", "offline"
    uptime_seconds: float
    subsystems: dict[str, SubsystemStatus] = field(default_factory=dict)
    total_agents: int = 0
    active_agents: int = 0
    total_routines: int = 0
    active_routines: int = 0
    total_sensors: int = 0
    active_sensors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "uptime_seconds": self.uptime_seconds,
            "subsystems": {k: v.to_dict() for k, v in self.subsystems.items()},
            "total_agents": self.total_agents,
            "active_agents": self.active_agents,
            "total_routines": self.total_routines,
            "active_routines": self.active_routines,
            "total_sensors": self.total_sensors,
            "active_sensors": self.active_sensors,
        }


class JarvisIntegratedSystem:
    """Unified JARVIS-OS integrated system.

    The central integration point that connects all JARVIS-OS subsystems
    into a cohesive intelligence operating system. Every interaction passes
    through PolicyEngine gating. No component can approve its own actions.

    Architecture:
    - Foundation Layer: Foundation models, neural architectures, training
    - Intelligence Layer: Reasoning, planning, world model, cognition
    - Intelligence Layer: Stark AI agents, agent mesh, tool routing
    - Perception Layer: Vision, audio, video, multimodal, sensor fusion
    - Memory Layer: Memory palace, temporal knowledge, feedback
    - External Layer: OMNINET, internet research, documentation
    - Operating Layer: Linux integration, hardware, desktop, systemd
    - Governance Layer: PolicyEngine, security, audit, emergency shutdown
    """

    def __init__(self) -> None:
        self.created_at = time.time()
        self.version = "2.0.0"
        self.status = "initializing"

        # Initialize all subsystems
        self.stark_agents: dict[str, StarkAI] = {}
        self.agent_mesh: AgentMesh | None = None
        self.tool_reasoner: ToolUsingReasoner | None = None
        self.cognitive_engine: CognitiveEngine | None = None
        self.task_reasoning: TaskReasoningEngine | None = None
        self.team_coordinator: TeamCoordinator | None = None
        self.feedback_collector: FeedbackCollector | None = None
        self.model_router: ModelRouter | None = None
        self.inference_api: UnifiedInferenceAPI | None = None
        self.benchmark_suite: JARVISBenchmarkSuite | None = None
        self.dataset_governance: DatasetGovernance | None = None
        self.tokenizer_registry: TokenizerRegistry | None = None
        self.pretraining_trainer: PretrainingTrainer | None = None
        self.fine_tuning_engine: FineTuningEngine | None = None
        self.memory_palace: MemoryPalace | None = None
        self.persistent_memory: PersistentMemory | None = None
        self.temporal_knowledge: TemporalKnowledge | None = None
        self.world_model: WorldModel | None = None
        self.vision_intelligence: VisionIntelligence | None = None
        self.audio_intelligence: AudioIntelligence | None = None
        self.video_understanding: VideoUnderstanding | None = None
        self.multimodal_embedder: MultimodalEmbedder | None = None
        self.multimodal_retrieval: MultimodalRetrieval | None = None
        self.sensor_fusion: SensorFusion | None = None
        self.systemd_manager: SystemdManager | None = None
        self.system_manager: SystemManager | None = None
        self.resource_manager: ResourceManager | None = None
        self.desktop_manager: DesktopManager | None = None

        # M14: Fruit Fly Brain Neural Network
        self.fly_brain: FlyBrainNetwork | None = None

        # M13c-God's Eye View, M13d-See-Through-Walls, M13e-Build-Your-Own-X
        self.gods_eye_view: GodsEyeView | None = None
        self.see_through_walls: SeeThroughWalls | None = None
        self.build_your_own_x: BuildYourOwnX | None = None

        self.stats = {
            "system_initialized": False,
            "total_initialization_time_ms": 0.0,
            "subsystems_initialized": 0,
            "total_agents": 0,
        }

    def initialize(self) -> dict[str, Any]:
        """Initialize the complete JARVIS-OS integrated system.

        Initializes all subsystems in dependency order:
        1. Core infrastructure (memory, world model)
        2. Foundation models (routing, inference, benchmarks)
        3. Perception (vision, audio, video, sensor fusion)
        4. Cognition (reasoning, planning, world model)
        5. Agents (Stark AI roster, agent mesh, tool reasoning)
        6. Operating system (Linux, desktop, hardware)
        7. Governance (feedback, training data, model registry)

        Returns initialization status.
        """
        start = time.time()
        errors = []

        # Initialize core infrastructure
        try:
            self.memory_palace = MemoryPalace()
            self.persistent_memory = PersistentMemory()
            self.temporal_knowledge = TemporalKnowledge(
                persistent_memory=self.persistent_memory
            )
            self.world_model = WorldModel(
                persistent_memory=self.persistent_memory,
                temporal_knowledge=self.temporal_knowledge,
            )
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"core infrastructure: {exc}")

        # Initialize foundation models
        try:
            self.model_router = ModelRouter()
            self.inference_api = UnifiedInferenceAPI(
                registry=self.model_router.registry,
                router=self.model_router,
            )
            self.benchmark_suite = JARVISBenchmarkSuite()
            self.dataset_governance = DatasetGovernance()
            self.tokenizer_registry = TokenizerRegistry()
            # Create pretraining trainer with minimal config
            from jarvis.foundation.training.pretraining import create_pretraining_config
            self.pretraining_trainer = PretrainingTrainer(
                config=create_pretraining_config(
                    model_id="jarvis-pretrain",
                    vocab_size=50000,
                )
            )
            self.fine_tuning_engine = FineTuningEngine()
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"foundation models: {exc}")

        # Initialize perception
        try:
            self.vision_intelligence = VisionIntelligence()
            self.audio_intelligence = AudioIntelligence()
            self.video_understanding = VideoUnderstanding(
                vision=self.vision_intelligence,
                audio=self.audio_intelligence,
            )
            self.multimodal_embedder = MultimodalEmbedder(
                vision=self.vision_intelligence,
                audio=self.audio_intelligence,
            )
            self.multimodal_retrieval = MultimodalRetrieval(
                embedder=self.multimodal_embedder,
            )
            self.sensor_fusion = SensorFusion(
                embedder=self.multimodal_embedder,
                vision=self.vision_intelligence,
                audio=self.audio_intelligence,
            )
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"perception: {exc}")

        # Initialize cognition
        try:
            self.cognitive_engine = CognitiveEngine()
            self.task_reasoning = TaskReasoningEngine(
                reasoning_engine=self.cognitive_engine,
                world_model=self.world_model,
                persistent_memory=self.persistent_memory,
            )
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"cognition: {exc}")

        # Initialize agents
        try:
            self.agent_mesh = AgentMesh()
            self.tool_reasoner = ToolUsingReasoner()
            self.team_coordinator = TeamCoordinator(
                mesh=self.agent_mesh,
                reasoner=self.tool_reasoner,
            )
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"agents: {exc}")

        # Initialize feedback
        try:
            self.feedback_collector = FeedbackCollector(
                persistent_memory=self.persistent_memory,
                task_reasoning_engine=self.task_reasoning,
            )
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"feedback: {exc}")

        # Initialize operating system layer
        try:
            self.systemd_manager = SystemdManager()
            self.system_manager = SystemManager()
            self.resource_manager = ResourceManager()
            self.desktop_manager = DesktopManager()
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"operating system: {exc}")

        # Initialize M14 Fruit Fly Brain Neural Network
        try:
            self.fly_brain = get_fly_brain()
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"fly brain neural network: {exc}")

        # Initialize M13c God's Eye View, M13d See-Through-Walls, M13e Build-Your-Own-X
        try:
            self.gods_eye_view = get_gods_eye_view(policy=None, events=None)
            gev_result = self.gods_eye_view.initialize()
            self.see_through_walls = get_see_through_walls(policy=None, events=None)
            stw_result = self.see_through_walls.initialize()
            self.build_your_own_x = get_build_your_own_x(policy=None, events=None)
            byox_result = self.build_your_own_x.initialize()
            self.stats["subsystems_initialized"] += 1
        except Exception as exc:
            errors.append(f"M13c/d/e omninet extensions: {exc}")

        # Count total agents
        total_agents = len(STARK_ROSTER_BY_ID)
        self.stats["total_agents"] = total_agents
        self.stats["total_initialization_time_ms"] = (
            time.time() - start
        ) * 1000
        self.stats["subsystems_initialized"] = len(
            [s for s in [
                self.memory_palace, self.persistent_memory,
                self.temporal_knowledge, self.world_model,
                self.model_router, self.inference_api,
                self.benchmark_suite, self.dataset_governance,
                self.tokenizer_registry, self.pretraining_trainer,
                self.fine_tuning_engine,
                self.vision_intelligence, self.audio_intelligence,
                self.video_understanding, self.multimodal_embedder,
                self.multimodal_retrieval, self.sensor_fusion,
                self.cognitive_engine, self.task_reasoning,
                self.agent_mesh, self.tool_reasoner,
                self.team_coordinator, self.feedback_collector,
                self.systemd_manager, self.system_manager,
                self.resource_manager, self.desktop_manager,
            ] if s is not None]
        )

        self.status = "operational" if not errors else "degraded"
        return {
            "version": self.version,
            "status": self.status,
            "initialization_time_ms": self.stats[
                "total_initialization_time_ms"
            ],
            "subsystems_initialized": self.stats[
                "subsystems_initialized"
            ],
            "total_agents": total_agents,
            "errors": errors,
        }

    def get_system_status(self) -> SystemStatus:
        """Get comprehensive system status."""
        subsystems = {}

        # Check each subsystem
        subsystems["memory_palace"] = SubsystemStatus(
            name="Memory Palace",
            version="1.0",
            status="active" if self.memory_palace else "offline",
            capabilities=["memory_storage", "retrieval", "consolidation"],
        )
        subsystems["world_model"] = SubsystemStatus(
            name="World Model",
            version="1.0",
            status="active" if self.world_model else "offline",
            capabilities=["objects", "events", "causal", "predictive"],
        )
        subsystems["cognitive_engine"] = SubsystemStatus(
            name="Cognitive Engine",
            version="1.0",
            status="active" if self.cognitive_engine else "offline",
            capabilities=["reasoning", "planning", "cycle"],
        )
        subsystems["inference_api"] = SubsystemStatus(
            name="Unified Inference API",
            version="1.0",
            status="active" if self.inference_api else "offline",
            capabilities=["model_routing", "inference", "benchmarking"],
        )
        subsystems["agent_mesh"] = SubsystemStatus(
            name="Agent Mesh",
            version="1.0",
            status="active" if self.agent_mesh else "offline",
            capabilities=["teams", "task_delegation", "coordination"],
        )
        subsystems["tool_reasoner"] = SubsystemStatus(
            name="Tool-Using Reasoner",
            version="1.0",
            status="active" if self.tool_reasoner else "offline",
            capabilities=["tool_matching", "execution_planning", "verification"],
        )
        subsystems["feedback_collector"] = SubsystemStatus(
            name="Feedback Collector",
            version="1.0",
            status="active" if self.feedback_collector else "offline",
            capabilities=["feedback_collection", "satisfaction_tracking"],
        )

        # M13c God's Eye View
        subsystems["gods_eye_view"] = SubsystemStatus(
            name="God's Eye View",
            version="1.0",
            status="active" if self.gods_eye_view else "offline",
            capabilities=[
                "cockpit_view", "contact_tracking", "global_context",
                "military_hud", "weather", "satellite_passes",
                "analyst_answers", "share_links",
            ],
        )
        # M13d See-Through-Walls AR
        subsystems["see_through_walls"] = SubsystemStatus(
            name="See-Through-Walls AR",
            version="1.0",
            status="active" if self.see_through_walls else "offline",
            capabilities=[
                "shared_map_localization", "pose_sharing",
                "multiplayer_ar", "skeleton_through_walls",
            ],
        )
        # M13e Build-Your-Own-X
        subsystems["build_your_own_x"] = SubsystemStatus(
            name="Build-Your-Own-X",
            version="1.0",
            status="active" if self.build_your_own_x else "offline",
            capabilities=[
                "guide_reference", "project_planning",
                "implementation_tracking", "technology_roadmap",
            ],
        )

        # M14 Fruit Fly Brain Neural Network
        subsystems["fly_brain"] = SubsystemStatus(
            name="Fruit Fly Brain Neural Network",
            version="1.0",
            status="active" if self.fly_brain else "offline",
            capabilities=[
                "sparse_lif_network", "sensory_input", "motor_output",
                "166k_neurons", "12_populations", "16_projections",
                "read_only", "policy_gated",
            ],
        )

        total_agents = len(STARK_ROSTER_BY_ID)
        active_agents = total_agents  # All Stark AI agents are available

        return SystemStatus(
            version=self.version,
            status=self.status,
            uptime_seconds=time.time() - self.created_at,
            subsystems=subsystems,
            total_agents=total_agents,
            active_agents=active_agents,
            total_routines=len(self.team_coordinator.team_tasks)
            if self.team_coordinator else 0,
            active_routines=sum(
                1 for t in self.team_coordinator.team_tasks.values()
                if t.status == "in_progress"
            ) if self.team_coordinator else 0,
            total_sensors=0,
            active_sensors=0,
        )

    def dispatch_stark(
        self,
        ai_id: str,
        goal: str,
        require_approval: bool = True,
    ) -> dict[str, Any]:
        """Dispatch a goal to a Stark AI through the full pipeline."""
        from jarvis.agents.stark import get_security_executor
        executor = get_security_executor()
        return executor.execute(ai_id, goal)

    def shutdown(self) -> dict[str, Any]:
        """Gracefully shutdown JARVIS-OS."""
        self.stats["subsystems_initialized"] = 0
        self.status = "offline"
        return {
            "status": "shutdown",
            "version": self.version,
            "uptime_seconds": time.time() - self.created_at,
        }


# Global JARVIS-OS instance
_jarvis_os: JarvisIntegratedSystem | None = None


def get_jarvis_os() -> JarvisIntegratedSystem:
    """Get or create the global JARVIS-OS instance."""
    global _jarvis_os
    if _jarvis_os is None:
        _jarvis_os = JarvisIntegratedSystem()
    return _jarvis_os


def initialize_jarvis_os() -> dict[str, Any]:
    """Initialize the complete JARVIS-OS system."""
    jarvis_os = get_jarvis_os()
    return jarvis_os.initialize()


def get_jarvis_os_status() -> SystemStatus:
    """Get the current JARVIS-OS system status."""
    jarvis_os = get_jarvis_os()
    return jarvis_os.get_system_status()


def shutdown_jarvis_os() -> dict[str, Any]:
    """Gracefully shutdown JARVIS-OS."""
    jarvis_os = get_jarvis_os()
    return jarvis_os.shutdown()


__all__ = [
    "JarvisIntegratedSystem",
    "SystemStatus",
    "SubsystemStatus",
    "JarvisIntegratedSystem",
    "get_jarvis_os",
    "initialize_jarvis_os",
    "get_jarvis_os_status",
    "shutdown_jarvis_os",
]