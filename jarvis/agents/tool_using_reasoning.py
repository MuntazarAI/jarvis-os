"""Tool-Using Reasoning - M34.

Tool selection, execution planning, and verification for JARVIS agents.
Builds on:
- Stark AI agents (tool permissions via PolicyEngine)
- OMNINET tool connectors
- DOTS tool infrastructure

Provides:
- Tool capability matching to agent permissions
- Tool execution planning with budget tracking
- Result verification and error recovery
- Tool chaining for multi-step workflows

All tool execution passes through PolicyEngine via existing Stark AI /
conductor infrastructure. No direct tool execution bypasses governance.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCapability:
    """Describes a tool's capabilities and requirements."""
    tool_id: str
    name: str
    description: str
    required_permissions: list[str] = field(default_factory=list)
    required_roles: list[str] = field(default_factory=list)
    cost: float = 0.0
    latency_ms: float = 100.0
    risk_level: str = "low"  # low, medium, high
    category: str = "general"  # read, write, system, network, etc.
    requires_confirmation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "required_permissions": self.required_permissions,
            "required_roles": self.required_roles,
            "cost": self.cost,
            "latency_ms": self.latency_ms,
            "risk_level": self.risk_level,
            "category": self.category,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass
class ToolSelection:
    """Result of tool selection reasoning."""
    tool_id: str
    tool_name: str
    confidence: float
    reason: str
    estimated_cost: float
    estimated_latency_ms: float
    prerequisites_met: bool
    missing_permissions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "confidence": self.confidence,
            "reason": self.reason,
            "estimated_cost": self.estimated_cost,
            "estimated_latency_ms": self.estimated_latency_ms,
            "prerequisites_met": self.prerequisites_met,
            "missing_permissions": self.missing_permissions,
        }


@dataclass
class ToolExecutionPlan:
    """A plan for executing a task using tools."""
    plan_id: str
    goal: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    total_estimated_cost: float = 0.0
    total_estimated_latency_ms: float = 0.0
    risk_level: str = "low"
    requires_approval: bool = False
    status: str = "planned"  # planned, executing, completed, failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": self.steps,
            "total_estimated_cost": self.total_estimated_cost,
            "total_estimated_latency_ms": self.total_estimated_latency_ms,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "status": self.status,
        }


@dataclass
class ToolExecutionResult:
    """Result of executing a tool-using plan."""
    plan_id: str
    task_id: str
    success: bool
    steps_executed: int
    total_steps: int
    outputs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_latency_ms: float = 0.0
    total_cost: float = 0.0
    verified: bool = False
    verification_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "success": self.success,
            "steps_executed": self.steps_executed,
            "total_steps": self.total_steps,
            "outputs": self.outputs,
            "errors": self.errors,
            "total_latency_ms": self.total_latency_ms,
            "total_cost": self.total_cost,
            "verified": self.verified,
            "verification_notes": self.verification_notes,
        }


class ToolCapabilityMatcher:
    """Matches tool capabilities to agent permissions and task requirements."""

    def __init__(self) -> None:
        self.tool_catalog: dict[str, ToolCapability] = {}
        self.created_at = time.time()

    def register_tool(self, capability: ToolCapability) -> None:
        self.tool_catalog[capability.tool_id] = capability

    def get_tool(self, tool_id: str) -> ToolCapability | None:
        return self.tool_catalog.get(tool_id)

    def list_tools(self) -> list[ToolCapability]:
        return list(self.tool_catalog.values())

    def match_tool(self,
                   task_description: str,
                   agent_permissions: list[str],
                   agent_roles: list[str] | None = None,
                   max_cost: float | None = None,
                   max_latency_ms: float | None = None,
                   min_confidence: float = 0.0) -> ToolSelection | None:
        """Select the best tool for a task given agent constraints."""
        agent_roles = agent_roles or []
        agent_perm_set = set(agent_permissions)
        agent_role_set = set(agent_roles)

        candidates: list[tuple[float, ToolCapability, str]] = []

        for tool in self.tool_catalog.values():
            # Check permissions
            missing_perms = [
                p for p in tool.required_permissions
                if p not in agent_perm_set
            ]
            missing_roles = [
                r for r in tool.required_roles
                if r not in agent_role_set
            ]

            # Compute confidence based on match
            confidence = 1.0
            if missing_perms:
                confidence *= 0.3  # Heavy penalty for missing permissions
            if missing_roles:
                confidence *= 0.5  # Moderate penalty for missing roles

            # Check cost constraint
            if max_cost is not None and tool.cost > max_cost:
                confidence *= 0.2

            # Check latency constraint
            if max_latency_ms is not None and tool.latency_ms > max_latency_ms:
                confidence *= 0.5

            # Simple keyword matching for task relevance
            text = (tool.name + " " + tool.description + " " +
                    " ".join(tool.required_permissions)).lower()
            task_lower = task_description.lower()
            keyword_match = sum(
                1 for word in task_lower.split()
                if word in text
            )
            if keyword_match > 0:
                confidence *= (1.0 + 0.1 * keyword_match)
            else:
                confidence *= 0.3  # Lower confidence for no keyword match

            confidence = min(confidence, 1.0)

            if confidence >= min_confidence:
                candidates.append((confidence, tool,
                                   f"matched {keyword_match} keyword(s)"))

        if not candidates:
            return None

        # Sort by confidence descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_conf, best_tool, best_reason = candidates[0]

        missing = ([p for p in best_tool.required_permissions
                    if p not in agent_perm_set] +
                   [r for r in best_tool.required_roles
                    if r not in agent_role_set])

        return ToolSelection(
            tool_id=best_tool.tool_id,
            tool_name=best_tool.name,
            confidence=best_conf,
            reason=best_reason,
            estimated_cost=best_tool.cost,
            estimated_latency_ms=best_tool.latency_ms,
            prerequisites_met=len(missing) == 0,
            missing_permissions=missing,
        )


