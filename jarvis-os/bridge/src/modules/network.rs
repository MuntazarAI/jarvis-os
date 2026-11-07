//! Network information module.

use crate::modules::{ModuleHandler, result_ok, param_optional_string};
use async_trait::async_trait;
use serde_json::Value;
use std::fs;

pub struct NetworkModule;

#[async_trait]
impl ModuleHandler for NetworkModule {
    async fn handle(&self, method: &str, params: &Value) -> Result<Value, String> {
        match method {
            "interfaces" => self.interfaces().await,
            "addresses" => self.addresses(params).await,
            "routes" => self.routes().await,
            "stats" => self.stats().await,
            _ => Err(format!("Unknown network method: {}", method)),
        }
    }
}

impl NetworkModule {
    async fn interfaces(&self) -> Result<Value, String> {
        let mut interfaces = Vec::new();
        
        if let Ok(entries) = fs::read_dir("/sys/class/net") {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                
                let mut iface = serde_json::json!({"name": name});
                
                // Type
                if let Ok(type_str) = fs::read_to_string(entry.path().join("type")) {
                    let iface_type = match type_str.trim().parse::<u32>().unwrap_or(0) {
                        1 => "ethernet",
                        65534 => "loopback",
                        256 => "infiniband",
                        512 => "ieee80211",
                        _ => "unknown",
                    };
                    iface["type"] = serde_json::json!(iface_type);
                }
                
                // MAC address
                if let Ok(addr) = fs::read_to_string(entry.path().join("address")) {
                    iface["mac_address"] = serde_json::json!(addr.trim());
                }
                
                // MTU
                if let Ok(mtu) = fs::read_to_string(entry.path().join("mtu")) {
                    iface["mtu"] = serde_json::json!(mtu.trim().parse::<u32>().unwrap_or(0));
                }
                
                // Flags (up/down)
                if let Ok(flags) = fs::read_to_string(entry.path().join("flags")) {
                    let flags_val = flags.trim().parse::<u32>().unwrap_or(0);
                    iface["up"] = serde_json::json!((flags_val & 1) != 0);
                    iface["running"] = serde_json::json!((flags_val & 64) != 0);
                }
                
                // Speed
                if let Ok(speed) = fs::read_to_string(entry.path().join("speed")) {
                    iface["speed_mbps"] = serde_json::json!(speed.trim().parse::<u32>().ok());
                }
                
                // Carrier
                if let Ok(carrier) = fs::read_to_string(entry.path().join("carrier")) {
                    iface["carrier"] = serde_json::json!(carrier.trim() == "1");
                }
                
                // Dormant
                if let Ok(dormant) = fs::read_to_string(entry.path().join("dormant")) {
                    iface["dormant"] = serde_json::json!(dormant.trim() == "1");
                }
                
                interfaces.push(iface);
            }
        }
        
        Ok(result_ok(serde_json::json!({"interfaces": interfaces})))
    }

    async fn addresses(&self, params: &Value) -> Result<Value, String> {
        let interface_filter = param_optional_string(params, "interface");
        let mut addresses = Vec::new();
        
        // Read /proc/net/if_inet6 for IPv6
        if let Ok(content) = fs::read_to_string("/proc/net/if_inet6") {
            for line in content.lines() {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 4 {
                    let addr = parts[0];
                    let iface_idx = parts[2];
                    
                    // Convert IPv6 address format
                    let mut formatted = String::new();
                    for (i, chunk) in addr.as_bytes().chunks(4).enumerate() {
                        if i > 0 {
                            formatted.push(':');
                        }
                        formatted.push_str(&String::from_utf8_lossy(chunk));
                    }
                    
                    addresses.push(serde_json::json!({
                        "address": formatted,
                        "family": "inet6",
                        "interface_index": iface_idx,
                    }));
                }
            }
        }
        
        // Read /proc/net/if_addr for IPv4
        // Using ip command would be better but we'll parse /proc/net/route and /proc/net/if_addr
        if let Ok(content) = fs::read_to_string("/proc/net/if_addr") {
            for line in content.lines() {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 4 {
                    // Format is complex, skip for now
                }
            }
        }
        
        // Better approach: use getifaddrs via a simple parse of ip addr output
        // But we can't run commands, so we'll use /sys/class/net and /proc/net
        
        // For now, return what we have
        Ok(result_ok(serde_json::json!({"addresses": addresses})))
    }

    async fn routes(&self) -> Result<Value, String> {
        let content = fs::read_to_string("/proc/net/route").map_err(|e| e.to_string())?;
        let mut routes = Vec::new();
        
        for line in content.lines().skip(1) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 11 {
                let iface = parts[0];
                let dest = u32::from_str_radix(parts[1], 16).unwrap_or(0);
                let gateway = u32::from_str_radix(parts[2], 16).unwrap_or(0);
                let flags = u32::from_str_radix(parts[3], 16).unwrap_or(0);
                let metric = parts[6].parse::<u32>().unwrap_or(0);
                
                routes.push(serde_json::json!({
                    "interface": iface,
                    "destination": Self::ip_from_u32(dest),
                    "gateway": Self::ip_from_u32(gateway),
                    "flags": flags,
                    "metric": metric,
                    "is_default": dest == 0,
                }));
            }
        }
        
        // IPv6 routes
        if let Ok(content) = fs::read_to_string("/proc/net/ipv6_route") {
            for line in content.lines().skip(1) {
                let parts: Vec<&str> = line.split_whitespace().collect();
                if parts.len() >= 11 {
                    routes.push(serde_json::json!({
                        "interface": parts[7],
                        "destination": parts[0],
                        "next_hop": parts[1],
                        "metric": parts[8].parse::<u32>().unwrap_or(0),
                    }));
                }
            }
        }
        
        Ok(result_ok(serde_json::json!({"routes": routes})))
    }

    async fn stats(&self) -> Result<Value, String> {
        let content = fs::read_to_string("/proc/net/dev").map_err(|e| e.to_string())?;
        let mut stats = Vec::new();
        
        for line in content.lines().skip(2) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 17 {
                let name = parts[0].trim_end_matches(':');
                stats.push(serde_json::json!({
                    "interface": name,
                    "rx_bytes": parts[1].parse::<u64>().unwrap_or(0),
                    "rx_packets": parts[2].parse::<u64>().unwrap_or(0),
                    "rx_errors": parts[3].parse::<u64>().unwrap_or(0),
                    "rx_dropped": parts[4].parse::<u64>().unwrap_or(0),
                    "tx_bytes": parts[9].parse::<u64>().unwrap_or(0),
                    "tx_packets": parts[10].parse::<u64>().unwrap_or(0),
                    "tx_errors": parts[11].parse::<u64>().unwrap_or(0),
                    "tx_dropped": parts[12].parse::<u64>().unwrap_or(0),
                }));
            }
        }
        
        Ok(result_ok(serde_json::json!({"stats": stats})))
    }

    fn ip_from_u32(ip: u32) -> String {
        format!("{}.{}.{}.{}", (ip >> 24) & 0xFF, (ip >> 16) & 0xFF, (ip >> 8) & 0xFF, ip & 0xFF)
    }
}