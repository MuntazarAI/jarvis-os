"""Wiring: bind real JARVIS subsystems to the IntelligenceLoop.

Factories build loop hooks from live subsystem instances. Every hook
degrades safely (returns skipped/empty) when its subsystem is absent, and
the action path always goes through PolicyEngine first.
"""

from __future__ import annotations

from typing import Any, Mapping

from .loop import IntelligenceLoop
from .sensory import SensoryEvent


def normalize_event(event: Any) -> dict[str, Any]:
    if isinstance(event, SensoryEvent):
        return event.to_dict()
    if isinstance(event, dict):
        return dict(event)
    return {"raw": str(event)[:1000]}


def make_world_hook(registry: Any = None, spatial: Any = None):
    def world_update(normalized: dict[str, Any]) -> dict[str, Any]:
        if registry is None:
            return {}
        summary = normalized.get("payload", normalized)
        name = str(summary.get("name", summary.get("text", "observation")))[:160] or "observation"
        try:
            entity, _ = registry.upsert_entity(
                "event", name,
                state={"kind": str(summary.get("kind", normalized.get("type", "note")))[:80]},
                provenance={"observer": "intelligence-loop"},
                confidence=float(normalized.get("confidence", 0.5)),
            )
        except Exception:
            return {}
        result: dict[str, Any] = {"entity_id": entity.id}
        if spatial is not None:
            try:
                node = spatial.add_node("object", name, confidence=0.5,
                                        provenance={"observer": "intelligence-loop"})
                result["spatial_id"] = node.id
            except Exception:
                pass
        return result
    return world_update


def make_recall_hook(palace: Any = None):
    def recall(normalized: dict[str, Any]) -> list[dict[str, Any]]:
        if palace is None:
            return []
        payload = normalized.get("payload", {})
        query = str(payload.get("text", payload.get("name", "")))[:300]
        if not query:
            return []
        try:
            hits = palace.search(query, limit=5)
        except Exception:
            return []
        out = []
        for memory, score in hits:
            out.append({"id": getattr(memory, "id", ""), "score": round(float(score), 3),
                        "content": str(getattr(memory, "content", ""))[:300]})
        return out
    return recall


def make_neural_hook(network: Any = None, encoder: Any = None, decoder: Any = None):
    def neural_step(normalized: dict[str, Any]) -> dict[str, Any]:
        if network is None or encoder is None:
            return {}
        payload = normalized.get("payload", {})
        features = {k: v for k, v in payload.items() if isinstance(v, (int, float))}
        # fold a text signal into novelty-ish features deterministically
        text = str(payload.get("text", ""))
        if text:
            features["novelty"] = min(1.0, len(set(text.split())) / 50.0)
            features["urgency"] = 1.0 if any(
                w in text.lower() for w in ("urgent", "alert", "error", "critical")) else 0.0
        try:
            currents = encoder.encode(features)
            fired = network.step(currents)
        except Exception:
            return {}
        signals: dict[str, Any] = {"fired": len(fired), "tick": network.time}
        if decoder is not None:
            try:
                intents = decoder.decode(fired, tick=network.time)
                signals["motor_intents"] = [i.to_dict() for i in intents]
            except Exception:
                signals["motor_intents"] = []
        return signals
    return neural_step


def make_reason_hook(reasoner: Any = None):
    def reason(context: dict[str, Any]) -> dict[str, Any]:
        normalized = context.get("normalized", {})
        neural = context.get("neural", {})
        memories = context.get("memories", [])
        if reasoner is None:
            summary = str(normalized.get("payload", {}).get("text", ""))[:300]
            return {"summary": summary, "mode": "passthrough",
                    "memory_count": len(memories), "spikes": neural.get("fired", 0)}
        try:
            return reasoner(context)
        except Exception:
            return {"summary": "reasoner failed (isolated)", "mode": "fallback"}
    return reason


def make_policy_hook(policy: Any = None, actor: str = "intelligence-loop",
                     tools: Any = None):
    """Build the loop's policy gate.

    Required permissions and risk come from the tool spec, exactly like
    ``Jarvis._execute_step``. Without a registry the loop cannot know what
    an action requires, so it denies (fail closed) rather than guessing.
    """
    def policy_check(action: str, args: Mapping[str, Any]) -> tuple[bool, str]:
        if policy is None:
            return False, "no policy bound (fail closed)"
        if tools is None:
            return False, "no tool registry bound (cannot verify permissions)"
        try:
            tool = tools.get(action)
        except Exception as exc:
            return False, f"tool lookup failed (fail closed): {exc}"[:200]
        if tool is None:
            return False, f"unknown tool: {action}"
        try:
            from ..core.types import ActionPlan
            plan = ActionPlan(action=action, args=dict(args),
                              required_permissions=list(tool.spec.required_permissions),
                              risk=tool.spec.risk)
            decision = policy.evaluate(actor, plan)
        except Exception as exc:
            return False, f"policy error (fail closed): {exc}"[:200]
        reasons = "; ".join(getattr(decision, "reasons", []) or [])
        if not getattr(decision, "allow", False):
            return False, reasons[:300] or "denied"
        if getattr(decision, "requires_approval", False):
            try:
                token = policy.request_approval(actor, plan, decision)
                return False, f"needs approval ({token})"
            except Exception:
                return False, "approval required (request failed)"
        return True, reasons[:300] or "allowed"
    return policy_check