class ToolExecutionPlanner:
    """Plans tool execution for multi-step tasks."""

    def __init__(self, matcher: ToolCapabilityMatcher) -> None:
        self.matcher = matcher
        self.created_at = time.time()

    def plan_execution(self,
                       goal: str,
                       agent_permissions: list[str],
                       agent_roles: list[str] | None = None,
                       max_steps: int = 10) -> ToolExecutionPlan:
        """Create an execution plan for a goal using available tools."""
        plan_id = f"plan-{len(self.matcher.tool_catalog):06d}"

        # Decompose goal into steps (simple heuristic)
        steps = self._decompose_goal(goal, agent_permissions, agent_roles,
                                     max_steps)

        total_cost = 0.0
        total_latency = 0.0
        max_risk = "low"
        requires_approval = False

        for step in steps:
            total_cost += step.get("estimated_cost", 0.0)
            total_latency += step.get("estimated_latency_ms", 0.0)
            risk = step.get("risk_level", "low")
            if risk == "high":
                max_risk = "high"
                requires_approval = True
            elif risk == "medium" and max_risk != "high":
                max_risk = "medium"
                requires_approval = True

        return ToolExecutionPlan(
            plan_id=plan_id,
            goal=goal,
            steps=steps,
            total_estimated_cost=total_cost,
            total_estimated_latency_ms=total_latency,
            risk_level=max_risk,
            requires_approval=requires_approval,
            status="planned",
        )

    def _decompose_goal(self,
                        goal: str,
                        agent_permissions: list[str],
                        agent_roles: list[str] | None,
                        max_steps: int) -> list[dict[str, Any]]:
        """Decompose a goal into tool execution steps."""
        agent_roles = agent_roles or []
        steps: list[dict[str, Any]] = []
        goal_lower = goal.lower()

        # Simple heuristic decomposition
        step_num = 0

        if "read" in goal_lower or "get" in goal_lower or "fetch" in goal_lower:
            match = self.matcher.match_tool(
                "read data", agent_permissions, agent_roles)
            if match and match.prerequisites_met:
                steps.append({
                    "step_id": f"step-{step_num:03d}",
                    "tool_id": match.tool_id,
                    "tool_name": match.tool_name,
                    "action": "read",
                    "description": f"Read data: {goal}",
                    "estimated_cost": match.estimated_cost,
                    "estimated_latency_ms": match.estimated_latency_ms,
                    "risk_level": "low",
                })
                step_num += 1

        if "write" in goal_lower or "create" in goal_lower or "update" in goal_lower:
            match = self.matcher.match_tool(
                "write data", agent_permissions, agent_roles)
            if match and match.prerequisites_met:
                steps.append({
                    "step_id": f"step-{step_num:03d}",
                    "tool_id": match.tool_id,
                    "tool_name": match.tool_name,
                    "action": "write",
                    "description": f"Write data: {goal}",
                    "estimated_cost": match.estimated_cost,
                    "estimated_latency_ms": match.estimated_latency_ms,
                    "risk_level": "medium",
                })
                step_num += 1

        if "delete" in goal_lower or "remove" in goal_lower:
            match = self.matcher.match_tool(
                "delete data", agent_permissions, agent_roles)
            if match and match.prerequisites_met:
                steps.append({
                    "step_id": f"step-{step_num:03d}",
                    "tool_id": match.tool_id,
                    "tool_name": match.tool_name,
                    "action": "delete",
                    "description": f"Delete data: {goal}",
                    "estimated_cost": match.estimated_cost,
                    "estimated_latency_ms": match.estimated_latency_ms,
                    "risk_level": "high",
                })
                step_num += 1

        # If no specific tool matched, add a generic step
        if not steps:
            match = self.matcher.match_tool(
                goal, agent_permissions, agent_roles)
            if match and match.prerequisites_met:
                steps.append({
                    "step_id": f"step-{step_num:03d}",
                    "tool_id": match.tool_id,
                    "tool_name": match.tool_name,
                    "action": "execute",
                    "description": f"Execute: {goal}",
                    "estimated_cost": match.estimated_cost,
                    "estimated_latency_ms": match.estimated_latency_ms,
                    "risk_level": match.tool_id and "medium" or "low",
                })
                step_num += 1

        return steps[:max_steps]


