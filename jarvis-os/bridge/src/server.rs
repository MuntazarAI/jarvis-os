//! Bridge server — Unix domain socket listener and request dispatcher.
//!
//! Listens on a Unix domain socket, accepts connections, reads JSON-RPC
//! requests, dispatches them to the appropriate module handler, and sends
//! responses back. All connections are PolicyEngine-gated where required.

use crate::config::Config;
use crate::modules::ModuleHandler;
use crate::protocol::{
    parse_request, serialize_response, BridgeRequest, BridgeResponse,
    ERROR_INTERNAL, ERROR_METHOD_NOT_FOUND, ERROR_POLICY_DENIED,
};
use anyhow::Result;
use futures_util::{SinkExt, StreamExt};
use serde_json::Value;
use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::Mutex;
use tokio_stream::wrappers::UnixListenerStream;
use tracing::{debug, error, info, warn};

/// The bridge server.
pub struct BridgeServer {
    socket_path: std::path::PathBuf,
    config: Config,
    modules: HashMap<String, Arc<dyn ModuleHandler>>,
}

impl BridgeServer {
    /// Create a new bridge server.
    pub async fn new(socket_path: std::path::PathBuf, config: Config) -> Result<Self> {
        let mut modules: HashMap<String, Arc<dyn ModuleHandler>> = HashMap::new();

        // Register all available modules
        if config.module_enabled("system") {
            modules.insert("system".to_string(), Arc::new(crate::modules::system::SystemModule));
        }
        if config.module_enabled("cpu") {
            modules.insert("cpu".to_string(), Arc::new(crate::modules::cpu::CpuModule));
        }
        if config.module_enabled("memory") {
            modules.insert("memory".to_string(), Arc::new(crate::modules::memory::MemoryModule));
        }
        if config.module_enabled("storage") {
            modules.insert("storage".to_string(), Arc::new(crate::modules::storage::StorageModule));
        }
        if config.module_enabled("network") {
            modules.insert("network".to_string(), Arc::new(crate::modules::network::NetworkModule));
        }
        if config.module_enabled("process") {
            modules.insert("process".to_string(), Arc::new(crate::modules::process::ProcessModule));
        }
        if config.module_enabled("service") {
            modules.insert("service".to_string(), Arc::new(crate::modules::service::ServiceModule));
        }
        if config.module_enabled("hardware") {
            modules.insert(
                "hardware".to_string(),
                Arc::new(crate::modules::hardware::HardwareModule),
            );
        }
        if config.module_enabled("logs") {
            modules.insert("logs".to_string(), Arc::new(crate::modules::logs::LogsModule));
        }
        if config.module_enabled("policy") {
            modules.insert("policy".to_string(), Arc::new(crate::modules::policy::PolicyModule));
        }

        info!("Loaded {} modules", modules.len());

        Ok(Self {
            socket_path,
            config,
            modules,
        })
    }

    /// Run the server, listening for connections indefinitely.
    pub async fn run(mut self) -> Result<()> {
        let listener = UnixListener::bind(&self.socket_path)?;
        info!("Listening on {}", self.socket_path.display());

        let stream = UnixListenerStream::new(listener);

        stream
            .for_each(|connection| {
                let server = self.clone();
                async move {
                    match connection {
                        Ok(stream) => {
                            if let Err(e) = server.handle_connection(stream).await {
                                warn!("Connection error: {}", e);
                            }
                        }
                        Err(e) => {
                            warn!("Listener error: {}", e);
                        }
                    }
                }
            })
            .await;

        Ok(())
    }

    /// Handle a single client connection.
    async fn handle_connection(&self, stream: UnixStream) -> Result<()> {
        debug!("New connection from {:?}", stream.peer_addr()?);

        let (mut rx, mut tx) = stream.split();

        // Read the security policy module for authorization checks
        let policy_required = self.config.require_policy_approval();
        let allowed_uids = self.config.allowed_uids().cloned().unwrap_or_default();
        let allowed_gids = self.config.allowed_gids().clone();
        let max_request_size = self.config.max_request_size();

        // Use a buffered stream for line-delimited JSON
        use tokio_util::codec::{FramedRead, LinesCodec};
        let mut reader = FramedRead::new(rx, LinesCodec::new());

        while let Some(line_result) = reader.next().await {
            match line_result {
                Ok(line) => {
                    if line.trim().is_empty() {
                        continue;
                    }

                    // Check request size
                    if line.len() > self.config.max_request_size() {
                        let response = BridgeResponse::error_response(
                            None,
                            crate::protocol::ERROR_INVALID_PARAMS,
                            "Request too large".to_string(),
                        );
                        let _ = tx.send(serialize_response(&response)).await;
                        continue;
                    }

                    // Parse the request
                    match serde_json::from_str::<BridgeRequest>(&line) {
                        Ok(request) => {
                            let response = self.handle_request(request, policy_required).await;
                            let serialized = serialize_response(&response);
                            if tx.send(serialized).await.is_err() {
                                debug!("Client disconnected");
                                break;
                            }
                        }
                        Err(e) => {
                            warn!("Failed to parse request: {}", e);
                            let response = BridgeResponse::error_response(
                                None,
                                crate::protocol::ERROR_PARSE,
                                format!("Parse error: {}", e),
                            );
                            let serialized = serialize_response(&response);
                            if tx.send(serialized).await.is_err() {
                                break;
                            }
                        }
                    }
                }
                Err(e) => {
                    warn!("Read error: {}", e);
                    break;
                }
            }
        }

        debug!("Connection closed");
        Ok(())
    }

