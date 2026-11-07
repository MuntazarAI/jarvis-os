//! Memory information module.

use crate::modules::{ModuleHandler, result_ok};
use async_trait::async_trait;
use serde_json::Value;
use std::fs;

pub struct MemoryModule;

#[async_trait]
impl ModuleHandler for MemoryModule {
    async fn handle(&self, method: &str, _params: &Value) -> Result<Value, String> {
        match method {
            "info" => self.memory_info().await,
            "usage" => self.memory_usage().await,
            "swap" => self.swap_info().await,
            _ => Err(format!("Unknown memory method: {}", method)),
        }
    }
}

impl MemoryModule {
    async fn memory_info(&self) -> Result<Value, String> {
        let meminfo = Self::read_meminfo()?;
        
        let total_kb = meminfo.get("MemTotal").copied().unwrap_or(0);
        let available_kb = meminfo.get("MemAvailable").copied().unwrap_or(0);
        let free_kb = meminfo.get("MemFree").copied().unwrap_or(0);
        let buffers_kb = meminfo.get("Buffers").copied().unwrap_or(0);
        let cached_kb = meminfo.get("Cached").copied().unwrap_or(0);
        let swap_total_kb = meminfo.get("SwapTotal").copied().unwrap_or(0);
        let swap_free_kb = meminfo.get("SwapFree").copied().unwrap_or(0);
        
        Ok(result_ok(serde_json::json!({
            "total_bytes": total_kb * 1024,
            "available_bytes": available_kb * 1024,
            "free_bytes": free_kb * 1024,
            "buffers_bytes": buffers_kb * 1024,
            "cached_bytes": cached_kb * 1024,
            "swap_total_bytes": swap_total_kb * 1024,
            "swap_free_bytes": swap_free_kb * 1024,
        })))
    }

    async fn memory_usage(&self) -> Result<Value, String> {
        let meminfo = Self::read_meminfo()?;
        
        let total_kb = meminfo.get("MemTotal").copied().unwrap_or(0);
        let available_kb = meminfo.get("MemAvailable").copied().unwrap_or(0);
        let free_kb = meminfo.get("MemFree").copied().unwrap_or(0);
        let buffers_kb = meminfo.get("Buffers").copied().unwrap_or(0);
        let cached_kb = meminfo.get("Cached").copied().unwrap_or(0);
        let sreclaimable_kb = meminfo.get("SReclaimable").copied().unwrap_or(0);
        let shmem_kb = meminfo.get("Shmem").copied().unwrap_or(0);
        
        let used_kb = total_kb - available_kb;
        let usage_percent = if total_kb > 0 {
            (used_kb as f64 / total_kb as f64) * 100.0
        } else {
            0.0
        };
        
        Ok(result_ok(serde_json::json!({
            "total_bytes": total_kb * 1024,
            "used_bytes": used_kb * 1024,
            "free_bytes": free_kb * 1024,
            "available_bytes": available_kb * 1024,
            "buffers_bytes": buffers_kb * 1024,
            "cached_bytes": cached_kb * 1024,
            "shared_bytes": (shmem_kb - sreclaimable_kb).max(0) * 1024,
            "usage_percent": usage_percent,
        })))
    }

    async fn swap_info(&self) -> Result<Value, String> {
        let meminfo = Self::read_meminfo()?;
        
        let swap_total_kb = meminfo.get("SwapTotal").copied().unwrap_or(0);
        let swap_free_kb = meminfo.get("SwapFree").copied().unwrap_or(0);
        let swap_used_kb = swap_total_kb - swap_free_kb;
        let swap_usage_percent = if swap_total_kb > 0 {
            (swap_used_kb as f64 / swap_total_kb as f64) * 100.0
        } else {
            0.0
        };
        
        Ok(result_ok(serde_json::json!({
            "total_bytes": swap_total_kb * 1024,
            "used_bytes": swap_used_kb * 1024,
            "free_bytes": swap_free_kb * 1024,
            "usage_percent": swap_usage_percent,
        })))
    }

    fn read_meminfo() -> Result<std::collections::HashMap<String, u64>, String> {
        let content = fs::read_to_string("/proc/meminfo").map_err(|e| e.to_string())?;
        let mut map = std::collections::HashMap::new();
        
        for line in content.lines() {
            if let Some((key, value)) = line.split_once(':') {
                let key = key.trim();
                let value = value.trim().split_whitespace().next().unwrap_or("0");
                if let Ok(val) = value.parse::<u64>() {
                    map.insert(key.to_string(), val);
                }
            }
        }
        
        Ok(map)
    }
}