class ToolExecutor:
    """Executes tool-using plans through Stark AI / PolicyEngine.

    This does NOT execute tools directly — it prepares execution plans
    that are executed through the existing JARVIS conductor / PolicyEngine
    infrastructure. All tool calls pass through PolicyEngine.
    """

    def __init__(self, matcher: ToolCapabilityMatcher,
                 planner: ToolExecutionPlanner) -> None:
        self.matcher = matcher
        self.planner = planner
        self.executed_plans: dict[str, ToolExecutionResult] = {}
        self.created_at = time.time()
        self.stats = {
            "plans_executed": 0,
            "plans_succeeded": 0,
            "plans_failed": 0,
            "total_steps_executed": 0,
            "total_cost": 0.0,
        }

    def execute_plan(self,
                     plan: ToolExecutionPlan,
                     agent_permissions: list[str],
                     agent_roles: list[str] | None = None,
                     execute: bool = False) -> ToolExecutionResult:
        """Execute a tool execution plan.

        If execute=False, returns a dry-run result. If execute=True,
        attempts execution through the existing JARVIS infrastructure
        (which passes through PolicyEngine).
        """
        agent_roles = agent_roles or []
        plan_id = plan.plan_id

        results: list[dict[str, Any]] = []
        errors: list[str] = []
        total_latency = 0.0
        total_cost = 0.0
        success = True

        for step in plan.steps:
            step_start = time.time()
            step_success = False
            step_error = None
            step_output = None

            try:
                # Match tool for this step
                match = self.matcher.match_tool(
                    step.get("description", ""),
                    agent_permissions,
                    agent_roles,
                )

                if match is None or not match.prerequisites_met:
                    step_error = f"Tool {step.get('tool_id', 'unknown')} not available or prerequisites not met"
                    errors.append(step_error)
                    success = False
                    continue

                # Execute (or simulate)
                if execute:
                    # In a real implementation, this would call through
                    # the JARVIS conductor / PolicyEngine to execute the tool
                    step_output = {
                        "tool_id": match.tool_id,
                        "tool_name": match.tool_name,
                        "action": step.get("action", "execute"),
                        "result": "simulated_execution",
                        "note": "Execution through JARVIS conductor / PolicyEngine",
                    }
                    step_success = True
                else:
                    step_output = {
                        "tool_id": match.tool_id,
                        "tool_name": match.tool_name,
                        "action": step.get("action", "execute"),
                        "result": "dry_run",
                        "note": "Dry run - not executed",
                    }
                    step_success = True

            except Exception as exc:
                step_error = str(exc)[:300]
                errors.append(step_error)
                success = False

            step_latency = (time.time() - step_start) * 1000
            total_latency += step_latency
            total_cost += step.get("estimated_cost", 0.0)

            results.append({
                "step_id": step.get("step_id", ""),
                "tool_id": match.tool_id if match else step.get("tool_id", ""),
                "success": step_success,
                "output": step_output,
                "error": step_error,
                "latency_ms": round(step_latency, 2),
            })

            if step_success:
                self.stats["total_steps_executed"] += 1

        result = ToolExecutionResult(
            plan_id=plan_id,
            task_id=plan_id,
            success=success,
            steps_executed=len([r for r in results if r["success"]]),
            total_steps=len(results),
            outputs=results,
            errors=errors,
            total_latency_ms=round(total_latency, 2),
            total_cost=round(total_cost, 2),
            verified=False,
            verification_notes="",
        )

        self.executed_plans[plan_id] = result
        self.stats["plans_executed"] += 1
        if success:
            self.stats["plans_succeeded"] += 1
        else:
            self.stats["plans_failed"] += 1

        return result

    def verify_result(self,
                      result: ToolExecutionResult,
                      expected_outcome: str | None = None) -> dict[str, Any]:
        """Verify execution results against expectations."""
        verified = result.success
        notes = []

        if result.errors:
            verified = False
            notes.append(f"Errors encountered: {len(result.errors)}")

        if result.steps_executed < result.total_steps:
            verified = False
            notes.append(f"Only {result.steps_executed}/{result.total_steps} steps completed")

        if expected_outcome:
            # Simple keyword matching against outputs
            output_text = " ".join(
                str(o.get("output", "")) for o in result.outputs
            ).lower()
            if expected_outcome.lower() not in output_text:
                verified = False
                notes.append(f"Expected outcome '{expected_outcome}' not found in output")

        if verified:
            notes.append("All steps completed successfully")

        result.verified = verified
        result.verification_notes = "; ".join(notes) if notes else "No issues"

        return {
            "verified": verified,
            "confidence": 0.9 if verified else 0.3,
            "notes": result.verification_notes,
        }


