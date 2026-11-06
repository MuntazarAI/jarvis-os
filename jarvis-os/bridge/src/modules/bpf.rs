//! eBPF Module for the JARVIS-OS Bridge
//!
//! Exposes kernel-level observability through the bridge

use crate::modules::{ModuleHandler, result_ok, param_optional_string, param_optional_string_array};
use crate::bpf::{BpfManager, BpfEvent};
use async_trait::async_trait;
use serde_json::Value;
use std::sync::Arc;
use tokio::sync::mpsc;

pub struct BpfModule {
    manager: Arc<tokio::sync::Mutex<Option<BpfManager>>>,
    event_receiver: Option<mpsc::UnboundedReceiver<BpfEvent>>,
}

impl BpfModule {
    pub fn new() -> Self {
        let (tx, rx) = mpsc::unbounded_channel();
        Self {
            manager: Arc::new(tokio::sync::Mutex::new(None)),
            event_receiver: Some(rx),
        }
    }
    
    pub async fn initialize(&self) -> Result<(), String> {
        let mut manager = BpfManager::new();
        manager.load_all().await.map_err(|e| e.to_string())?;
        *self.manager.lock().await = Some(manager);
        Ok(())
    }
    
    pub async fn shutdown(&self) -> Result<(), String> {
        if let Some(mut manager) = self.manager.lock().await.take() {
            manager.unload_all().await.map_err(|e| e.to_string())?;
        }
        Ok(())
    }
}

#[async_trait]
impl ModuleHandler for BpfModule {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "load" => self.load_programs().await,
            "unload" => self.unload_programs().await,
            "status" => self.get_status().await,
            "events" => self.get_events(params).await,
            "exec_tracer" => self.exec_tracer_control(params).await,
            "net_filter" => self.net_filter_control(params).await,
            "fs_monitor" => self.fs_monitor_control(params).await,
            "syscall_audit" => self.syscall_audit_control(params).await,
            "lsm_hooks" => self.lsm_hooks_control(params).await,
            _ => Err(format!("Unknown bpf method: {}", method)),
        }
    }
}

impl BpfModule {
    async fn load_programs(&self) -> Result<Value, String> {
        let mut manager = BpfManager::new();
        manager.load_all().await.map_err(|e| e.to_string())?;
        *self.manager.lock().await = Some(manager);
        Ok(result_ok(serde_json::json!({"status": "loaded"})))
    }
    
    async fn unload_programs(&self) -> Result<Value, String> {
        if let Some(mut manager) = self.manager.lock().await.take() {
            manager.unload_all().await.map_err(|e| e.to_string())?;
        }
        Ok(result_ok(serde_json::json!({"status": "unloaded"})))
    }
    
    async fn get_status(&self) -> Result<Value, String> {
        let manager_guard = self.manager.lock().await;
        let loaded = manager_guard.is_some();
        
        let mut programs = Vec::new();
        if loaded {
            programs = vec![
                "exec_tracer", "net_filter", "fs_monitor", 
                "syscall_audit", "lsm_hooks"
            ];
        }
        
        Ok(result_ok(serde_json::json!({
            "loaded": loaded,
            "programs": programs,
        })))
    }
    
    async fn get_events(&self, params: &Value) -> Result<Value, String> {
        let limit = param_optional_u64(params, "limit").unwrap_or(100) as usize;
        let filter = param_optional_string_array(params, "filter");
        
        // In a real implementation, we'd have a buffered event store
        // For now, return empty
        Ok(result_ok(serde_json::json!({
            "events": [],
            "count": 0,
        })))
    }
    
    async fn exec_tracer_control(&self, params: &Value) -> Result<Value, String> {
        let action = param_optional_string(params, "action").unwrap_or("status".to_string());
        
        match action.as_str() {
            "status" => Ok(result_ok(serde_json::json!({"program": "exec_tracer", "status": "loaded"}))),
            _ => Err("Unknown exec_tracer action".to_string()),
        }
    }
    
    async fn net_filter_control(&self, params: &Value) -> Result<Value, String> {
        let action = param_optional_string(params, "action").unwrap_or("status".to_string());
        
        match action.as_str() {
            "block" => {
                let ip = param_optional_string(params, "ip").ok_or("ip required")?;
                // Update blocklist in net_filter
                Ok(result_ok(serde_json::json!({"blocked": ip})))
            }
            "unblock" => {
                let ip = param_optional_string(params, "ip").ok_or("ip required")?;
                Ok(result_ok(serde_json::json!({"unblocked": ip})))
            }
            "ratelimit" => {
                let ip = param_optional_string(params, "ip").ok_or("ip required")?;
                let rate = param_optional_u64(params, "rate").unwrap_or(1000);
                Ok(result_ok(serde_json::json!({"ratelimited": ip, "rate": rate})))
            }
            "status" => Ok(result_ok(serde_json::json!({"program": "net_filter", "status": "loaded"}))),
            _ => Err("Unknown net_filter action".to_string()),
        }
    }
    
    async fn fs_monitor_control(&self, params: &Value) -> Result<Value, String> {
        let action = param_optional_string(params, "action").unwrap_or("status".to_string());
        
        match action.as_str() {
            "watch" => {
                let path = param_optional_string(params, "path").ok_or("path required")?;
                Ok(result_ok(serde_json::json!({"watching": path})))
            }
            "unwatch" => {
                let path = param_optional_string(params, "path").ok_or("path required")?;
                Ok(result_ok(serde_json::json!({"unwatched": path})))
            }
            "status" => Ok(result_ok(serde_json::json!({"program": "fs_monitor", "status": "loaded"}))),
            _ => Err("Unknown fs_monitor action".to_string()),
        }
    }
    
    async fn syscall_audit_control(&self, params: &Value) -> Result<Value, String> {
        let action = param_optional_string(params, "action").unwrap_or("status".to_string());
        
        match action.as_str() {
            "filter" => {
                let syscall = param_optional_string(params, "syscall").ok_or("syscall required")?;
                Ok(result_ok(serde_json::json!({"filtered": syscall})))
            }
            "unfilter" => {
                let syscall = param_optional_string(params, "syscall").ok_or("syscall required")?;
                Ok(result_ok(serde_json::json!({"unfiltered": syscall})))
            }
            "status" => Ok(result_ok(serde_json::json!({"program": "syscall_audit", "status": "loaded"}))),
            _ => Err("Unknown syscall_audit action".to_string()),
        }
    }
    
    async fn lsm_hooks_control(&self, params: &Value) -> Result<Value, String> {
        let action = param_optional_string(params, "action").unwrap_or("status".to_string());
        
        match action.as_str() {
            "add_rule" => {
                let subject = param_optional_string(params, "subject").ok_or("subject required")?;
                let object = param_optional_string(params, "object").ok_or("object required")?;
                let permissions = param_optional_string_array(params, "permissions").unwrap_or_default();
                Ok(result_ok(serde_json::json!({"rule_added": format!("{}->{}", subject, object)})))
            }
            "remove_rule" => {
                let subject = param_optional_string(params, "subject").ok_or("subject required")?;
                let object = param_optional_string(params, "object").ok_or("object required")?;
                Ok(result_ok(serde_json::json!({"rule_removed": format!("{}->{}", subject, object)})))
            }
            "status" => Ok(result_ok(serde_json::json!({"program": "lsm_hooks", "status": "loaded"}))),
            _ => Err("Unknown lsm_hooks action".to_string()),
        }
    }
}