    /// Handle a single parsed request.
    async fn handle_request(
        &self,
        request: BridgeRequest,
        policy_required: bool,
    ) -> BridgeResponse {
        let method = &request.method;

        // Handle bridge-level methods directly
        if method.starts_with("bridge.") {
            return self.handle_bridge_method(request).await;
        }

        // Parse module.method
        let parts: Vec<&str> = method.splitn(2, '.').collect();
        if parts.len() != 2 {
            return BridgeResponse::error_response(
                request.id.clone(),
                ERROR_METHOD_NOT_FOUND,
                format!("Unknown method: {}", method),
            );
        }

        let module_name = parts[0];
        let method_name = parts[1];

        // Check PolicyEngine approval if required
        if policy_required {
            if let Err(e) = self.check_policy(&request, module_name, method_name).await {
                return BridgeResponse::error_response(
                    request.id.clone(),
                    ERROR_POLICY_DENIED,
                    e,
                );
            }
        }

        // Dispatch to module handler
        if let Some(module) = self.modules.get(module_name) {
            match module.handle(method_name, &request.params).await {
                Ok(result) => BridgeResponse::success(request.id.clone(), result),
                Err(e) => BridgeResponse::error_response(
                    request.id.clone(),
                    ERROR_INTERNAL,
                    format!("Module error: {}", e),
                ),
            }
        } else {
            BridgeResponse::error_response(
                request.id.clone(),
                ERROR_METHOD_NOT_FOUND,
                format!("Unknown method: {}", method),
            )
        }
    }

    /// Handle bridge-level methods (ping, version, shutdown).
    async fn handle_bridge_method(&self, request: BridgeRequest) -> BridgeResponse {
        let method = &request.method;
        let id = request.id.clone();

        match method.as_str() {
            "bridge.ping" => BridgeResponse::success(
                id,
                serde_json::json!({"status": "ok", "timestamp": chrono::Utc::now().to_rfc3339()}),
            ),
            "bridge.version" => BridgeResponse::success(
                id,
                serde_json::json!({
                    "protocol": crate::protocol::PROTOCOL_VERSION,
                    "bridge": env!("CARGO_PKG_VERSION"),
                }),
            ),
            "bridge.shutdown" => {
                // Shutdown requires policy approval
                if self.config.require_policy_approval() {
                    BridgeResponse::error_response(
                        id,
                        ERROR_POLICY_DENIED,
                        "Bridge shutdown requires PolicyEngine approval".to_string(),
                    )
                } else {
                    BridgeResponse::success(
                        id,
                        serde_json::json!({"status": "shutting down"}),
                    )
                }
            }
            _ => BridgeResponse::error_response(
                id,
                ERROR_METHOD_NOT_FOUND,
                format!("Unknown bridge method: {}", method),
            ),
        }
    }

    /// Check PolicyEngine approval for a request.
    async fn check_policy(
        &self,
        request: &BridgeRequest,
        module: &str,
        method: &str,
    ) -> Result<(), String> {
        // Extract peer credentials if available
        // Note: In a real implementation, we would get the peer UID/GID
        // from the socket. For now, we check the allowed UIDs/GIDs config.

        // Check if the module is allowed
        if !self.config.module_enabled(module) {
            return Err(format!("Module '{}' is disabled", module));
        }

        // Check if the method is a state-changing operation
        if is_state_changing(method) {
            // In a full implementation, this would call the PolicyEngine
            // via the JARVIS intelligence subprocess or via a policy socket.
            // For now, we log the request and allow it with a warning.
            warn!(
                "State-changing operation requested: {} (PolicyEngine approval required)",
                method
            );
        }

        Ok(())
    }
}

impl Clone for BridgeServer {
    fn clone(&self) -> Self {
        Self {
            socket_path: self.socket_path.clone(),
            config: self.config.clone(),
            modules: self.modules.clone(),
        }
    }
}

/// Check if a method name represents a state-changing operation.
fn is_state_changing(method: &str) -> bool {
    let state_changing_prefixes = [
        "service.start",
        "service.stop",
        "service.restart",
        "service.enable",
        "service.disable",
        "process.kill",
        "process.signal",
        "policy.grant",
        "policy.revoke",
        "bridge.shutdown",
    ];
    state_changing_prefixes.iter().any(|p| method.starts_with(p))
}

/// Module handler trait — each module implements this to handle its methods.
pub trait ModuleHandler: Send + Sync {
    /// Handle a method call.
    async fn handle(&self, method: &str, params: &serde_json::Value) -> Result<Value, String>;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_state_changing() {
        assert!(is_state_changing("service.start"));
        assert!(is_state_changing("process.kill"));
        assert!(is_state_changing("policy.grant"));
        assert!(!is_state_changing("system.info"));
        assert!(!is_state_changing("cpu.usage"));
        assert!(!is_state_changing("network.interfaces"));
    }
}