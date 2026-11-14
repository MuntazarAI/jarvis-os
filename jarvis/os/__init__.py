"""
JARVIS-OS — Operating System Integration Layer

This package bridges JARVIS Intelligence (Python) with JARVIS-OS (Linux system services).
All system access goes through the PolicyEngine-gated Unix domain socket bridge.

Components:
- bridge: Client for JARVIS-OS Bridge (Rust daemon)
- policy: PolicyEngine integration for system operations
- desktop: Wayland desktop integration
- hardware: Hardware abstraction layer
- update: Atomic update/rollback system
"""

from .bridge import JarvisOSBridgeClient, SyncJarvisOSBridgeClient
from .policy import SystemPolicyEngine, PolicyGrant, PolicyAction

__all__ = [
    "JarvisOSBridgeClient",
    "SyncJarvisOSBridgeClient", 
    "SystemPolicyEngine",
    "PolicyGrant",
    "PolicyAction",
]

# Version
__version__ = "1.0.0"