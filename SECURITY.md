# Security Policy

## Reporting a vulnerability

Please do **not** publish exploitable security details in a public issue.

For a vulnerability involving JARVIS-OS, contact the repository owner privately through an appropriate GitHub contact method and include:

- affected component
- impact
- reproduction steps
- relevant logs or minimal proof of concept
- suggested mitigation, if known

Do not include passwords, API keys, session tokens, private keys, or other secrets.

## Security-sensitive areas

Particular care is required around:

- tool execution
- computer control
- browser automation
- prompt injection
- memory poisoning
- secret handling
- policy/permission checks
- network access
- file access
- agent delegation
- model/tool output treated as trusted input

## Security principles

JARVIS-OS is designed around:

- explicit policy gates
- approval boundaries
- least privilege
- provenance tracking
- input validation
- bounded automation
- failure isolation
- emergency stop controls

These are design goals and application-level safeguards, not a guarantee that the system is secure in every environment.

## Supported versions

The project is under active development and does not currently promise a long-term security-support window for older versions. When reporting an issue, identify the commit or release you tested.
