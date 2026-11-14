//! System information module.

use crate::modules::{ModuleHandler, result_ok, param_optional_string};
use async_trait::async_trait;
use serde_json::Value;
use std::fs;

pub struct SystemModule;

#[async_trait]
impl ModuleHandler for SystemModule {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "info" => self.system_info().await,
            "uptime" => self.uptime().await,
            "hostname" => self.hostname().await,
            "kernel_version" => self.kernel_version().await,
            "os_release" => self.os_release().await,
            _ => Err(format!("Unknown system method: {}", method)),
        }
    }
}

impl SystemModule {
    async fn system_info(&self) -> Result<Value, String> {
        let hostname = fs::read_to_string("/etc/hostname").unwrap_or_else(|_| "unknown".to_string()).trim().to_string();
        let kernel = fs::read_to_string("/proc/sys/kernel/osrelease").unwrap_or_else(|_| "unknown".to_string()).trim().to_string();
        let os_release = Self::read_os_release()?;
        
        Ok(result_ok(serde_json::json!({
            "hostname": hostname,
            "kernel": kernel,
            "os_release": os_release,
            "architecture": std::env::consts::ARCH,
        })))
    }

    async fn uptime(&self) -> Result<Value, String> {
        let content = fs::read_to_string("/proc/uptime").map_err(|e| e.to_string())?;
        let uptime_secs: f64 = content.split_whitespace().next().unwrap_or("0").parse().unwrap_or(0.0);
        
        Ok(result_ok(serde_json::json!({
            "uptime_seconds": uptime_secs,
            "uptime_human": Self::format_uptime(uptime_secs),
        })))
    }

    async fn hostname(&self) -> Result<Value, String> {
        let hostname = fs::read_to_string("/etc/hostname").unwrap_or_else(|_| "unknown".to_string()).trim().to_string();
        Ok(result_ok(serde_json::json!({"hostname": hostname})))
    }

    async fn kernel_version(&self) -> Result<Value, String> {
        let version = fs::read_to_string("/proc/sys/kernel/osrelease").unwrap_or_else(|_| "unknown".to_string()).trim().to_string();
        Ok(result_ok(serde_json::json!({"kernel_version": version})))
    }

    async fn os_release(&self) -> Result<Value, String> {
        let release = Self::read_os_release()?;
        Ok(result_ok(serde_json::json!({"os_release": release})))
    }

    fn read_os_release() -> Result<String, String> {
        let content = fs::read_to_string("/etc/os-release").map_err(|e| e.to_string())?;
        let mut pretty_name = "Unknown".to_string();
        for line in content.lines() {
            if line.starts_with("PRETTY_NAME=") {
                pretty_name = line["PRETTY_NAME=".len()..].trim_matches('"').to_string();
                break;
            }
        }
        Ok(pretty_name)
    }

    fn format_uptime(seconds: f64) -> String {
        let days = (seconds / 86400.0) as u64;
        let hours = ((seconds % 86400.0) / 3600.0) as u64;
        let minutes = ((seconds % 3600.0) / 60.0) as u64;
        let secs = (seconds % 60.0) as u64;
        
        if days > 0 {
            format!("{}d {}h {}m {}s", days, hours, minutes, secs)
        } else if hours > 0 {
            format!("{}h {}m {}s", hours, minutes, secs)
        } else if minutes > 0 {
            format!("{}m {}s", minutes, secs)
        } else {
            format!("{}s", secs)
        }
    }
}