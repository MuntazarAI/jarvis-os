# jarvis-sdk

Python SDK for JARVIS-OS — Local-First Personal AI OS.

## Installation

```bash
pip install jarvis-sdk
```

## Quick Start

```python
from jarvis_sdk import create_client

client = create_client(base_url="http://localhost:8765", token="my-token")

# Dispatch to a Stark AI agent
result = client.stark_ask("friday", "check system health")
print(result)

# Get system status
status = client.system_status()
print(status)

# Translate text
translation = client.translate("Hello world", "es")
print(translation)

# Get weather observation
weather = client.weather_observation("New York")
print(weather)
```

## API Reference

### JarvisClient

- `stark_list()` — List all Stark AI agents
- `stark_ask(ai_id, goal)` — Dispatch a goal to a Stark AI agent
- `stark_status()` — Get Stark AI system status
- `dots_list()` — List all DOT templates
- `dots_create(template_id, name)` — Create a DOT from a template
- `weather_observation(location)` — Get weather observation
- `geocode(address)` — Convert address to coordinates
- `translate(text, target_language, source_language)` — Translate text
- `parse_document(document_name, document_type, content)` — Parse document
- `system_status()` — Get overall system status
- `health()` — Get system health check

## License

Apache License 2.0