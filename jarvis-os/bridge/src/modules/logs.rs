//! System logs module (journald, kernel, syslog).

use crate::modules::{ModuleHandler, result_ok, param_optional_u64, param_optional_string, param_optional_string_array};
use async_trait::async_trait;
use serde_json::Value;
use std::process::Command;

pub struct LogsModule;

#[async_trait]
impl ModuleHandler for LogsModule {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "journald" => self.journald_logs(params).await,
            "kernel" => self.kernel_logs(params).await,
            "syslog" => self.syslog_logs(params).await,
            _ => Err(format!("Unknown logs method: {}", method)),
        }
    }
}

impl LogsModule {
    async fn journald_logs(&self, params: &Value) -> Result<Value, String> {
        let mut args = vec!["-n", &param_optional_u64(params, "lines").unwrap_or(100).to_string(), "--no-pager"];
        
        if let Some(unit) = param_optional_string(params, "unit") {
            args.push("-u");
            args.push(&unit);
        }
        
        if let Some(since) = param_optional_string(params, "since") {
            args.push("--since");
            args.push(&since);
        }
        
        if let Some(until) = param_optional_string(params, "until") {
            args.push("--until");
            args.push(&until);
        }
        
        if let Some(priority) = param_optional_string(params, "priority") {
            args.push("-p");
            args.push(&priority);
        }
        
        if let Some(grep) = param_optional_string(params, "grep") {
            args.push("-g");
            args.push(&grep);
        }
        
        if let Some(output_format) = param_optional_string(params, "output") {
            args.push("-o");
            args.push(&output_format);
        } else {
            args.push("-o");
            args.push("json");
        }
        
        if param_optional_string(params, "reverse").map(|s| s == "true").unwrap_or(false) {
            args.push("-r");
        }
        
        if param_optional_string(params, "follow").map(|s| s == "true").unwrap_or(false) {
            args.push("-f");
        }
        
        if let Some(identifier) = param_optional_string(params, "identifier") {
            args.push("-t");
            args.push(&identifier);
        }
        
        let output = Command::new("journalctl")
            .args(&args)
            .output()
            .map_err(|e| e.to_string())?;
        
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut entries = Vec::new();
        
        for line in stdout.lines() {
            if let Ok(entry) = serde_json::from_str::<Value>(line) {
                entries.push(entry);
            }
        }
        
        Ok(result_ok(serde_json::json!({"entries": entries, "count": entries.len()})))
    }

    async fn kernel_logs(&self, params: &Value) -> Result<Value, String> {
        let lines = param_optional_u64(params, "lines").unwrap_or(100) as usize;
        
        // Read from /dev/kmsg or use dmesg
        let output = Command::new("dmesg")
            .args(["-T", "--color=never"])
            .output()
            .map_err(|e| e.to_string())?;
        
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut entries = Vec::new();
        
        for line in stdout.lines().rev().take(lines).collect::<Vec<_>>().into_iter().rev() {
            entries.push(serde_json::json!({"message": line, "source": "kernel"}));
        }
        
        Ok(result_ok(serde_json::json!({"entries": entries, "count": entries.len()})))
    }

    async fn syslog_logs(&self, params: &Value) -> Result<Value, String> {
        let lines = param_optional_u64(params, "lines").unwrap_or(100) as usize;
        let files = param_optional_string_array(params, "files").unwrap_or_else(|| vec![
            "/var/log/syslog".to_string(),
            "/var/log/messages".to_string(),
        ]);
        
        let mut all_entries = Vec::new();
        
        for file in files {
            if let Ok(content) = std::fs::read_to_string(&file) {
                for line in content.lines().rev().take(lines).collect::<Vec<_>>().into_iter().rev() {
                    all_entries.push(serde_json::json!({
                        "message": line,
                        "source": "syslog",
                        "file": file,
                    }));
                }
            }
        }
        
        Ok(result_ok(serde_json::json!({"entries": all_entries, "count": all_entries.len()})))
    }
}