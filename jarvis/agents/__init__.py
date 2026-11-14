"""Agent system exports."""

from .agents import Agent, AgentRegistry, PlanStep, Planner, Supervisor, default_agents
from .enhanced_planner import EnhancedPlanStep, EnhancedPlanner, plan_goal
from .enhanced_supervisor import EnhancedSupervisor, DelegatedStep
from .security_agent import SecurityAgent, SecurityVerdict
from .agent_mesh_intelligence import (
    AgentTeam,
    AgentTaskResult,
    AgentMesh,
    get_agent_mesh,
)
from .tool_using_reasoning import (
    ToolCapability,
    ToolSelection,
    ToolExecutionPlan,
    ToolExecutionResult,
    ToolCapabilityMatcher,
    ToolExecutionPlanner,
    ToolExecutor,
    ToolUsingReasoner,
    get_tool_using_reasoner,
)
from .stark_roster_500 import (
    STARK_ROSTER_500,
    stark_roster_500_by_id,
    generate_stark_agents,
    count_by_category as stark_count_by_category,
    list_categories as stark_list_categories,
)
from .ai_bots_250 import (
    AI_BOTS_250,
    ai_bots_250_by_id,
    generate_ai_bots,
    count_by_category as bots_count_by_category,
    list_categories as bots_list_categories,
)
from .medical_advisor import (
    MedicalAdvisor,
    MedicalQuery,
    MedicalResponse,
    get_medical_advisor,
)
from .legal_advisor import (
    LegalAdvisor,
    LegalQuery,
    LegalResponse,
    get_legal_advisor,
)
from .financial_advisor import (
    FinancialAdvisor,
    FinancialQuery,
    FinancialResponse,
    get_financial_advisor,
)
from .scientific_advisor import (
    ScientificAdvisor,
    ScientificQuery,
    ScientificResponse,
    get_scientific_advisor,
)

__all__ = [
    "Agent",
    "AgentRegistry",
    "PlanStep",
    "Planner",
    "Supervisor",
    "default_agents",
    "EnhancedPlanStep",
    "EnhancedPlanner",
    "plan_goal",
    "EnhancedSupervisor",
    "DelegatedStep",
    "SecurityAgent",
    "SecurityVerdict",
    "AgentTeam",
    "AgentTaskResult",
    "AgentMesh",
    "get_agent_mesh",
    "ToolCapability",
    "ToolSelection",
    "ToolExecutionPlan",
    "ToolExecutionResult",
    "ToolCapabilityMatcher",
    "ToolExecutionPlanner",
    "ToolExecutor",
    "ToolUsingReasoner",
    "get_tool_using_reasoner",
    # Expanded Stark AI roster (500 agents)
    "STARK_ROSTER_500",
    "stark_roster_500_by_id",
    "generate_stark_agents",
    "stark_count_by_category",
    "stark_list_categories",
    # AI Bot roster (250 bots)
    "AI_BOTS_250",
    "ai_bots_250_by_id",
    "generate_ai_bots",
    "bots_count_by_category",
    "bots_list_categories",
    # Domain-specific advisory agents
    "MedicalAdvisor",
    "MedicalQuery",
    "MedicalResponse",
    "get_medical_advisor",
    "LegalAdvisor",
    "LegalQuery",
    "LegalResponse",
    "get_legal_advisor",
    "FinancialAdvisor",
    "FinancialQuery",
    "FinancialResponse",
    "get_financial_advisor",
    "ScientificAdvisor",
    "ScientificQuery",
    "ScientificResponse",
    "get_scientific_advisor",
]
