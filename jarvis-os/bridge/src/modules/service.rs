//! Service management module (read-only inspection).

use crate::modules::{ModuleHandler, result_ok, param_optional_string};
use async_trait::async_trait;
use serde_json::Value;
use std::fs;
use std::process::Command;

pub struct ServiceModule;

#[async_trait]
impl ModuleHandler for ServiceModule {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "list" => self.service_list().await,
            "info" => self.service_info(params).await,
            "status" => self.service_status(params).await,
            _ => Err(format!("Unknown service method: {}", method)),
        }
    }
}

impl ServiceModule {
    async fn service_list(&self) -> Result<Value, String> {
        let mut services = Vec::new();
        
        // Use systemctl list-units --type=service --no-legend --no-pager
        let output = Command::new("systemctl")
            .args(["list-units", "--type=service", "--no-legend", "--no-pager", "--plain"])
            .output()
            .map_err(|e| e.to_string())?;
        
        let stdout = String::from_utf8_lossy(&output.stdout);
        for line in stdout.lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 4 {
                let name = parts[0];
                let load = parts[1];
                let active = parts[2];
                let sub = parts[3];
                let description = parts[4..].join(" ");
                
                services.push(serde_json::json!({
                    "name": name,
                    "load": load,
                    "active": active,
                    "sub": sub,
                    "description": description,
                }));
            }
        }
        
        Ok(result_ok(serde_json::json!({"services": services})))
    }

    async fn service_info(&self, params: &Value) -> Result<Value, String> {
        let name = param_optional_string(params, "name").ok_or("name parameter required")?;
        
        // Use systemctl show
        let output = Command::new("systemctl")
            .args(["show", &name, "--no-pager"])
            .output()
            .map_err(|e| e.to_string())?;
        
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut info = serde_json::Map::new();
        
        for line in stdout.lines() {
            if let Some((key, value)) = line.split_once('=') {
                info.insert(key.to_string(), Value::String(value.to_string()));
            }
        }
        
        Ok(result_ok(Value::Object(info)))
    }

    async fn service_status(&self, params: &Value) -> Result<Value, String> {
        let name = param_optional_string(params, "name").ok_or("name parameter required")?;
        
        let output = Command::new("systemctl")
            .args(["status", &name, "--no-pager"])
            .output()
            .map_err(|e| e.to_string())?;
        
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        
        Ok(result_ok(serde_json::json!({
            "name": name,
            "status_output": stdout,
            "error_output": stderr,
            "exit_code": output.status.code(),
        })))
    }
}