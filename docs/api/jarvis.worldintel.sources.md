# `jarvis.worldintel.sources`

## Members

### `EvidenceItem` (class)

EvidenceItem(evidence_id: 'str' = <factory>, source_id: 'str' = '', title: 'str' = '', url: 'str' = '', published_at: 'float' = 0.0, retrieved_at: 'float' = <factory>, text: 'str' = '', entities: 'list[str]' = <factory>, injection_flags: 'list[str]' = <factory>)

### `Source` (class)

Source(source_id: 'str' = '', name: 'str' = '', kind: 'str' = 'rss', endpoint: 'str' = '', freshness_domain: 'str' = 'general', rate_limit_s: 'float' = 60.0, privacy_class: 'str' = 'public', trust_note: 'str' = 'unknown', trust_basis: 'str' = 'unknown', enabled: 'bool' = True)

### `SourceRegistry` (class)

Known sources + last-fetch times for rate limiting.

### `bounded_get` (function)

SSRF-guarded, size-capped GET with NO redirect following

### `default_sources` (function)

_No docstring._

### `fetch_hn` (function)

Hacker News top stories via the keyless Firebase API.

### `parse_rss` (function)

RSS 2.0 + Atom via stdlib. Malformed XML yields nothing.
