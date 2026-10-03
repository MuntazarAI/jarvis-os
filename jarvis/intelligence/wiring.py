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
        data = dict(event)
        if "payload" not in data:
            # Bare attribute dicts (e.g. supervisor event payloads)
            # nest under payload so downstream hooks find them.
            return {"payload": data}
        return data
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
                     tools: Any = None, device_service: Any = None):
    """Build the loop's policy gate.

    Required permissions and risk come from the tool spec, exactly like
    ``Jarvis._execute_step``. Without a registry the loop cannot know what
    an action requires, so it denies (fail closed) rather than guessing.

    Device actions (``device.*``) are pre-checked through the device
    service's router (peek only, nothing consumed). A denial stops the
    cycle; an approval-gated action passes to the executor, which routes
    it through the full durable service gate (grant + policy + approval
    consume at delivery). The loop can never execute a device action
    itself — only the service can.
    """
    def policy_check(action: str, args: Mapping[str, Any]) -> tuple[bool, str]:
        if str(action).startswith(("device.", "pi.")):
            return _device_policy_check(action, args)
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

    def _device_policy_check(action: str,
                             args: Mapping[str, Any]) -> tuple[bool, str]:
        if device_service is None:
            return False, "no device service bound (fail closed)"
        params = dict(args)
        device_id = str(params.pop("device_id", ""))
        if not device_id:
            return False, "device action requires device_id in args"
        try:
            gate = device_service.preview(actor, device_id, action, params)
        except Exception as exc:
            return False, f"device gate failed (fail closed): {exc}"[:200]
        if gate.get("authorized"):
            return True, "device authorized"
        reasons = "; ".join(gate.get("reasons", []))
        if gate.get("approval_token"):
            # Approval-gated: the executor routes through the durable
            # service gate, which mints the approval and parks the
            # command. The loop records waiting exactly once.
            return True, "device approval via service (awaiting human)"
        return False, reasons[:300] or "denied by device gate"
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


def make_predict_hook(board: Any = None):
    """Predict from evidence, or honestly report NO_PREDICTION.

    With a PredictionBoard bound, forecasts recent world-change trends
    (linear_trend needs >= 2 points, otherwise NO_PREDICTION).
    Confidence is capped at 0.5 and status stays unverified: a
    prediction is planning input, never authorization.
    """
    def predict(context: dict[str, Any]) -> dict[str, Any]:
        if board is None:
            return {"prediction": "NO_PREDICTION", "confidence": None,
                    "basis": [], "mode": "unavailable"}
        try:
            changes = board.latest_changes(3) if hasattr(
                board, "latest_changes") else []
        except Exception:
            return {"prediction": "NO_PREDICTION", "confidence": None,
                    "basis": [], "mode": "board failed"}
        points = [(float(c.get("at", 0.0)), float(c.get("delta", 0.0)))
                  for c in changes
                  if isinstance(c, dict)]
        try:
            from ..world.state import linear_trend
            trend = linear_trend([(x, y) for x, y in points])
        except Exception:
            trend = None
        if not trend:
            return {"prediction": "NO_PREDICTION", "confidence": None,
                    "basis": [str(c.get("summary", ""))[:120]
                              for c in changes[:3]],
                    "mode": "insufficient evidence"}
        rate = trend.get("rate_per_second", 0.0)
        direction = "rising" if rate > 0 else ("falling" if rate < 0
                                              else "steady")
        basis = [str(c.get("summary", ""))[:120] for c in changes[:3]]
        try:
            board.predict(f"trend {direction} "
                          f"({rate:+.4f}/s over {trend.get('points', 0)} "
                          "points)", basis or ["trend"], confidence=0.5)
        except Exception:
            pass
        return {"prediction": f"trend {direction}",
                "confidence": 0.5, "basis": basis,
                "mode": "linear-trend", "rate_per_second": rate}
    return predict


