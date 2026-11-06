#!/usr/bin/env python3
"""
JARVIS-OS Bridge PolicyEngine Client

Python client for the JARVIS-OS Bridge Unix domain socket.
Integrates with JARVIS PolicyEngine for gated system access.

Usage:
    from jarvis_os_bridge import JarvisOSBridgeClient
    
    async with JarvisOSBridgeClient() as client:
        result = await client.call("system.info", {})
        print(result)
"""

import asyncio
import json
import uuid
import logging
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, field
from pathlib import Path
import socket

logger = logging.getLogger(__name__)


@dataclass
class BridgeRequest:
    """JSON-RPC request to the bridge."""
    method: str
    params: Dict[str, Any]
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    def to_json(self) -> str:
        return json.dumps({
            "jsonrpc": "2.0",
            "method": self.method,
            "params": self.params,
            "id": self.request_id,
        })


@dataclass
class BridgeResponse:
    """JSON-RPC response from the bridge."""
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    request_id: Optional[str] = None
    
    @classmethod
    def from_json(cls, json_str: str) -> "BridgeResponse":
        data = json.loads(json_str)
        if "result" in data and data["result"]:
            result = data["result"]
            if isinstance(result, dict) and result.get("ok"):
                return cls(ok=True, data=result.get("data"), request_id=data.get("id"))
            else:
                return cls(ok=False, error=result.get("error") if isinstance(result, dict) else str(result), request_id=data.get("id"))
        elif "error" in data and data["error"]:
            return cls(ok=False, error=data["error"].get("message", "Unknown error"), request_id=data.get("id"))
        return cls(ok=False, error="Invalid response format", request_id=data.get("id"))


