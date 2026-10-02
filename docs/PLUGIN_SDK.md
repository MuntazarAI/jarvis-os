# JARVIS-OS Plugin SDK

JARVIS plugins are bounded extensions around the core platform. A plugin should expose explicit metadata and typed operations rather than arbitrary execution hooks.

## Design goals

- Small, explicit interface.
- No implicit shell or filesystem authority.
- Testable without a running JARVIS installation.
- Compatible with the PolicyEngine and existing tool boundaries.

## Minimal plugin contract

A plugin provides a stable name, version, description, explicit capabilities, a health method, and a handle method for plugin-defined typed requests.

See examples/plugins/hello_plugin.py.
