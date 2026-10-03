# `jarvis.core.config`

## Members

### `CognitiveConfig` (class)

Controls the Master Cognitive Loop.

### `DeviceFabricConfig` (class)

DeviceFabricConfig(enabled: 'bool' = True, state_path: 'str' = 'device-fabric.json', heartbeat_timeout_s: 'float' = 120.0, max_devices: 'int' = 64)

### `DeviceTransportConfig` (class)

Real network transport for the device fabric (3.10).

### `JarvisConfig` (class)

JarvisConfig(paths: 'PathsConfig' = <factory>, cognitive: 'CognitiveConfig' = <factory>, memory: 'MemoryConfig' = <factory>, policy: 'PolicyConfig' = <factory>, models: 'ModelConfig' = <factory>, server: 'ServerConfig' = <factory>, device_fabric: 'DeviceFabricConfig' = <factory>, device_transport: 'DeviceTransportConfig' = <factory>, voice: 'VoiceConfig' = <factory>, world: 'WorldConfig' = <factory>, personality: 'dict[str, Any]' = <factory>, version: 'int' = 1)

### `MemoryConfig` (class)

MemoryConfig(working_capacity: 'int' = 40, short_term_hours: 'int' = 24, decay_half_life_days: 'float' = 30.0, archive_after_days: 'float' = 90.0, expire_after_days: 'float' = 365.0, consolidate_every_cycles: 'int' = 50, dedup_similarity: 'float' = 0.82, rooms: 'list[str]' = <factory>)

### `ModelConfig` (class)

ModelConfig(planner_model: 'str' = 'local-planner', reasoning_model: 'str' = 'local-reasoning', fast_model: 'str' = 'local-fast', vision_model: 'str' = 'local-vision', embedding_dim: 'int' = 64, cloud_enabled: 'bool' = False, fallback_enabled: 'bool' = True, ollama_enabled: 'bool' = True, ollama_host: 'str' = 'http://localhost:11434', llm_timeout: 'float' = 120.0, llm_max_tokens: 'int' = 512)

### `PathsConfig` (class)

PathsConfig(home: 'Path' = PosixPath('~/.jarvis-os'), db: 'str' = 'jarvis.db', events: 'str' = 'events.db', logs: 'str' = 'logs', screenshots: 'str' = 'screenshots', captures: 'str' = 'captures', exports: 'str' = 'exports')

### `PolicyConfig` (class)

PolicyConfig(require_approval_above_risk: 'float' = 0.5, block_high_risk_paths: 'list[str]' = <factory>, local_only: 'bool' = True, record_audit: 'bool' = True, emergency_stop_file: 'str' = 'EMERGENCY_STOP', proactivity: 'str' = 'assisted', quiet_hours: 'list[int]' = <factory>)

### `ServerConfig` (class)

ServerConfig(host: 'str' = '127.0.0.1', port: 'int' = 8765)

### `VoiceConfig` (class)

Local-first voice I/O (5.1). STT and TTS are independent.

### `WorldConfig` (class)

World Intelligence 1.0: evidence-driven live knowledge.