def make_executor_hook(tools: Any = None):
    def executor(action: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if tools is None:
            return {"ok": False, "error": "no tool registry bound"}
        try:
            result = tools.call(action, **dict(args))
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        return {"ok": bool(getattr(result, "ok", False)),
                "output": str(getattr(result, "output", ""))[:1000],
                "error": str(getattr(result, "error", ""))[:300]}
    return executor


def make_learn_hook(palace: Any = None):
    def learn(context: dict[str, Any]) -> dict[str, Any]:
        if palace is None:
            return {}
        normalized = context.get("normalized", {})
        result = context.get("result")
        if result is None:
            return {"stored": False, "reason": "no action result"}
        text = (f"cycle {context.get('cycle_id')}: action "
                f"'{context.get('action', {}).get('action', '')}' -> "
                f"{'ok' if result.get('ok') else 'failed'}")
        try:
            memory = palace.store_observation(text[:500], source="intelligence-loop",
                                              confidence=0.6)
            return {"stored": True, "memory_id": getattr(memory, "id", "")}
        except Exception:
            return {"stored": False}
    return learn


def build_loop(**components: Any) -> IntelligenceLoop:
    """Assemble an IntelligenceLoop from subsystem instances.

    Accepted keys: registry, spatial, palace, network, encoder, decoder,
    reasoner, planner, policy, actor, tools.
    """
    from ..planning.planner import MissionPlanner
    planner = components.get("planner") or MissionPlanner()
    network = components.get("network")
    reasoner = components.get("reasoner")
    if reasoner is not None and hasattr(reasoner, "audit") and not callable(reasoner):
        reason_hook = make_meta_reasoner_adapter(reasoner)
    else:
        reason_hook = make_reason_hook(reasoner)
    checkpoint = restore = None
    if network is not None and hasattr(network, "snapshot") and hasattr(network, "restore"):
        checkpoint = lambda: network.snapshot(include_weights=True)  # noqa: E731
        restore = network.restore
    loop = IntelligenceLoop(
        normalize=normalize_event,
        world_update=make_world_hook(components.get("registry"), components.get("spatial")),
        recall=make_recall_hook(components.get("palace")),
        neural_step=make_neural_hook(components.get("network"),
                                     components.get("encoder"), components.get("decoder")),
        reason=reason_hook,
        plan=planner.plan,
        policy_check=make_policy_hook(components.get("policy"),
                                      components.get("actor", "intelligence-loop"),
                                      components.get("tools")),
        executor=make_executor_hook(components.get("tools")),
        learn=make_learn_hook(components.get("palace")),
        neural_checkpoint=checkpoint,
        neural_restore=restore,
    )
    return loop


def make_meta_reasoner_adapter(reasoner: Any = None):
    """Adapt MetaReasoner.audit() to the loop's reason hook signature."""
    from ..core.types import Confidence

    def reason(context: dict[str, Any]) -> dict[str, Any]:
        normalized = context.get("normalized", {}) or {}
        payload = normalized.get("payload", {}) or {}
        neural = context.get("neural", {}) or {}
        memories = context.get("memories", []) or []
        text = str(payload.get("text", payload.get("name", "")))[:500]
        if reasoner is None:
            return {"summary": text, "mode": "passthrough",
                    "memory_count": len(memories),
                    "spikes": neural.get("fired", 0)}
        confidence = Confidence.MEDIUM
        if neural.get("fired", 0) > 5:
            confidence = Confidence.HIGH
        assumptions = [f"memory:{m.get('id', '')}" for m in memories[:3]]
        try:
            audit = reasoner.audit(text or "no input text", confidence, assumptions)
        except Exception:
            return {"summary": text, "mode": "fallback"}
        return {"summary": text, "mode": "meta-audit",
                "confidence": audit.get("confidence"),
                "biases": audit.get("detected_biases", []),
                "decision": text,
                "memory_count": len(memories),
                "spikes": neural.get("fired", 0)}
    return reason


def default_neural_stack(seed: int = 41, size: int = 64, edges: int = 400):
    """Build the default small neural stack: network + encoder + decoder.

    A small synthetic net is the production default because the full
    166k fly schema costs seconds to generate per process; callers that
    want the full substrate pass an explicit network instead.
    """
    import random
    from ..neural.scale import SparseLIFNetwork
    from ..neural.codec import ChannelMap, MotorDecoder, SensoryEncoder, default_sensor_features

    rng = random.Random(seed)
    network = SparseLIFNetwork(size)
    for _ in range(edges):
        network.stage_edge(rng.randrange(size), rng.randrange(size),
                           rng.uniform(0.1, 0.9), rng.randrange(3))
    network.compile()
    encoder = SensoryEncoder(ChannelMap(default_sensor_features()))
    decoder = MotorDecoder({0: ("ATTEND", 0.7), 1: ("FOCUS", 0.6)})
    return network, encoder, decoder