class JarvisOSBridgeClient:
    """
    Async client for JARVIS-OS Bridge.
    
    Communicates via Unix domain socket with JSON-RPC 2.0 protocol.
    All requests are PolicyEngine-gated on the bridge side.
    """
    
    def __init__(
        self,
        socket_path: str = "/run/jarvis-os/bridge.sock",
        timeout: float = 10.0,
        max_retries: int = 3,
    ):
        self.socket_path = socket_path
        self.timeout = timeout
        self.max_retries = max_retries
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._pending_requests: Dict[str, asyncio.Future] = {}
    
    async def connect(self) -> None:
        """Connect to the bridge socket."""
        if self._connected:
            return
            
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path),
                timeout=self.timeout
            )
            self._connected = True
            
            # Start background reader
            asyncio.create_task(self._read_loop())
            logger.info(f"Connected to JARVIS-OS Bridge at {self.socket_path}")
            
        except asyncio.TimeoutError:
            raise ConnectionError(f"Connection timeout to {self.socket_path}")
        except FileNotFoundError:
            raise ConnectionError(f"Bridge socket not found at {self.socket_path}. Is the bridge service running?")
        except PermissionError:
            raise ConnectionError(f"Permission denied connecting to {self.socket_path}. Check user/group membership.")
        except Exception as e:
            raise ConnectionError(f"Failed to connect to bridge: {e}")
    
    async def disconnect(self) -> None:
        """Disconnect from the bridge."""
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
        """Background task to read responses from the bridge."""
        try:
            while self._connected and self._reader:
                line = await self._reader.readline()
                if not line:
                    break
                
                line = line.decode().strip()
                if not line:
                    continue
                
                try:
                    response = BridgeResponse.from_json(line)
                    if response.request_id and response.request_id in self._pending_requests:
                        future = self._pending_requests.pop(response.request_id)
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
            # Cancel all pending requests
            for future in self._pending_requests.values():
                if not future.done():
                    future.set_exception(ConnectionError("Connection closed"))
            self._pending_requests.clear()
            self._connected = False
    
    async def call(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Make a JSON-RPC call to the bridge.
        
        Args:
            method: Method name (e.g., "system.info", "cpu.usage")
            params: Parameters dictionary
            
        Returns:
            Response data dictionary
            
        Raises:
            ConnectionError: If not connected or connection fails
            RuntimeError: If the bridge returns an error
        """
        if not self._connected:
            await self.connect()
        
        if params is None:
            params = {}
        
        request = BridgeRequest(method=method, params=params)
        future = asyncio.get_event_loop().create_future()
        self._pending_requests[request.request_id] = future
        
        try:
            # Send request
            self._writer.write((request.to_json() + "\n").encode())
            await self._writer.drain()
            
            # Wait for response with timeout
            response = await asyncio.wait_for(future, timeout=self.timeout)
            
            if response.ok:
                return response.data or {}
            else:
                raise RuntimeError(f"Bridge error: {response.error}")
                
        except asyncio.TimeoutError:
            self._pending_requests.pop(request.request_id, None)
            raise RuntimeError(f"Request timeout for {method}")
        except Exception as e:
            self._pending_requests.pop(request.request_id, None)
            raise
    
    # Convenience methods for common operations
    
    async def system_info(self) -> Dict[str, Any]:
        """Get system information."""
        return await self.call("system.info", {})
    
    async def system_uptime(self) -> Dict[str, Any]:
        """Get system uptime."""
        return await self.call("system.uptime", {})
    
    async def cpu_info(self) -> Dict[str, Any]:
        """Get CPU information."""
        return await self.call("cpu.info", {})
    
    async def cpu_usage(self, interval_ms: int = 1000) -> Dict[str, Any]:
        """Get CPU usage."""
        return await self.call("cpu.usage", {"interval": interval_ms})
    
    async def cpu_temperature(self) -> Dict[str, Any]:
        """Get CPU temperatures."""
        return await self.call("cpu.temperature", {})
    
    async def cpu_frequency(self) -> Dict[str, Any]:
        """Get CPU frequencies."""
        return await self.call("cpu.frequency", {})
    
    async def memory_info(self) -> Dict[str, Any]:
        """Get memory information."""
        return await self.call("memory.info", {})
    
    async def memory_usage(self) -> Dict[str, Any]:
        """Get memory usage."""
        return await self.call("memory.usage", {})
    
    async def swap_info(self) -> Dict[str, Any]:
        """Get swap information."""
        return await self.call("memory.swap", {})
    
    async def storage_info(self) -> Dict[str, Any]:
        """Get storage information."""
        return await self.call("storage.info", {})
    
    async def storage_usage(self) -> Dict[str, Any]:
        """Get storage usage."""
        return await self.call("storage.usage", {})
    
    async def storage_devices(self) -> Dict[str, Any]:
        """Get storage devices."""
        return await self.call("storage.devices", {})
    
    async def network_interfaces(self) -> Dict[str, Any]:
        """Get network interfaces."""
        return await self.call("network.interfaces", {})
    
    async def network_addresses(self, interface: Optional[str] = None) -> Dict[str, Any]:
        """Get network addresses."""
        params = {}
        if interface:
            params["interface"] = interface
        return await self.call("network.addresses", params)
    
    async def network_routes(self) -> Dict[str, Any]:
        """Get network routes."""
        return await self.call("network.routes", {})
    
    async def network_stats(self) -> Dict[str, Any]:
        """Get network statistics."""
        return await self.call("network.stats", {})
    
    async def process_list(self, limit: int = 100, sort_by: str = "cpu") -> Dict[str, Any]:
        """Get process list."""
        return await self.call("process.list", {"limit": limit, "sort_by": sort_by})
    
    async def process_info(self, pid: int) -> Dict[str, Any]:
        """Get process info."""
        return await self.call("process.info", {"pid": pid})
    
    async def process_tree(self) -> Dict[str, Any]:
        """Get process tree."""
        return await self.call("process.tree", {})
    
    async def service_list(self) -> Dict[str, Any]:
        """List systemd services."""
        return await self.call("service.list", {})
    
    async def service_info(self, name: str) -> Dict[str, Any]:
        """Get service info."""
        return await self.call("service.info", {"name": name})
    
    async def service_status(self, name: str) -> Dict[str, Any]:
        """Get service status."""
        return await self.call("service.status", {"name": name})
    
    async def hardware_computer(self) -> Dict[str, Any]:
        """Get computer hardware info."""
        return await self.call("hardware.computer", {})
    
    async def hardware_bios(self) -> Dict[str, Any]:
        """Get BIOS info."""
        return await self.call("hardware.bios", {})
    
    async def hardware_chassis(self) -> Dict[str, Any]:
        """Get chassis info."""
        return await self.call("hardware.chassis", {})
    
    async def hardware_motherboard(self) -> Dict[str, Any]:
        """Get motherboard info."""
        return await self.call("hardware.motherboard", {})
    
    async def logs_journald(
        self,
        lines: int = 100,
        unit: Optional[str] = None,
        since: Optional[str] = None,
        priority: Optional[str] = None,
        grep: Optional[str] = None,
    ) -> Dict[str, Any]:
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
        return await self.call("logs.journald", params)
    
    async def logs_kernel(self, lines: int = 100) -> Dict[str, Any]:
        """Get kernel logs."""
        return await self.call("logs.kernel", {"lines": lines})
    
    async def logs_syslog(self, lines: int = 100) -> Dict[str, Any]:
        """Get syslog logs."""
        return await self.call("logs.syslog", {"lines": lines})
    
    async def policy_grant(
        self,
        subject: str,
        resource: str,
        action: str = "allow",
        conditions: Optional[List[str]] = None,
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
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
        return await self.call("policy.grant", params)
    
    async def policy_revoke(self, grant_id: str) -> Dict[str, Any]:
        """Revoke a policy permission."""
        return await self.call("policy.revoke", {"grant_id": grant_id})
    
    async def policy_list(self) -> Dict[str, Any]:
        """List all policy grants."""
        return await self.call("policy.list", {})
    
    async def policy_check(self, subject: str, resource: str) -> Dict[str, Any]:
        """Check if a subject has permission for a resource."""
        return await self.call("policy.check", {"subject": subject, "resource": resource})
    
    async def bridge_ping(self) -> Dict[str, Any]:
        """Ping the bridge."""
        return await self.call("bridge.ping", {})
    
    async def bridge_version(self) -> Dict[str, Any]:
        """Get bridge version."""
        return await self.call("bridge.version", {})


# Synchronous wrapper for non-async contexts
class SyncJarvisOSBridgeClient:
    """Synchronous wrapper for the async client."""
    
    def __init__(self, socket_path: str = "/run/jarvis-os/bridge.sock", timeout: float = 10.0):
        self._async_client = JarvisOSBridgeClient(socket_path, timeout)
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
    
    def call(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._get_loop().run_until_complete(self._async_client.call(method, params))
    
    # Delegate all convenience methods
    def __getattr__(self, name: str):
        if hasattr(self._async_client, name):
            async_method = getattr(self._async_client, name)
            def sync_wrapper(*args, **kwargs):
                return self._get_loop().run_until_complete(async_method(*args, **kwargs))
            return sync_wrapper
        raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")


# Example usage and testing
async def main():
    """Test the bridge client."""
    logging.basicConfig(level=logging.INFO)
    
    async with JarvisOSBridgeClient() as client:
        # Test ping
        print("Ping:", await client.bridge_ping())
        
        # Test version
        print("Version:", await client.bridge_version())
        
        # Test system info
        print("System:", await client.system_info())
        
        # Test CPU info
        print("CPU:", await client.cpu_info())
        
        # Test CPU usage
        print("CPU Usage:", await client.cpu_usage(500))
        
        # Test memory
        print("Memory:", await client.memory_usage())
        
        # Test storage
        print("Storage:", await client.storage_usage())
        
        # Test network
        print("Network:", await client.network_interfaces())
        
        # Test processes
        print("Processes:", await client.process_list(limit=5))
        
        # Test services
        print("Services:", await client.service_list())
        
        # Test hardware
        print("Hardware:", await client.hardware_computer())
        
        # Test logs
        print("Logs:", await client.logs_journald(lines=5))


if __name__ == "__main__":
    asyncio.run(main())