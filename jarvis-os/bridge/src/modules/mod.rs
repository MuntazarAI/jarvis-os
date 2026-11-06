//! Module handlers for the JARVIS-OS Bridge.

mod system;
mod cpu;
mod memory;
mod storage;
mod network;
mod process;
mod service;
mod hardware;
mod logs;
mod policy;

pub use system::SystemModule;
pub use cpu::CpuModule;
pub use memory::MemoryModule;
pub use storage::StorageModule;
pub use network::NetworkModule;
pub use process::ProcessModule;
pub use service::ServiceModule;
pub use hardware::HardwareModule;
pub use logs::LogsModule;
pub use policy::PolicyModule;

use crate::modules::{ModuleHandler, result_ok, param_optional_string, param_optional_u64, param_optional_bool, param_optional_string_array};
use async_trait::async_trait;
use serde_json::Value;

/// Module handler trait — each module implements this to handle its methods.
#[async_trait]
pub trait ModuleHandler: Send + Sync {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String>;
}

/// Helper to extract a string parameter with a default.
pub fn param_string(params: &Value, key: &str, default: &str) -> String {
    params
        .get(key)
        .and_then(|v| v.as_str())
        .unwrap_or(default)
        .to_string()
}

/// Helper to extract an optional string parameter.
pub fn param_optional_string(params: &Value, key: &str) -> Option<String> {
    params.get(key).and_then(|v| v.as_str()).map(|s| s.to_string())
}

/// Helper to extract an optional u64 parameter.
pub fn param_optional_u64(params: &Value, key: &str) -> Option<u64> {
    params.get(key).and_then(|v| v.as_u64())
}

/// Helper to extract an optional bool parameter.
pub fn param_optional_bool(params: &Value, key: &str) -> Option<bool> {
    params.get(key).and_then(|v| v.as_bool())
}

/// Helper to extract an optional array of strings.
pub fn param_optional_string_array(params: &Value, key: &str) -> Option<Vec<String>> {
    params
        .get(key)
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
}

/// Helper to create a successful result with optional data.
pub fn result_ok(data: Value) -> Value {
    serde_json::json!({
        "ok": true,
        "data": data,
    })
}

/// Helper to create an error result.
pub fn result_err(message: &str) -> Value {
    serde_json::json!({
        "ok": false,
        "error": message,
    })
}