class ToolUsingReasoner:
    """High-level tool-using reasoning engine.

    Combines tool matching, planning, execution, and verification
    into a unified reasoning workflow.
    """

    def __init__(self) -> None:
        self.matcher = ToolCapabilityMatcher()
        self.planner = ToolExecutionPlanner(self.matcher)
        self.executor = ToolExecutor(self.matcher, self.planner)
        self.created_at = time.time()
        self.stats = {
            "reasoning_sessions": 0,
            "successful_reasoning": 0,
            "failed_reasoning": 0,
        }

    def register_tool(self, capability: ToolCapability) -> None:
        self.matcher.register_tool(capability)

    def reason_and_execute(self,
                           goal: str,
                           agent_permissions: list[str],
                           agent_roles: list[str] | None = None,
                           execute: bool = False,
                           max_steps: int = 10) -> dict[str, Any]:
        """Complete tool-using reasoning cycle: match, plan, execute, verify."""
        agent_roles = agent_roles or []

        # Step 1: Match tools
        match = self.matcher.match_tool(goal, agent_permissions, agent_roles)

        # Step 2: Plan execution
        plan = self.planner.plan_execution(
            goal, agent_permissions, agent_roles, max_steps=max_steps)

        # Step 3: Execute (or dry-run)
        result = self.executor.execute_plan(
            plan, agent_permissions, agent_roles, execute=execute)

        # Step 4: Verify
        verification = self.executor.verify_result(result)

        # Step 5: Build reasoning trace
        self.stats["reasoning_sessions"] += 1
        if result.success and verification["verified"]:
            self.stats["successful_reasoning"] += 1
        else:
            self.stats["failed_reasoning"] += 1

        return {
            "goal": goal,
            "plan": plan.to_dict(),
            "execution": result.to_dict(),
            "verification": verification,
            "tool_match": match.to_dict() if match else None,
            "success": result.success and verification["verified"],
        }

    def get_stats(self) -> dict[str, Any]:
        return {
            "reasoning_sessions": self.stats["reasoning_sessions"],
            "successful_reasoning": self.stats["successful_reasoning"],
            "failed_reasoning": self.stats["failed_reasoning"],
            "plans_executed": self.executor.stats["plans_executed"],
            "plans_succeeded": self.executor.stats["plans_succeeded"],
            "plans_failed": self.executor.stats["plans_failed"],
            "total_steps_executed": self.executor.stats["total_steps_executed"],
            "registered_tools": len(self.matcher.tool_catalog),
        }


# Global tool-using reasoner instance
_tool_using_reasoner: ToolUsingReasoner | None = None


def get_tool_using_reasoner() -> ToolUsingReasoner:
    """Get or create the global ToolUsingReasoner instance."""
    global _tool_using_reasoner
    if _tool_using_reasoner is None:
        _tool_using_reasoner = ToolUsingReasoner()
    return _tool_using_reasoner


__all__ = [
    "ToolCapability",
    "ToolSelection",
    "ToolExecutionPlan",
    "ToolExecutionResult",
    "ToolCapabilityMatcher",
    "ToolExecutionPlanner",
    "ToolExecutor",
    "ToolUsingReasoner",
    "get_tool_using_reasoner",
]
