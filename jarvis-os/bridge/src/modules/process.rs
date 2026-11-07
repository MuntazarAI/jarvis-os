//! Process information module.

use crate::modules::{ModuleHandler, result_ok, param_optional_u64, param_optional_string};
use async_trait::async_trait;
use serde_json::Value;
use std::fs;

pub struct ProcessModule;

#[async_trait]
impl ModuleHandler for ProcessModule {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "list" => self.process_list(params).await,
            "info" => self.process_info(params).await,
            "tree" => self.process_tree().await,
            _ => Err(format!("Unknown process method: {}", method)),
        }
    }
}

impl ProcessModule {
    async fn process_list(&self, params: &Value) -> Result<Value, String> {
        let limit = param_optional_u64(params, "limit").unwrap_or(100) as usize;
        let sort_by = param_optional_string(params, "sort_by").unwrap_or("cpu".to_string());
        
        let mut processes = Vec::new();
        
        if let Ok(entries) = fs::read_dir("/proc") {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if let Ok(pid) = name.parse::<u32>() {
                    if let Ok(proc_info) = Self::read_process_info(pid) {
                        processes.push(proc_info);
                    }
                }
            }
        }
        
        // Sort
        match sort_by.as_str() {
            "cpu" => processes.sort_by(|a, b| b.get("cpu_percent").and_then(|v| v.as_f64()).unwrap_or(0.0)
                .partial_cmp(&a.get("cpu_percent").and_then(|v| v.as_f64()).unwrap_or(0.0))
                .unwrap_or(std::cmp::Ordering::Equal)),
            "memory" => processes.sort_by(|a, b| b.get("memory_rss").and_then(|v| v.as_u64()).unwrap_or(0)
                .cmp(&a.get("memory_rss").and_then(|v| v.as_u64()).unwrap_or(0))),
            "pid" => processes.sort_by(|a, b| a.get("pid").and_then(|v| v.as_u64()).unwrap_or(0)
                .cmp(&b.get("pid").and_then(|v| v.as_u64()).unwrap_or(0))),
            _ => {}
        }
        
        if processes.len() > limit {
            processes.truncate(limit);
        }
        
        Ok(result_ok(serde_json::json!({"processes": processes, "count": processes.len()})))
    }

    async fn process_info(&self, params: &Value) -> Result<Value, String> {
        let pid = param_optional_u64(params, "pid").ok_or("pid parameter required")? as u32;
        
        let info = Self::read_process_info(pid)?;
        Ok(result_ok(info))
    }

    async fn process_tree(&self) -> Result<Value, String> {
        let mut processes = std::collections::HashMap::new();
        
        if let Ok(entries) = fs::read_dir("/proc") {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if let Ok(pid) = name.parse::<u32>() {
                    if let Ok(proc_info) = Self::read_process_info(pid) {
                        processes.insert(pid, proc_info);
                    }
                }
            }
        }
        
        // Build tree
        let mut children: std::collections::HashMap<u32, Vec<u32>> = std::collections::HashMap::new();
        let mut roots = Vec::new();
        
        for (pid, info) in &processes {
            if let Some(ppid) = info.get("ppid").and_then(|v| v.as_u64()) {
                children.entry(ppid as u32).or_default().push(*pid);
            } else {
                roots.push(*pid);
            }
        }
        
        fn build_tree(
            pid: u32,
            processes: &std::collections::HashMap<u32, Value>,
            children: &std::collections::HashMap<u32, Vec<u32>>,
        ) -> Value {
            let mut node = processes.get(&pid).cloned().unwrap_or(serde_json::json!({}));
            if let Some(child_pids) = children.get(&pid) {
                let child_nodes: Vec<Value> = child_pids.iter()
                    .map(|cpid| build_tree(*cpid, processes, children))
                    .collect();
                node["children"] = serde_json::json!(child_nodes);
            }
            node
        }
        
        let tree: Vec<Value> = roots.iter()
            .map(|pid| build_tree(*pid, &processes, &children))
            .collect();
        
        Ok(result_ok(serde_json::json!({"tree": tree})))
    }

    fn read_process_info(pid: u32) -> Result<Value, String> {
        let stat_path = format!("/proc/{}/stat", pid);
        let status_path = format!("/proc/{}/status", pid);
        let cmdline_path = format!("/proc/{}/cmdline", pid);
        let exe_path = format!("/proc/{}/exe", pid);
        let cwd_path = format!("/proc/{}/cwd", pid);
        
        // Read stat
        let stat_content = fs::read_to_string(&stat_path).map_err(|e| e.to_string())?;
        let stat_parts: Vec<&str> = stat_content.split_whitespace().collect();
        
        if stat_parts.len() < 24 {
            return Err("Invalid stat format".to_string());
        }
        
        let ppid = stat_parts[3].parse::<u32>().unwrap_or(0);
        let utime = stat_parts[13].parse::<u64>().unwrap_or(0);
        let stime = stat_parts[14].parse::<u64>().unwrap_or(0);
        let vsize = stat_parts[22].parse::<u64>().unwrap_or(0);
        let rss = stat_parts[23].parse::<u64>().unwrap_or(0);
        
        // Read cmdline
        let cmdline = fs::read_to_string(&cmdline_path).unwrap_or_default();
        let cmdline: Vec<String> = cmdline.split('\0').filter(|s| !s.is_empty()).map(|s| s.to_string()).collect();
        
        // Read status for memory info
        let mut uid = 0u32;
        let mut gid = 0u32;
        let mut state = String::new();
        let mut threads = 0u32;
        
        if let Ok(status_content) = fs::read_to_string(&status_path) {
            for line in status_content.lines() {
                if line.starts_with("Uid:") {
                    let parts: Vec<&str> = line.split_whitespace().collect();
                    if parts.len() >= 2 {
                        uid = parts[1].parse().unwrap_or(0);
                    }
                } else if line.starts_with("Gid:") {
                    let parts: Vec<&str> = line.split_whitespace().collect();
                    if parts.len() >= 2 {
                        gid = parts[1].parse().unwrap_or(0);
                    }
                } else if line.starts_with("State:") {
                    state = line["State:".len()..].trim().split_whitespace().next().unwrap_or("").to_string();
                } else if line.starts_with("Threads:") {
                    let parts: Vec<&str> = line.split_whitespace().collect();
                    if parts.len() >= 2 {
                        threads = parts[1].parse().unwrap_or(0);
                    }
                }
            }
        }
        
        // Read exe link
        let exe = fs::read_link(&exe_path).ok().and_then(|p| p.to_str().map(|s| s.to_string()));
        let cwd = fs::read_link(&cwd_path).ok().and_then(|p| p.to_str().map(|s| s.to_string()));
        
        // Calculate CPU percentage (simplified)
        let cpu_percent = 0.0; // Would need two samples
        
        Ok(serde_json::json!({
            "pid": pid,
            "ppid": ppid,
            "name": cmdline.first().cloned().unwrap_or_default(),
            "cmdline": cmdline,
            "state": state,
            "uid": uid,
            "gid": gid,
            "threads": threads,
            "cpu_percent": cpu_percent,
            "memory_vsize": vsize,
            "memory_rss": rss * 4096, // pages to bytes
            "exe": exe,
            "cwd": cwd,
        }))
    }
}