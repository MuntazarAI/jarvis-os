"""
JARVIS-OS Policy Integration

Integrates JARVIS PolicyEngine with system-level operations.
Provides policy-gated access to JARVIS-OS Bridge functionality.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Callable, Awaitable
from pathlib import Path
import json

logger = logging.getLogger(__name__)


class PolicyAction(Enum):
    """Policy actions for system operations."""
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_AUTH = "require_auth"


class SystemResource(Enum):
    """System resources that can be policy-controlled."""
    # Information (read-only)
    SYSTEM_INFO = "system.info"
    CPU_INFO = "cpu.info"
    CPU_USAGE = "cpu.usage"
    CPU_TEMPERATURE = "cpu.temperature"
    MEMORY_INFO = "memory.info"
    MEMORY_USAGE = "memory.usage"
    STORAGE_INFO = "storage.info"
    STORAGE_USAGE = "storage.usage"
    NETWORK_INTERFACES = "network.interfaces"
    NETWORK_STATS = "network.stats"
    PROCESS_LIST = "process.list"
    PROCESS_INFO = "process.info"
    SERVICE_LIST = "service.list"
    SERVICE_INFO = "service.info"
    HARDWARE_INFO = "hardware.computer"
    LOGS_JOURNALD = "logs.journald"
    LOGS_KERNEL = "logs.kernel"
    
    # State-changing (require approval)
    SERVICE_START = "service.start"
    SERVICE_STOP = "service.stop"
    SERVICE_RESTART = "service.restart"
    SERVICE_ENABLE = "service.enable"
    SERVICE_DISABLE = "service.disable"
    PROCESS_KILL = "process.kill"
    PROCESS_SIGNAL = "process.signal"
    POLICY_GRANT = "policy.grant"
    POLICY_REVOKE = "policy.revoke"
    BRIDGE_SHUTDOWN = "bridge.shutdown"


@dataclass
class PolicyGrant:
    """A policy grant for a subject to access a resource."""
    id: str
    subject: str                    # Agent/tool identifier
    resource: SystemResource        # Resource being accessed
    action: PolicyAction            # What action is allowed
    conditions: List[str] = field(default_factory=list)  # Additional conditions
    granted_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    granted_by: str = "policy_engine"
    metadata: Dict = field(default_factory=dict)
    
    def is_valid(self, now: Optional[datetime] = None) -> bool:
        """Check if grant is currently valid."""
        now = now or datetime.utcnow()
        if self.expires_at and now > self.expires_at:
            return False
        return True
    
    def matches(self, subject: str, resource: SystemResource) -> bool:
        """Check if grant matches subject and resource."""
        return self.subject == subject and self.resource == resource and self.is_valid()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "subject": self.subject,
            "resource": self.resource.value,
            "action": self.action.value,
            "conditions": self.conditions,
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "granted_by": self.granted_by,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "PolicyGrant":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            subject=data["subject"],
            resource=SystemResource(data["resource"]),
            action=PolicyAction(data["action"]),
            conditions=data.get("conditions", []),
            granted_at=datetime.fromisoformat(data["granted_at"]),
            expires_at=datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None,
            granted_by=data.get("granted_by", "policy_engine"),
            metadata=data.get("metadata", {}),
        )


class PolicyRule:
    """A policy rule for automatic grant evaluation."""
    
    def __init__(
        self,
        name: str,
        subject_pattern: str,
        resource_pattern: str,
        action: PolicyAction,
        condition_fn: Optional[Callable[[Dict], Awaitable[bool]]] = None,
        priority: int = 0,
    ):
        self.name = name
        self.subject_pattern = subject_pattern
        self.resource_pattern = resource_pattern
        self.action = action
        self.condition_fn = condition_fn
        self.priority = priority
    
    def matches(self, subject: str, resource: SystemResource) -> bool:
        """Check if rule matches subject and resource."""
        import fnmatch
        return (
            fnmatch.fnmatch(subject, self.subject_pattern) and
            fnmatch.fnmatch(resource.value, self.resource_pattern)
        )
    
    async def evaluate(self, context: Dict) -> Optional[PolicyAction]:
        """Evaluate rule with context."""
        if self.condition_fn:
            try:
                result = await self.condition_fn(context)
                if result:
                    return self.action
            except Exception as e:
                logger.error(f"Policy rule {self.name} condition error: {e}")
                return None
        return self.action


class SystemPolicyEngine:
    """
    Policy Engine for JARVIS-OS system operations.
    
    Integrates with JARVIS core PolicyEngine and provides:
    - Resource-based access control
    - Automatic grant management
    - Policy rules for dynamic evaluation
    - Audit logging
    - Persistence
    """
    
    def __init__(
        self,
        grants_file: str = "/etc/jarvis-os/policy-grants.json",
        audit_log: str = "/var/log/jarvis-os/policy-audit.log",
        jarvis_policy_engine=None,
    ):
        self.grants_file = Path(grants_file)
        self.audit_log = Path(audit_log)
        self.jarvis_policy_engine = jarvis_policy_engine
        
        self._grants: Dict[str, PolicyGrant] = {}
        self._rules: List[PolicyRule] = []
        self._subject_index: Dict[str, Set[str]] = {}  # subject -> grant_ids
        self._resource_index: Dict[str, Set[str]] = {}  # resource -> grant_ids
        
        self._load_grants()
        self._setup_default_rules()
    
    def _load_grants(self) -> None:
        """Load grants from file."""
        if self.grants_file.exists():
            try:
                with open(self.grants_file) as f:
                    data = json.load(f)
                    for grant_data in data.values():
                        grant = PolicyGrant.from_dict(grant_data)
                        self._add_grant_index(grant)
                        self._grants[grant.id] = grant
                logger.info(f"Loaded {len(self._grants)} policy grants")
            except Exception as e:
                logger.error(f"Failed to load grants: {e}")
    
    def _save_grants(self) -> None:
        """Save grants to file."""
        try:
            self.grants_file.parent.mkdir(parents=True, exist_ok=True)
            data = {gid: grant.to_dict() for gid, grant in self._grants.items()}
            with open(self.grants_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save grants: {e}")
    
    def _add_grant_index(self, grant: PolicyGrant) -> None:
        """Add grant to indexes."""
        self._subject_index.setdefault(grant.subject, set()).add(grant.id)
        self._resource_index.setdefault(grant.resource.value, set()).add(grant.id)
    
    def _remove_grant_index(self, grant: PolicyGrant) -> None:
        """Remove grant from indexes."""
        self._subject_index.get(grant.subject, set()).discard(grant.id)
        self._resource_index.get(grant.resource.value, set()).discard(grant.id)
    
    def _setup_default_rules(self) -> None:
        """Setup default policy rules."""
        # JARVIS core gets read access to system info
        self.add_rule(PolicyRule(
            name="jarvis-core-read",
            subject_pattern="jarvis-*",
            resource_pattern="*.info",
            action=PolicyAction.ALLOW,
            priority=10,
        ))
        
        self.add_rule(PolicyRule(
            name="jarvis-core-usage",
            subject_pattern="jarvis-*",
            resource_pattern="*.usage",
            action=PolicyAction.ALLOW,
            priority=10,
        ))
        
        self.add_rule(PolicyRule(
            name="jarvis-core-logs",
            subject_pattern="jarvis-*",
            resource_pattern="logs.*",
            action=PolicyAction.ALLOW,
            priority=10,
        ))
        
        # State-changing operations require approval
        self.add_rule(PolicyRule(
            name="state-change-approval",
            subject_pattern="*",
            resource_pattern="service.*",
            action=PolicyAction.REQUIRE_APPROVAL,
            priority=5,
        ))
        
        self.add_rule(PolicyRule(
            name="process-control-approval",
            subject_pattern="*",
            resource_pattern="process.kill",
            action=PolicyAction.REQUIRE_APPROVAL,
            priority=5,
        ))
        
        self.add_rule(PolicyRule(
            name="policy-admin-approval",
            subject_pattern="*",
            resource_pattern="policy.*",
            action=PolicyAction.REQUIRE_APPROVAL,
            priority=5,
        ))
    
    def add_rule(self, rule: PolicyRule) -> None:
        """Add a policy rule."""
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)  # Higher priority first
    
    def remove_rule(self, name: str) -> bool:
        """Remove a policy rule by name."""
        for i, rule in enumerate(self._rules):
            if rule.name == name:
                self._rules.pop(i)
                return True
        return False
    
    async def evaluate(
        self,
        subject: str,
        resource: SystemResource,
        context: Optional[Dict] = None,
    ) -> PolicyAction:
        """
        Evaluate policy for a subject accessing a resource.
        
        Returns the action to take (ALLOW, DENY, REQUIRE_APPROVAL, REQUIRE_AUTH).
        """
        context = context or {}
        context.update({
            "subject": subject,
            "resource": resource.value,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # Check explicit grants first
        now = datetime.utcnow()
        for grant_id in self._subject_index.get(subject, set()):
            grant = self._grants.get(grant_id)
            if grant and grant.matches(subject, resource) and grant.is_valid(now):
                self._audit("GRANT_MATCH", subject, resource, grant.action)
                return grant.action
        
        # Evaluate rules
        for rule in self._rules:
            if rule.matches(subject, resource):
                action = await rule.evaluate(context)
                if action:
                    self._audit("RULE_MATCH", subject, resource, action, rule_name=rule.name)
                    return action
        
        # Check JARVIS core PolicyEngine if available
        if self.jarvis_policy_engine:
            try:
                # This would call the JARVIS PolicyEngine
                # result = await self.jarvis_policy_engine.evaluate(...)
                pass
            except Exception as e:
                logger.error(f"JARVIS PolicyEngine error: {e}")
        
        # Default deny
        self._audit("DEFAULT_DENY", subject, resource, PolicyAction.DENY)
        return PolicyAction.DENY
    
    def _audit(
        self,
        event: str,
        subject: str,
        resource: SystemResource,
        action: PolicyAction,
        rule_name: str = None,
    ) -> None:
        """Log policy decision for audit."""
        try:
            self.audit_log.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "event": event,
                "subject": subject,
                "resource": resource.value,
                "action": action.value,
                "rule": rule_name,
            }
            with open(self.audit_log, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Don't let audit failures affect policy decisions
    
    # Grant management
    
    def grant(
        self,
        subject: str,
        resource: SystemResource,
        action: PolicyAction = PolicyAction.ALLOW,
        conditions: List[str] = None,
        expires_at: Optional[datetime] = None,
        granted_by: str = "policy_engine",
        metadata: Dict = None,
    ) -> PolicyGrant:
        """Create a new policy grant."""
        import uuid
        grant = PolicyGrant(
            id=str(uuid.uuid4())[:8],
            subject=subject,
            resource=resource,
            action=action,
            conditions=conditions or [],
            expires_at=expires_at,
            granted_by=granted_by,
            metadata=metadata or {},
        )
        
        self._grants[grant.id] = grant
        self._add_grant_index(grant)
        self._save_grants()
        
        self._audit("GRANT_CREATED", subject, resource, action)
        logger.info(f"Created grant {grant.id}: {subject} -> {resource.value} = {action.value}")
        
        return grant
    
    def revoke(self, grant_id: str) -> bool:
        """Revoke a policy grant."""
        grant = self._grants.pop(grant_id, None)
        if grant:
            self._remove_grant_index(grant)
            self._save_grants()
            self._audit("GRANT_REVOKED", grant.subject, grant.resource, grant.action)
            logger.info(f"Revoked grant {grant_id}")
            return True
        return False
    
    def revoke_subject(self, subject: str) -> int:
        """Revoke all grants for a subject."""
        count = 0
        grant_ids = list(self._subject_index.get(subject, set()))
        for grant_id in grant_ids:
            if self.revoke(grant_id):
                count += 1
        return count
    
    def list_grants(
        self,
        subject: Optional[str] = None,
        resource: Optional[SystemResource] = None,
        valid_only: bool = True,
    ) -> List[PolicyGrant]:
        """List policy grants with optional filters."""
        grants = list(self._grants.values())
        
        if subject:
            grants = [g for g in grants if g.subject == subject]
        if resource:
            grants = [g for g in grants if g.resource == resource]
        if valid_only:
            now = datetime.utcnow()
            grants = [g for g in grants if g.is_valid(now)]
        
        return grants
    
    def get_grant(self, grant_id: str) -> Optional[PolicyGrant]:
        """Get a specific grant by ID."""
        return self._grants.get(grant_id)
    
    # Convenience methods for common resources
    
    async def can_read_system_info(self, subject: str) -> bool:
        """Check if subject can read system info."""
        action = await self.evaluate(subject, SystemResource.SYSTEM_INFO)
        return action == PolicyAction.ALLOW
    
    async def can_control_service(self, subject: str, action: str) -> bool:
        """Check if subject can control services."""
        resource_map = {
            "start": SystemResource.SERVICE_START,
            "stop": SystemResource.SERVICE_STOP,
            "restart": SystemResource.SERVICE_RESTART,
            "enable": SystemResource.SERVICE_ENABLE,
            "disable": SystemResource.SERVICE_DISABLE,
        }
        resource = resource_map.get(action)
        if not resource:
            return False
        result = await self.evaluate(subject, resource)
        return result == PolicyAction.ALLOW
    
    async def can_kill_process(self, subject: str) -> bool:
        """Check if subject can kill processes."""
        action = await self.evaluate(subject, SystemResource.PROCESS_KILL)
        return action == PolicyAction.ALLOW


# Global policy engine instance
_policy_engine: Optional[SystemPolicyEngine] = None


def get_policy_engine() -> SystemPolicyEngine:
    """Get or create the global policy engine."""
    global _policy_engine
    if _policy_engine is None:
        _policy_engine = SystemPolicyEngine()
    return _policy_engine


def set_policy_engine(engine: SystemPolicyEngine) -> None:
    """Set the global policy engine."""
    global _policy_engine
    _policy_engine = engine