def make_verify_hook():
    """Pure result-vs-expectation check. No I/O, no side effects.

    Rules: no action -> skipped by the loop; no result -> UNKNOWN
    (never success-by-default); result ok + expectations met ->
    VERIFIED; ok but expectations unmet -> PARTIALLY_VERIFIED;
    not ok -> FAILED. Expectations come from the plan's
    verification_conditions (else any ok result verifies).
    """
    def verify(context: dict[str, Any]) -> dict[str, Any]:
        action = context.get("action") or {}
        result = context.get("result")
        name = str(action.get("action", ""))
        if result is None:
            return {"verdict": "UNKNOWN", "evidence": ["no result recorded"],
                    "expected": "", "observed": ""}
        if isinstance(result, dict) and result.get("waiting_approval"):
            return {"verdict": "UNKNOWN",
                    "evidence": ["waiting for human approval"],
                    "expected": "approval decision", "observed": "waiting"}
        ok = bool(result.get("ok", False)) if isinstance(result, dict) \
            else bool(result)
        observed = str(result.get("result", result.get("output", ""))
                       if isinstance(result, dict) else result)[:300]
        conditions = (context.get("action") or {}).get(
            "verification_conditions", {}) or {}
        if not ok:
            return {"verdict": "FAILED",
                    "evidence": [f"action {name} failed"],
                    "expected": str(conditions.get("expect", ""))[:200],
                    "observed": observed}
        expect = str(conditions.get("expect_result_contains", ""))[:200]
        if expect and expect not in observed:
            return {"verdict": "PARTIALLY_VERIFIED",
                    "evidence": [f"missing expected {expect!r}"],
                    "expected": expect, "observed": observed}
        return {"verdict": "VERIFIED",
                "evidence": [f"action {name} ok"],
                "expected": expect, "observed": observed}
    return verify


def make_device_executor(service: Any = None,
                         actor: str = "cognitive-loop"):
    """Route device.* loop actions through DeviceCommandService.

    The action's args MUST carry ``device_id`` (planner convention);
    anything else is refused fail-closed. Approval-gated commands
    return a waiting marker — the loop records it once and never
    busy-loops; the outbox drainer delivers after human approval.
    """
    def execute(action: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if service is None:
            return {"ok": False, "error": "no device service bound"}
        if not str(action).startswith(("device.", "pi.")):
            return {"ok": False,
                    "error": f"not a device action: {action}"[:160]}
        params = dict(args)
        device_id = str(params.pop("device_id", ""))
        if not device_id:
            return {"ok": False,
                    "error": "device action requires device_id in args"}
        try:
            out = service.request_command(actor, device_id, action, params)
        except Exception as exc:
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {exc}"[:300]}
        if out.get("requires_approval"):
            return {"ok": False, "waiting_approval": True,
                    "approval_id": str(out.get("approval_id", ""))[:64],
                    "command_id": str(out.get("command_id", ""))[:64],
                    "error": "waiting for human approval (no retry in cycle)"}
        return {"ok": bool(out.get("ok", False)),
                "output": str(out.get("result", out.get("error", "")))[:1000],
                "error": "" if out.get("ok") else str(
                    out.get("error", ""))[:300],
                "command_id": str(out.get("command_id", ""))[:64]}
    return execute


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
    reasoner, planner, policy, actor, tools, prediction_board,
    device_service.
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
    if components.get("device_service") is not None:
        executor_hook: Any = make_device_executor(
            components.get("device_service"),
            components.get("actor", "intelligence-loop"))
    else:
        executor_hook = make_executor_hook(components.get("tools"))
    loop = IntelligenceLoop(
        normalize=normalize_event,
        world_update=make_world_hook(components.get("registry"), components.get("spatial")),
        recall=make_recall_hook(components.get("palace")),
        neural_step=make_neural_hook(components.get("network"),
                                     components.get("encoder"), components.get("decoder")),
        reason=reason_hook,
        predict=make_predict_hook(components.get("prediction_board")),
        plan=planner.plan,
        policy_check=make_policy_hook(components.get("policy"),
                                      components.get("actor", "intelligence-loop"),
                                      components.get("tools"),
                                      components.get("device_service")),
        executor=executor_hook,
        verify=make_verify_hook(),
        learn=make_learn_hook(components.get("palace")),
        neural_checkpoint=checkpoint,
        neural_restore=restore,
    )
    return loop


def make_meta_reasoner_adapter(reasoner: Any = None):
    """Adapt MetaReasoner.audit() to the loop's reason hook signature."""
    from ..core.types import Confidence

    _NUMERIC = {"high": 0.8, "medium": 0.5, "low": 0.3, "unknown": 0.0}

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
        label = str(audit.get("confidence", "unknown"))
        return {"summary": text, "mode": "meta-audit",
                "confidence": _NUMERIC.get(label, 0.0),
                "confidence_label": label,
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


def build_supervisor(home: Any = None, actor: str = "cognitive-loop",
                     **components: Any) -> Any:
    """Assemble a CognitiveSupervisor: loop engine + persistent store.

    Same component keys as :func:`build_loop`, plus ``home`` (cycle
    store directory) and ``actor``. The supervisor conducts; every
    subsystem keeps working through the loop's hooks.
    """
    from .cognitive import CognitiveSupervisor
    loop = build_loop(actor=actor, **components)
    loop.start()
    return CognitiveSupervisor(loop, home=home, actor=actor)
