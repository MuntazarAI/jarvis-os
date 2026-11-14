//! CPU information module.

use crate::modules::{ModuleHandler, result_ok, param_optional_u64};
use async_trait::async_trait;
use serde_json::Value;
use std::fs;

pub struct CpuModule;

#[async_trait]
impl ModuleHandler for CpuModule {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "info" => self.cpu_info().await,
            "usage" => self.cpu_usage(params).await,
            "temperature" => self.cpu_temperature().await,
            "frequency" => self.cpu_frequency().await,
            _ => Err(format!("Unknown cpu method: {}", method)),
        }
    }
}

impl CpuModule {
    async fn cpu_info(&self) -> Result<Value, String> {
        let content = fs::read_to_string("/proc/cpuinfo").map_err(|e| e.to_string())?;
        let mut cores = 0;
        let mut model_name = String::new();
        let mut vendor = String::new();
        let mut cache_size = String::new();
        
        for line in content.lines() {
            if line.starts_with("processor") {
                cores += 1;
            } else if line.starts_with("model name") && model_name.is_empty() {
                model_name = line.split(':').nth(1).unwrap_or("").trim().to_string();
            } else if line.starts_with("vendor_id") && vendor.is_empty() {
                vendor = line.split(':').nth(1).unwrap_or("").trim().to_string();
            } else if line.starts_with("cache size") && cache_size.is_empty() {
                cache_size = line.split(':').nth(1).unwrap_or("").trim().to_string();
            }
        }
        
        Ok(result_ok(serde_json::json!({
            "cores": cores,
            "model_name": model_name,
            "vendor": vendor,
            "cache_size": cache_size,
        })))
    }

    async fn cpu_usage(&self, params: &Value) -> Result<Value, String> {
        let interval = param_optional_u64(params, "interval").unwrap_or(1000) as u64;
        
        // Read /proc/stat twice with a small delay to calculate usage
        let stat1 = Self::read_cpu_stat()?;
        tokio::time::sleep(std::time::Duration::from_millis(interval)).await;
        let stat2 = Self::read_cpu_stat()?;
        
        let mut usages = Vec::new();
        for (cpu1, cpu2) in stat1.iter().zip(stat2.iter()) {
            let total1: u64 = cpu1.iter().sum();
            let total2: u64 = cpu2.iter().sum();
            let idle1 = cpu1[3];
            let idle2 = cpu2[3];
            
            let total_diff = total2 - total1;
            let idle_diff = idle2 - idle1;
            
            let usage = if total_diff > 0 {
                100.0 * (total_diff - idle_diff) as f64 / total_diff as f64
            } else {
                0.0
            };
            usages.push(usage);
        }
        
        Ok(result_ok(serde_json::json!({
            "per_core": usages,
            "average": if usages.is_empty() { 0.0 } else { usages.iter().sum::<f64>() / usages.len() as f64 },
        })))
    }

    async fn cpu_temperature(&self) -> Result<Value, String> {
        let mut temps = Vec::new();
        
        // Try thermal zones
        if let Ok(entries) = fs::read_dir("/sys/class/thermal") {
            for entry in entries.flatten() {
                if let Ok(name) = fs::read_to_string(entry.path().join("type")) {
                    if name.trim().starts_with("cpu") || name.trim().starts_with("core") {
                        if let Ok(temp_str) = fs::read_to_string(entry.path().join("temp")) {
                            if let Ok(temp) = temp_str.trim().parse::<u64>() {
                                temps.push(serde_json::json!({
                                    "zone": name.trim(),
                                    "temperature_celsius": temp as f64 / 1000.0,
                                }));
                            }
                        }
                    }
                }
            }
        }
        
        // Try hwmon
        if let Ok(entries) = fs::read_dir("/sys/class/hwmon") {
            for entry in entries.flatten() {
                if let Ok(name) = fs::read_to_string(entry.path().join("name")) {
                    if name.trim().to_lowercase().contains("cpu") || name.trim().to_lowercase().contains("core") || name.trim().to_lowercase().contains("k10temp") {
                        if let Ok(temp_files) = fs::read_dir(entry.path()) {
                            for temp_file in temp_files.flatten() {
                                if temp_file.file_name().to_string_lossy().starts_with("temp") && temp_file.file_name().to_string_lossy().ends_with("_input") {
                                    if let Ok(temp_str) = fs::read_to_string(temp_file.path()) {
                                        if let Ok(temp) = temp_str.trim().parse::<u64>() {
                                            temps.push(serde_json::json!({
                                                "sensor": name.trim(),
                                                "temperature_celsius": temp as f64 / 1000.0,
                                            }));
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        Ok(result_ok(serde_json::json!({"temperatures": temps})))
    }

    async fn cpu_frequency(&self) -> Result<Value, String> {
        let mut freqs = Vec::new();
        
        if let Ok(entries) = fs::read_dir("/sys/devices/system/cpu") {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if name.starts_with("cpu") && name[3..].chars().all(|c| c.is_ascii_digit()) {
                    let base_path = entry.path();
                    let mut cpu_freq = serde_json::json!({"core": &name[3..]});
                    
                    if let Ok(current) = fs::read_to_string(base_path.join("cpufreq/scaling_cur_freq")) {
                        if let Ok(val) = current.trim().parse::<u64>() {
                            cpu_freq["current_mhz"] = serde_json::json!(val / 1000);
                        }
                    }
                    if let Ok(min) = fs::read_to_string(base_path.join("cpufreq/scaling_min_freq")) {
                        if let Ok(val) = min.trim().parse::<u64>() {
                            cpu_freq["min_mhz"] = serde_json::json!(val / 1000);
                        }
                    }
                    if let Ok(max) = fs::read_to_string(base_path.join("cpufreq/scaling_max_freq")) {
                        if let Ok(val) = max.trim().parse::<u64>() {
                            cpu_freq["max_mhz"] = serde_json::json!(val / 1000);
                        }
                    }
                    if let Ok(governor) = fs::read_to_string(base_path.join("cpufreq/scaling_governor")) {
                        cpu_freq["governor"] = serde_json::json!(governor.trim());
                    }
                    
                    freqs.push(cpu_freq);
                }
            }
        }
        
        Ok(result_ok(serde_json::json!({"frequencies": freqs})))
    }

    fn read_cpu_stat() -> Result<Vec<Vec<u64>>, String> {
        let content = fs::read_to_string("/proc/stat").map_err(|e| e.to_string())?;
        let mut result = Vec::new();
        
        for line in content.lines() {
            if line.starts_with("cpu") {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 8 {
                    let values: Vec<u64> = parts[1..].iter()
                        .filter_map(|s| s.parse().ok())
                        .collect();
                    if values.len() >= 8 {
                        result.push(values);
                    }
                }
            }
        }
        
        Ok(result)
    }
}