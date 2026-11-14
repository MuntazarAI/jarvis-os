# Models — using any model, anywhere

JARVIS talks to models through **backends**. A backend is a named
provider it can ask for text: the local Ollama daemon, NVIDIA NIM, an
OpenAI-compatible server (LM Studio, vLLM, llama.cpp, Groq,
OpenRouter, Together, OpenAI), or anything else that speaks one of the
supported protocols.

Backends and the model they serve are **config**, not code. Switching
models never needs a code change.

## The two pieces

- **backend** — where a model lives (`ollama`, `nvidia`, `lmstudio`, …)
- **kind** — what the model is for: `fast`, `reasoning`, `coding`,
  `vision`, `embedding`

`selection` says which backend answers which kind. That is the whole
switchboard.

## Quick start

```bash
# what is configured, what is reachable, what is selected
jarvis models list

# add a provider
jarvis models add nvidia --type openai \
  --base-url https://integrate.api.nvidia.com/v1 \
  --model fast=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning \
  --model reasoning=nvidia/nemotron-3-ultra-550b-a55b \
  --model coding=nvidia/nemotron-3-ultra-550b-a55b \
  --model vision=nvidia/nemotron-3.5-super-vl-120b-a12b \
  --model embedding=nvidia/nemotron-3-embed-1b \
  --api-key-secret nvidia_api_key --remote --timeout 30

# store the key in the encrypted vault (never in argv, never in config)
cat key.txt | jarvis models key nvidia

# point a kind at a backend
jarvis models use reasoning nvidia --allow-remote

# probe a backend with a real prompt
jarvis models test nvidia --probe
```

`--allow-remote` turns `policy.local_only` off. While it is on, remote
backends are configured but **never used** — the privacy wall holds.

## Keys

Keys never live in `config.json`. A backend names where the key is:

| field | meaning |
|---|---|
| `api_key_secret` | a vault secret name (read from `~/.jarvis-os/secrets.json`) |
| `api_key_env` | an environment variable name |

The vault wins over the environment. The value is fetched at call time
and never reaches config, logs, health output or snapshots.

## Config shape

`~/.jarvis-os/config.json`:

```json
{
  "policy": { "local_only": false },
  "models": {
    "backends": [
      {
        "name": "ollama",
        "type": "ollama",
        "base_url": "http://localhost:11434",
        "local": true,
        "models": { "fast": "qwen2.5:3b", "vision": "qwen3-vl:2b" }
      },
      {
        "name": "nvidia",
        "type": "openai",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "local": false,
        "api_key_secret": "nvidia_api_key",
        "timeout": 30,
        "models": { "reasoning": "nvidia/nemotron-3-ultra-550b-a55b" }
      }
    ],
    "selection": {
      "fast": "ollama",
      "reasoning": "nvidia"
    }
  }
}
```

A selection value is `backend` or `backend:model`. With just the
backend name, the backend's own model for that kind is used. With an
explicit model id, that exact model is used — so one backend can serve
several models across kinds.

## Behaviour

- **Selection wins.** The selected backend is always tried first.
- **Fallback.** If it fails, the next healthy backend answers. A
  backend is retried even if the boot-time probe marked it unhealthy:
  the call itself is the real test.
- **Local-only wall.** With `policy.local_only` on, remote backends are
  removed from the chain entirely, not merely deprioritised.
- **Degrade, never crash.** A failing backend returns an error dict and
  the router moves on.
- **Bounded.** Every backend has a timeout; responses are size-capped.

## Checking it

```bash
jarvis doctor          # backend:<name> and model:<backend>/<kind> lines
jarvis models test     # reachability per backend
jarvis talk "hello"    # real round trip
```

`doctor` reports each backend's reachability and whether the model it
claims is really served by that backend.

## Notes

- The catalog a provider advertises may be larger than what your
  account can actually call — some ids 404, some hang. `jarvis models
  test --probe` is the honest check, not the catalog.
- The local Ollama fallback on a small CPU can take minutes. Remote
  models are usually far quicker; set a backend `--timeout` so a hung
  provider cannot stall the loop.
- Memory search keeps using the local deterministic embedder
  (`jarvis/memory/palace.py`); the `embedding` kind is for callers that
  want a real embedding model.
