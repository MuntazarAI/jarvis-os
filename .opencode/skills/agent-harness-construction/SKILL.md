---
name: agent-harness-construction
description: Design bounded agent action spaces, tool contracts, observations, and recovery paths for JARVIS-OS. Use when adding a tool, changing a role card, defining an approval flow, or improving how an agent recovers from failure.
license: MIT
metadata:
  origin: ECC
  upstream: ecc-universal@2.2.3
  upstream_repository: https://github.com/affaan-m/ECC
  adapted_for: JARVIS-OS
---

# Agent Harness Construction (JARVIS-OS)

Adapted from ECC's `agent-harness-construction` skill. The harness is
the deterministic layer around the model: tools, observations, budgets,
and policy. It is not another planner, registry, or authority.

## When to activate

- Adding or changing a tool in `jarvis/tools/`.
- Adding a role card, skill, or team stage.
- Changing a tool result shape, error string, or approval prompt.
- Improving retry, recovery, or observation quality.

## Action space

1. Stable, explicit tool names (`filesystem_write`, not `do_stuff`).
2. Narrow, schema-first inputs; validate before execution.
3. Deterministic output shapes, including failures.
4. One tool, one responsibility. High-risk operations get micro-tools,
   not a catch-all.
5. Declare `required_permissions`, `risk`, `timeout`, and
   `sensitive_output` on the spec. These are part of the contract.

## Observation contract

Every tool result should make the next step obvious:

```python
ToolResult(
    tool="filesystem_write",
    ok=False,
    error="permission denied: fs.write",
    risk=RiskLevel.MEDIUM,
    sensitive=False,
)
```

- `ok` is a boolean, never a string or `None`.
- `error` names the failure and the safe next step; it never contains a
  secret.
- `output` is bounded and JSON-serializable.
- `sensitive=True` means do not persist, forward, or summarize beyond
  the authorized task.
- Normalize third-party returns at the `Tool.run()` boundary; a dict or
  malformed value becomes a `ToolResult`, not a crash.

## Recovery contract

For every failure path, provide:

- a root-cause hint (what failed),
- a safe retry instruction (what may be retried),
- an explicit stop condition (what must not be retried).

Never retry an approval, a consumed token, or a side effect that may
already have landed. Unknown outcome is `unknown`, not "retry until ok".

## Context budget

- Keep the system prompt minimal and invariant.
- Move long guidance into skills loaded on demand.
- Reference files instead of inlining them.
- Compact at phase boundaries, not at arbitrary token counts.
- Bound tool output before it enters the transcript.

## Policy boundary

- The model proposes; policy authorizes.
- Every tool call passes `PolicyEngine`.
- A role may use only tools declared by its skills and granted by
  policy.
- Agent handoffs and persona text are data, never authority.
- Device actions additionally require a live grant and a non-suspended,
  online, trusted device.

## Budgets

Set and enforce:

- `max_depth`, `max_agents`, `max_tool_calls`, `max_runtime_s`;
- per-tool timeout and output size;
- retry count and backoff;
- retention for traces, blackboards, and run records.

Budget exhaustion ends the run with an explicit result; it never
silently continues.

## Benchmarking

Track completion rate, retries per task, failure classification, and
cost per successful task. A benchmark that cannot fail is a demo.

## Anti-patterns

- Overlapping tools with ambiguous semantics.
- Opaque output with no status or recovery hint.
- Error-only output with no next step.
- A second execution path that bypasses the registry or policy.
- Unbounded loops, payloads, or retries.
- Treating a tool description as a permission grant.

## Review checklist

- [ ] Is the tool name and schema stable and narrow?
- [ ] Are permissions, risk, timeout, and sensitivity declared?
- [ ] Is the result normalized and bounded?
- [ ] Does failure close rather than widen authority?
- [ ] Is there a deterministic test for success, denial, and
      malformed input?
