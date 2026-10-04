# JARVIS-OS Security Review

Use JARVIS-OS self-review tooling from any coding agent. Two layers:
static tripwire (always available, no dependencies) and dynamic
proof-of-exploit (needs the Strix CLI + an LLM key, policy-gated).

## Static self-review (heuristic, offline)

```bash
python3 -m jarvis.cli --home <STATE> security review --target <DIR> --json
```

- Exit `0`: no high-severity heuristic hits. Exit `1`: high hits
  (probable hardcoded credential) — triage before merging.
  Exit `3`: review error.
- Caps: 200 files, 200KB each; binaries/hidden dirs skipped and counted.
- A clean result means "no heuristic hits", never "secure". Say that
  in your report; never upgrade it.

## Dynamic scan (Strix bridge, authorized targets ONLY)

```bash
python3 -m jarvis.cli --home <STATE> security scan \
  --target <PATH-OR-URL> --mode quick --yes --json
```

Rules (enforced by the tool, restated so you don't fight them):

1. `--yes` is REQUIRED and means: you own the target or hold explicit
   written permission to test it. Never pass `--yes` by default or to
   "see what happens". Ask the human first.
2. Non-local targets additionally require `--allow-nonlocal`.
3. Only `quick|standard|deep` modes; timeout 30–3600s (default 600).
4. Exit `0`: no findings reported. Exit `1`: findings/tool failure/
   timeout — read `log_tail`, triage, fix, re-scan. Exit `2`: refused
   (authorization/target/emergency-stop). Exit `3`: Strix not installed.
5. Record results as `partial` evidence, never `verified`. A tool claim
   is a lead; proof is a reproduced fix + green re-scan + tests.

## Machine-readable references

- `llms.txt` (repo root): CLI map, exit-code contract, agent rules.
- `AGENTS.md` (repo root): layout, house rules, workflow, probes.

## What NOT to do

- Do not scan third-party sites, clients, or "just curious" targets.
- Do not paste secrets into commands; use env or the vault.
- Do not present heuristic or tool output as a clean bill of health.
