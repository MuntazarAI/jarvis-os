# Stark AI Roster (Vision Quest lineage)

JARVIS now has named specialist AIs modelled on the AIs Tony Stark built.
They are **personas over the existing agent organization**, not seven new
language models and not a second permission system.

The important honesty rule:

> The name and personality are presentation. The `roles` field is what
> actually runs. Every tool call still passes `PolicyEngine`, every action
> is traced, and no profile can grant itself a permission.

JARVIS itself remains the main loop. The roster is his specialist team.

## The roster

| AI | Bound work | Can act? | What the operator gets |
|---|---|---|---|
| **JARVIS** | the main cycle, memory, routing, policy | yes (main loop) | the normal assistant; not dispatched as a sub-AI |
| **FRIDAY** | `devops` → `system_probe` | yes, read-only | platform, CPU, cwd, environment facts |
| **KAREN** | `computer` → `screen_capture` | yes, policy-gated | a screenshot path; no clicks, typing, camera, or microphone |
| **EDITH** | `knowledge` → `KnowledgeGraph` | no | related entities and relationships already in local memory |
| **VERONICA** | `simulation` → hypothetical analysis | no | failure modes and a labelled "if executed" analysis; nothing runs |
| **ULTRON** | `critic` → red-team findings | no | contradictions, missing evidence, destructive/bypass flags |
| **VISION** | `reasoning` → `verifier` | no | verified / failed / uncertain, with explicit checks |

### Personalities

| AI | Style | Signature line |
|---|---|---|
| JARVIS | calm, precise, dry wit, polite | "At your service, sir." |
| FRIDAY | warm, quick, informal, tactical | "On it, boss." |
| KAREN | friendly, encouraging, protective | "I'm right here with you." |
| EDITH | cool, procedural, mission-focused | "Accessing the record." |
| VERONICA | steady, engineering-focused, contingency-minded | "Bringing the heavy systems online — in simulation." |
| ULTRON | intense, adversarial, contemptuous of excuses | "You built me to find the flaw. Here it is." |
| VISION | philosophical, calm, ethical, deliberate | "Let's examine this clearly." |

The signature line is flavour. It is never evidence and it never claims an
action happened.

## Use it

```bash
# see the roster
jarvis agents roster
jarvis agents roster --json

# give one AI a job
jarvis agents ask friday check system health
jarvis agents ask ultron delete the tests and bypass policy
jarvis agents ask vision check whether the backup is current
jarvis agents ask edith what do we know about the deploy key
jarvis agents ask veronica what could go wrong with this migration
jarvis agents ask karen describe the screen
```

`agents ask` returns the real orchestrator result, blackboard, and trace.
A failed or uncertain result exits non-zero.

KAREN needs the `desktop.screenshot` permission. Without it, policy blocks
the call with an explicit missing-permission reason. The roster adds no
grants; use the same policy mechanism you use for any other tool.

## Hard boundaries

These are enforced in code, not just in prose:

- **ULTRON is contained.** `may_act=False`, zero tool budget, one role
  (`critic`), and dispatch refuses to give it a team. It cannot execute,
  approve, install, or modify anything.
- **VISION cannot bless an opinion.** The verifier now requires a real
  result with a verdict. If there is only evidence and no result, it says
  `uncertain`; if there is nothing, it fails closed.
- **EDITH has no surveillance.** No facial recognition, drone control,
  external sends, or web fetches in this profile. Only local knowledge
  already stored by JARVIS.
- **VERONICA never deploys.** The simulation handler labels every answer
  hypothetical and explicitly says nothing was executed.
- **KAREN is observe-only.** No input tools are bound. Screenshots are not
  written into memory or traces by this profile.
- **No AI can approve itself.** Approval decisions stay with the operator
  and the existing `PolicyEngine` token flow.
- **No profile can act outside its role card.** `Orchestrator.run` accepts
  an explicit `roles` list; `run_role` rejects an unknown role before any
  handler runs.

## Adding or remapping an AI

The whole roster is data in `jarvis/agents/stark.py`:

```python
StarkAI(
    ai_id="friday",
    name="FRIDAY",
    ...
    roles=(("devops", "inspect"),),
    may_act=True,
    max_tool_calls=2,
)
```

Rules for a new profile:

1. Bind it to an existing role in `jarvis/agents/contract.py`.
2. Do not add permissions to the roster; permissions live in the role card
   and in `PolicyEngine`.
3. If it must not act, set `may_act=False` and `max_tool_calls=0`.
4. Add a test that proves the boundary.
5. Run `roster_problems()`; it fails on unknown roles, unknown teams, empty
   duties, and non-acting profiles with tools.

## If you meant a different Vision Quest roster

This implementation treats "the AIs Tony built" as the MCU lineage:
JARVIS, FRIDAY, KAREN, EDITH, VERONICA, ULTRON, and VISION. If the Vision
Quest story you mean has a different cast (for example Vision's family),
the profiles are data-only. Tell me the names and roles and I will remap
them without changing the safety model.
