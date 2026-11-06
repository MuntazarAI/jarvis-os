"""
JARVIS-OS Bridge Client

High-level Python client for the JARVIS-OS Bridge Unix domain socket.
Integrates with existing JARVIS PolicyEngine for gated system access.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from jarvis.neural.torch_integration import HybridSNNPolicyNetwork, TorchSNNConfig

logger = logging.getLogger(__name__)


@dataclass
class BridgeConfig:
    """Configuration for JARVIS-OS Bridge client."""
    socket_path: str = "/run/jarvis-os/bridge.sock"
    timeout: float = 10.0
    max_retries: int = 3
    retry_delay: float = 0.5
    policy_engine_socket: Optional[str] = "/run/jarvis/policy.sock"


@dataclass
class SystemInfo:
    """System information snapshot."""
    hostname: str
    kernel_version: str
    os_release: str
    architecture: str
    uptime_seconds: float
    cpu_cores: int
    cpu_model: str
    memory_total_gb: float
    memory_available_gb: float
    storage_total_gb: float
    storage_used_gb: float


class BridgeConnectionError(Exception):
    """Raised when bridge connection fails."""
    pass


class BridgePolicyError(Exception):
    """Raised when PolicyEngine denies an operation."""
    pass


class BridgeResponseError(Exception):
    """Raised when bridge returns an error response."""
    def __init__(self, message: str, code: int = -32603):
        super().__init__(message)
        self.code = code


class JarvisOSBridgeClient:
    """
    Async client for JARVIS-OS Bridge.
    
    All methods are PolicyEngine-gated on the bridge side.
    This client handles connection management, retries, and error handling.
    """
    
    def __init__(self, config: Optional[BridgeConfig] = None):
        self.config = config or BridgeConfig()
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._pending: Dict[str, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._policy_engine = None
    
    def set_policy_engine(self, policy_engine) -> None:
        """Set PolicyEngine reference for local gating."""
        self._policy_engine = policy_engine
    
    async def connect(self) -> None:
        """Connect to the bridge socket."""
        if self._connected:
            return
        
        socket_path = self.config.socket_path
        
        # Check if socket exists
        if not Path(socket_path).exists():
            raise BridgeConnectionError(
                f"Bridge socket not found at {socket_path}. "
                "Is the jarvis-os-bridge service running?"
            )
        
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(socket_path),
                timeout=self.config.timeout
            )
            self._connected = True
            self._read_task = asyncio.create_task(self._read_loop())
            logger.info(f"Connected to JARVIS-OS Bridge at {socket_path}")
            
        except asyncio.TimeoutError:
            raise BridgeConnectionError(f"Connection timeout to {socket_path}")
        except PermissionError:
            raise BridgeConnectionError(
                f"Permission denied connecting to {socket_path}. "
                "Ensure user is in jarvis-os group."
            )
        except Exception as e:
            raise BridgeConnectionError(f"Failed to connect: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect from the bridge."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        
        self._connected = False
        self._reader = None
        self._writer = None
        logger.info("Disconnected from JARVIS-OS Bridge")
    
    async def __aenter__(self) -> "JarvisOSBridgeClient":
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()
    
    async def _read_loop(self) -> None:
        """Background task to read responses."""
        try:
            while self._connected and self._reader:
                line = await self._reader.readline()
                if not line:
                    break
                
                line = line.decode().strip()
                if not line:
                    continue
                
                try:
                    response = json.loads(line)
                    request_id = response.get("id")
                    
                    if request_id and request_id in self._pending:
                        future = self._pending.pop(request_id)
                        if not future.done():
                            future.set_result(response)
                            
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse response: {line}")
                except Exception as e:
                    logger.error(f"Error processing response: {e}")
                    
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Read loop error: {e}")
        finally:
            # Cancel pending requests
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(BridgeConnectionError("Connection closed"))
            self._pending.clear()
            self._connected = False
    
    async def _call(self, method: str, params: Dict = None) -> Dict:
        """Make a JSON-RPC call to the bridge."""
        if not self._connected:
            await self.connect()
        
        if params is None:
            params = {}
        
        request_id = str(uuid.uuid4())
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": request_id,
        }
        
        future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        
        # Send with retries
        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                self._writer.write((json.dumps(request) + "\n").encode())
                await self._writer.drain()
                
                # Wait for response
                response = await asyncio.wait_for(future, timeout=self.config.timeout)
                
                # Check for JSON-RPC error
                if "error" in response and response["error"]:
                    error = response["error"]
                    raise BridgeResponseError(
                        error.get("message", "Unknown error"),
                        error.get("code", -32603)
                    )
                
                return response.get("result", {})
                
            except asyncio.TimeoutError:
                last_error = BridgeConnectionError(f"Request timeout for {method}")
            except BrokenPipeError:
                last_error = BridgeConnectionError("Connection lost")
                self._connected = False
                break
            except BridgeResponseError:
                raise
            except Exception as e:
                last_error = e
            
            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))
                # Try to reconnect
                try:
                    await self.connect()
                except Exception:
                    pass
        
        self._pending.pop(request_id, None)
        raise last_error or BridgeConnectionError("Max retries exceeded")
    
    # =========================================================================
    # System Information
    # =========================================================================
    
    async def get_system_info(self) -> SystemInfo:
        """Get comprehensive system information."""
        # Gather all info in parallel
        results = await asyncio.gather(
            self._call("system.info", {}),
            self._call("system.uptime", {}),
            self._call("cpu.info", {}),
            self._call("memory.info", {}),
            self._call("storage.usage", {}),
            return_exceptions=True
        )
        
        sys_info = results[0] if not isinstance(results[0], Exception) else {}
        uptime = results[1] if not isinstance(results[1], Exception) else {}
        cpu_info = results[2] if not isinstance(results[2], Exception) else {}
        mem_info = results[3] if not isinstance(results[3], Exception) else {}
        storage = results[4] if not isinstance(results[4], Exception) else {}
        
        return SystemInfo(
            hostname=sys_info.get("data", {}).get("hostname", "unknown"),
            kernel_version=sys_info.get("data", {}).get("kernel", "unknown"),
            os_release=sys_info.get("data", {}).get("os_release", "unknown"),
            architecture=sys_info.get("data", {}).get("architecture", "unknown"),
            uptime_seconds=uptime.get("data", {}).get("uptime_seconds", 0),
            cpu_cores=cpu_info.get("data", {}).get("cores", 0),
            cpu_model=cpu_info.get("data", {}).get("model_name", "unknown"),
            memory_total_gb=mem_info.get("data", {}).get("total_bytes", 0) / (1024**3),
            memory_available_gb=mem_info.get("data", {}).get("available_bytes", 0) / (1024**3),
            storage_total_gb=storage.get("data", {}).get("total_bytes", 0) / (1024**3),
            storage_used_gb=storage.get("data", {}).get("used_bytes", 0) / (1024**3),
        )
    
    async def get_cpu_usage(self, interval_ms: int = 1000) -> Dict:
        """Get CPU usage percentages."""
        return await self._call("cpu.usage", {"interval": interval_ms})
    
    async def get_cpu_temperature(self) -> Dict:
        """Get CPU temperatures."""
        return await self._call("cpu.temperature", {})
    
    async def get_cpu_frequency(self) -> Dict:
        """Get CPU frequencies."""
        return await self._call("cpu.frequency", {})
    
    async def get_memory_usage(self) -> Dict:
        """Get memory usage details."""
        return await self._call("memory.usage", {})
    
    async def get_swap_info(self) -> Dict:
        """Get swap information."""
        return await self._call("memory.swap", {})
    
    async def get_storage_info(self) -> Dict:
        """Get storage information."""
        return await self._call("storage.info", {})
    
    async def get_storage_devices(self) -> Dict:
        """Get storage device details."""
        return await self._call("storage.devices", {})
    
    # =========================================================================
    # Network Information
    # =========================================================================
    
    async def get_network_interfaces(self) -> Dict:
        """Get network interfaces."""
        return await self._call("network.interfaces", {})
    
    async def get_network_addresses(self, interface: str = None) -> Dict:
        """Get network addresses."""
        params = {}
        if interface:
            params["interface"] = interface
        return await self._call("network.addresses", params)
    
    async def get_network_routes(self) -> Dict:
        """Get network routes."""
        return await self._call("network.routes", {})
    
    async def get_network_stats(self) -> Dict:
        """Get network statistics."""
        return await self._call("network.stats", {})
    
    # =========================================================================
    # Process Management
    # =========================================================================
    
    async def list_processes(self, limit: int = 100, sort_by: str = "cpu") -> Dict:
        """List processes."""
        return await self._call("process.list", {"limit": limit, "sort_by": sort_by})
    
    async def get_process_info(self, pid: int) -> Dict:
        """Get process information."""
        return await self._call("process.info", {"pid": pid})
    
    async def get_process_tree(self) -> Dict:
        """Get process tree."""
        return await self._call("process.tree", {})
    
    # =========================================================================
    # Service Management (Read-only)
    # =========================================================================
    
    async def list_services(self) -> Dict:
        """List systemd services."""
        return await self._call("service.list", {})
    
    async def get_service_info(self, name: str) -> Dict:
        """Get service information."""
        return await self._call("service.info", {"name": name})
    
    async def get_service_status(self, name: str) -> Dict:
        """Get service status."""
        return await self._call("service.status", {"name": name})
    
    # =========================================================================
    # Hardware Information
    # =========================================================================
    
    async def get_hardware_computer(self) -> Dict:
        """Get computer hardware info."""
        return await self._call("hardware.computer", {})
    
    async def get_hardware_bios(self) -> Dict:
        """Get BIOS information."""
        return await self._call("hardware.bios", {})
    
    async def get_hardware_chassis(self) -> Dict:
        """Get chassis information."""
        return await self._call("hardware.chassis", {})
    
    async def get_hardware_motherboard(self) -> Dict:
        """Get motherboard information."""
        return await self._call("hardware.motherboard", {})
    
    # =========================================================================
    # System Logs
    # =========================================================================
    
    async def get_journald_logs(
        self,
        lines: int = 100,
        unit: str = None,
        since: str = None,
        priority: str = None,
        grep: str = None,
    ) -> Dict:
        """Get journald logs."""
        params = {"lines": lines}
        if unit:
            params["unit"] = unit
        if since:
            params["since"] = since
        if priority:
            params["priority"] = priority
        if grep:
            params["grep"] = grep
        return await self._call("logs.journald", params)
    
    async def get_kernel_logs(self, lines: int = 100) -> Dict:
        """Get kernel logs."""
        return await self._call("logs.kernel", {"lines": lines})
    
    async def get_syslog_logs(self, lines: int = 100) -> Dict:
        """Get syslog logs."""
        return await self._call("logs.syslog", {"lines": lines})
    
    # =========================================================================
    # Policy Management
    # =========================================================================
    
    async def policy_grant(
        self,
        subject: str,
        resource: str,
        action: str = "allow",
        conditions: List[str] = None,
        expires_at: str = None,
    ) -> Dict:
        """Grant a policy permission."""
        params = {
            "subject": subject,
            "resource": resource,
            "action": action,
        }
        if conditions:
            params["conditions"] = conditions
        if expires_at:
            params["expires_at"] = expires_at
        return await self._call("policy.grant", params)
    
    async def policy_revoke(self, grant_id: str) -> Dict:
        """Revoke a policy permission."""
        return await self._call("policy.revoke", {"grant_id": grant_id})
    
    async def policy_list(self) -> Dict:
        """List all policy grants."""
        return await self._call("policy.list", {})
    
    async def policy_check(self, subject: str, resource: str) -> Dict:
        """Check policy permission."""
        return await self._call("policy.check", {"subject": subject, "resource": resource})
    
    # =========================================================================
    # Bridge Management
    # =========================================================================
    
    async def ping(self) -> Dict:
        """Ping the bridge."""
        return await self._call("bridge.ping", {})
    
    async def version(self) -> Dict:
        """Get bridge version."""
        return await self._call("bridge.version", {})


class SyncJarvisOSBridgeClient:
    """Synchronous wrapper for the async bridge client."""
    
    def __init__(self, config: BridgeConfig = None):
        self._async_client = JarvisOSBridgeClient(config)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    def _get_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
        return self._loop
    
    def connect(self) -> None:
        self._get_loop().run_until_complete(self._async_client.connect())
    
    def disconnect(self) -> None:
        self._get_loop().run_until_complete(self._async_client.disconnect())
    
    def __getattr__(self, name: str):
        if hasattr(self._async_client, name):
            async_method = getattr(self._async_client, name)
            def sync_wrapper(*args, **kwargs):
                return self._get_loop().run_until_complete(async_method(*args, **kwargs))
            return sync_wrapper
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")


# =============================================================================
# JARVIS Intelligence Integration
# =============================================================================

class JARVISOSIntegration:
    """
    Integrates JARVIS-OS Bridge with JARVIS Intelligence core.
    
    This class provides the glue between:
    - JARVIS cognitive loop (jarvis.core.loop)
    - JARVIS PolicyEngine (jarvis.policy.policy)
    - JARVIS-OS Bridge (Rust daemon)
    """
    
    def __init__(self, jarvis_core=None, policy_engine=None):
        self.jarvis_core = jarvis_core
        self.policy_engine = policy_engine
        self.bridge_client = JarvisOSBridgeClient()
        self._system_monitor_task: Optional[asyncio.Task] = None
        self._running = False
    
    async def initialize(self) -> bool:
        """Initialize the integration."""
        try:
            await self.bridge_client.connect()
            
            # Test connection
            ping_result = await self.bridge_client.ping()
            if not ping_result.get("data", {}).get("status") == "ok":
                logger.error("Bridge ping failed")
                return False
            
            # Register policy grants for JARVIS core
            if self.policy_engine:
                await self._register_core_grants()
            
            # Start system monitoring
            self._running = True
            self._system_monitor_task = asyncio.create_task(self._system_monitor_loop())
            
            logger.info("JARVIS-OS Integration initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize JARVIS-OS Integration: {e}")
            return False
    
    async def shutdown(self) -> None:
        """Shutdown the integration."""
        self._running = False
        if self._system_monitor_task:
            self._system_monitor_task.cancel()
            try:
                await self._system_monitor_task
            except asyncio.CancelledError:
                pass
        await self.bridge_client.disconnect()
        logger.info("JARVIS-OS Integration shutdown")
    
    async def _register_core_grants(self) -> None:
        """Register default policy grants for JARVIS core."""
        grants = [
            ("jarvis-core", "system.info"),
            ("jarvis-core", "system.uptime"),
            ("jarvis-core", "cpu.info"),
            ("jarvis-core", "cpu.usage"),
            ("jarvis-core", "cpu.temperature"),
            ("jarvis-core", "memory.info"),
            ("jarvis-core", "memory.usage"),
            ("jarvis-core", "storage.info"),
            ("jarvis-core", "storage.usage"),
            ("jarvis-core", "network.interfaces"),
            ("jarvis-core", "network.stats"),
            ("jarvis-core", "process.list"),
            ("jarvis-core", "service.list"),
            ("jarvis-core", "hardware.computer"),
            ("jarvis-core", "logs.journald"),
        ]
        
        for subject, resource in grants:
            try:
                await self.bridge_client.policy_grant(subject, resource, "allow")
            except Exception as e:
                logger.warning(f"Failed to register grant {subject}/{resource}: {e}")
    
    async def _system_monitor_loop(self, interval: float = 30.0) -> None:
        """Background system monitoring loop."""
        while self._running:
            try:
                # Collect system metrics
                metrics = await self.collect_system_metrics()
                
                # Feed to JARVIS core if available
                if self.jarvis_core and hasattr(self.jarvis_core, 'memory_palace'):
                    # Store in memory palace
                    pass
                
                # Check for anomalies
                await self._check_anomalies(metrics)
                
            except Exception as e:
                logger.error(f"System monitor error: {e}")
            
            await asyncio.sleep(interval)
    
    async def collect_system_metrics(self) -> Dict:
        """Collect comprehensive system metrics."""
        return {
            "cpu": await self.bridge_client.get_cpu_usage(500),
            "memory": await self.bridge_client.get_memory_usage(),
            "storage": await self.bridge_client.get_storage_info(),
            "network": await self.bridge_client.get_network_stats(),
            "temperature": await self.bridge_client.get_cpu_temperature(),
        }
    
    async def _check_anomalies(self, metrics: Dict) -> None:
        """Check for system anomalies."""
        # CPU usage anomaly
        cpu_data = metrics.get("cpu", {}).get("data", {})
        avg_cpu = cpu_data.get("average", 0)
        if avg_cpu > 90:
            logger.warning(f"High CPU usage: {avg_cpu}%")
        
        # Memory anomaly
        mem_data = metrics.get("memory", {}).get("data", {})
        mem_usage = mem_data.get("usage_percent", 0)
        if mem_usage > 90:
            logger.warning(f"High memory usage: {mem_usage}%")
        
        # Temperature anomaly
        temp_data = metrics.get("temperature", {}).get("data", {})
        temps = temp_data.get("temperatures", [])
        for t in temps:
            if t.get("temperature_celsius", 0) > 85:
                logger.warning(f"High temperature: {t}")
    
    # Delegate methods for easy access
    async def get_system_info(self) -> SystemInfo:
        return await self.bridge_client.get_system_info()
    
    async def get_metrics(self) -> Dict:
        return await self.collect_system_metrics()


# Convenience function for quick access
async def create_jarvis_os_integration(
    jarvis_core=None,
    policy_engine=None,
) -> JARVISOSIntegration:
    """Create and initialize JARVIS-OS Integration."""
    integration = JARVISOSIntegration(jarvis_core, policy_engine)
    if await integration.initialize():
        return integration
    raise RuntimeError("Failed to initialize JARVIS-OS Integration")