//! Protocol definitions for the JARVIS-OS System Bridge.
//!
//! All messages are JSON-RPC 2.0 compatible with typed method names and
//! validated parameters. Versioned protocol: v1 is the initial release.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use uuid::Uuid;

/// Protocol version
pub const PROTOCOL_VERSION: &str = "1.0";

/// A JSON-RPC 2.0 request from JARVIS intelligence to the bridge.
#[derive(Debug, Serialize, Deserialize)]
pub struct BridgeRequest {
    pub jsonrpc: String,
    pub method: String,
    pub params: Value,
    pub id: Option<Value>,
}

/// A JSON-RPC 2.0 response from the bridge to JARVIS intelligence.
#[derive(Debug, Serialize, Deserialize)]
pub struct BridgeResponse {
    pub jsonrpc: String,
    pub result: Option<Value>,
    pub error: Option<BridgeError>,
    pub id: Option<Value>,
}

/// Error information for a bridge response.
#[derive(Debug, Serialize, Deserialize)]
pub struct BridgeError {
    pub code: i32,
    pub message: String,
    pub data: Option<Value>,
}

impl BridgeRequest {
    pub fn new(method: &str, params: Value) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            method: method.to_string(),
            params,
            id: Some(Value::String(Uuid::new_v4().to_string())),
        }
    }

    pub fn notification(method: &str, params: Value) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            method: method.to_string(),
            params,
            id: None,
        }
    }
}

impl BridgeResponse {
    pub fn success(id: Option<Value>, result: Value) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            result: Some(result),
            error: None,
            id,
        }
    }

    pub fn error_response(id: Option<Value>, code: i32, message: String) -> Self {
        Self {
            jsonrpc: "2.0".to_string(),
            result: None,
            error: Some(BridgeError {
                code,
                message,
                data: None,
            }),
            id,
        }
    }
}

/// Standard error codes.
pub const ERROR_PARSE: i32 = -32700;
pub const ERROR_INVALID_REQUEST: i32 = -32600;
pub const ERROR_METHOD_NOT_FOUND: i32 = -32601;
pub const ERROR_INVALID_PARAMS: i32 = -32602;
pub const ERROR_INTERNAL: i32 = -32603;
pub const ERROR_POLICY_DENIED: i32 = -32001;
pub const ERROR_RESOURCE_NOT_FOUND: i32 = -32002;
pub const ERROR_OPERATION_NOT_SUPPORTED: i32 = -32003;

/// All supported bridge methods, organized by category.
pub mod methods {
    pub mod system {
        pub const INFO: &str = "system.info";
        pub const UPTIME: &str = "system.uptime";
        pub const HOSTNAME: &str = "system.hostname";
        pub const KERNEL_VERSION: &str = "system.kernel_version";
        pub const OS_RELEASE: &str = "system.os_release";
    }

    pub mod cpu {
        pub const INFO: &str = "cpu.info";
        pub const USAGE: &str = "cpu.usage";
        pub const TEMPERATURE: &str = "cpu.temperature";
        pub const FREQUENCY: &str = "cpu.frequency";
    }

    pub mod memory {
        pub const INFO: &str = "memory.info";
        pub const USAGE: &str = "memory.usage";
        pub const SWAP: &str = "memory.swap";
    }

    pub mod storage {
        pub const INFO: &str = "storage.info";
        pub const USAGE: &str = "storage.usage";
        pub const DEVICES: &str = "storage.devices";
    }

    pub mod network {
        pub const INTERFACES: &str = "network.interfaces";
        pub const ADDRESSES: &str = "network.addresses";
        pub const ROUTES: &str = "network.routes";
        pub const STATS: &str = "network.stats";
    }

    pub mod process {
        pub const LIST: &str = "process.list";
        pub const INFO: &str = "process.info";
        pub const TREE: &str = "process.tree";
    }

    pub mod service {
        pub const LIST: &str = "service.list";
        pub const INFO: &str = "service.info";
        pub const STATUS: &str = "service.status";
    }

    pub mod hardware {
        pub const COMPUTER: &str = "hardware.computer";
        pub const BIOS: &str = "hardware.bios";
        pub const CHASSIS: &str = "hardware.chassis";
        pub const MOTHERBOARD: &str = "hardware.motherboard";
    }

    pub mod logs {
        pub const JOURNALD: &str = "logs.journald";
        pub const KERNEL: &str = "logs.kernel";
        pub const SYSLOG: &str = "logs.syslog";
    }

    pub mod policy {
        pub const GRANT: &str = "policy.grant";
        pub const REVOKE: &str = "policy.revoke";
        pub const LIST: &str = "policy.list";
        pub const CHECK: &str = "policy.check";
    }

    pub mod bridge {
        pub const PING: &str = "bridge.ping";
        pub const VERSION: &str = "bridge.version";
        pub const SHUTDOWN: &str = "bridge.shutdown";
    }
}

/// Parse a raw JSON value into a typed BridgeRequest.
pub fn parse_request(value: Value) -> Result<BridgeRequest, BridgeError> {
    serde_json::from_value(value).map_err(|e| BridgeError {
        code: ERROR_INVALID_REQUEST,
        message: format!("Invalid request: {}", e),
        data: None,
    })
}

/// Serialize a BridgeResponse into a JSON value.
pub fn serialize_response(response: &BridgeResponse) -> Value {
    serde_json::to_value(response).unwrap_or_else(|_| {
        Value::Object(serde_json::Map::from_iter([
            ("jsonrpc".to_string(), Value::String("2.0".to_string())),
            ("error".to_string(), Value::Object(serde_json::Map::from_iter([
                ("code".to_string(), Value::Number(serde_json::Number::from(ERROR_INTERNAL))),
                ("message".to_string(), Value::String("Internal serialization error".to_string())),
            ]))),
            ("id".to_string(), Value::Null),
        ]))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_request_serialization() {
        let req = BridgeRequest::new("system.info", serde_json::json!({}));
        let serialized = serde_json::to_string(&req).unwrap();
        let deserialized: BridgeRequest = serde_json::from_str(&serialized).unwrap();
        assert_eq!(req.method, deserialized.method);
        assert_eq!(req.jsonrpc, deserialized.jsonrpc);
    }

    #[test]
    fn test_response_success() {
        let resp = BridgeResponse::success(
            Some(Value::String("test-id".to_string())),
            serde_json::json!({"status": "ok"}),
        );
        assert!(resp.result.is_some());
        assert!(resp.error.is_none());
    }

    #[test]
    fn test_response_error() {
        let resp = BridgeResponse::error_response(
            Some(Value::String("test-id".to_string())),
            ERROR_POLICY_DENIED,
            "Access denied".to_string(),
        );
        assert!(resp.error.is_some());
        assert_eq!(resp.error.unwrap().code, ERROR_POLICY_DENIED);
    }
}