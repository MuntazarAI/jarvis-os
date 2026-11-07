//! Storage information module.

use crate::modules::{ModuleHandler, result_ok};
use async_trait::async_trait;
use serde_json::Value;
use std::fs;

pub struct StorageModule;

#[async_trait]
impl ModuleHandler for StorageModule {
    async fn handle(&self, method: &str, _params: &Value) -> Result<Value, String> {
        match method {
            "info" => self.storage_info().await,
            "usage" => self.storage_usage().await,
            "devices" => self.storage_devices().await,
            _ => Err(format!("Unknown storage method: {}", method)),
        }
    }
}

impl StorageModule {
    async fn storage_info(&self) -> Result<Value, String> {
        let mounts = Self::read_mounts()?;
        let mut filesystems = Vec::new();
        
        for mount in mounts {
            if let Ok(usage) = Self::get_disk_usage(&mount.mount_point) {
                filesystems.push(usage);
            }
        }
        
        Ok(result_ok(serde_json::json!({"filesystems": filesystems})))
    }

    async fn storage_usage(&self) -> Result<Value, String> {
        let mounts = Self::read_mounts()?;
        let mut total_bytes = 0u64;
        let mut used_bytes = 0u64;
        let mut free_bytes = 0u64;
        
        for mount in mounts {
            if let Ok(usage) = Self::get_disk_usage(&mount.mount_point) {
                total_bytes += usage.get("total_bytes").and_then(|v| v.as_u64()).unwrap_or(0);
                used_bytes += usage.get("used_bytes").and_then(|v| v.as_u64()).unwrap_or(0);
                free_bytes += usage.get("free_bytes").and_then(|v| v.as_u64()).unwrap_or(0);
            }
        }
        
        let usage_percent = if total_bytes > 0 {
            (used_bytes as f64 / total_bytes as f64) * 100.0
        } else {
            0.0
        };
        
        Ok(result_ok(serde_json::json!({
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "usage_percent": usage_percent,
        })))
    }

    async fn storage_devices(&self) -> Result<Value, String> {
        let mut devices = Vec::new();
        
        if let Ok(entries) = fs::read_dir("/sys/block") {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if name.starts_with("loop") || name.starts_with("ram") {
                    continue;
                }
                
                let mut device = serde_json::json!({"name": name});
                
                // Size
                if let Ok(size_str) = fs::read_to_string(entry.path().join("size")) {
                    if let Ok(sectors) = size_str.trim().parse::<u64>() {
                        device["size_bytes"] = serde_json::json!(sectors * 512);
                    }
                }
                
                // Model
                if let Ok(model) = fs::read_to_string(entry.path().join("device/model")) {
                    device["model"] = serde_json::json!(model.trim());
                }
                
                // Vendor
                if let Ok(vendor) = fs::read_to_string(entry.path().join("device/vendor")) {
                    device["vendor"] = serde_json::json!(vendor.trim());
                }
                
                // Removable
                if let Ok(removable) = fs::read_to_string(entry.path().join("removable")) {
                    device["removable"] = serde_json::json!(removable.trim() == "1");
                }
                
                // Rotational
                if let Ok(rotational) = fs::read_to_string(entry.path().join("queue/rotational")) {
                    device["rotational"] = serde_json::json!(rotational.trim() == "1");
                }
                
                // Partitions
                let mut partitions = Vec::new();
                if let Ok(part_entries) = fs::read_dir(entry.path()) {
                    for part_entry in part_entries.flatten() {
                        let part_name = part_entry.file_name().to_string_lossy().to_string();
                        if part_name.starts_with(&name) && part_name != name {
                            let mut partition = serde_json::json!({"name": part_name});
                            
                            if let Ok(size_str) = fs::read_to_string(part_entry.path().join("size")) {
                                if let Ok(sectors) = size_str.trim().parse::<u64>() {
                                    partition["size_bytes"] = serde_json::json!(sectors * 512);
                                }
                            }
                            
                            if let Ok(start_str) = fs::read_to_string(part_entry.path().join("start")) {
                                if let Ok(start) = start_str.trim().parse::<u64>() {
                                    partition["start_sector"] = serde_json::json!(start);
                                }
                            }
                            
                            partitions.push(partition);
                        }
                    }
                }
                device["partitions"] = serde_json::json!(partitions);
                
                devices.push(device);
            }
        }
        
        Ok(result_ok(serde_json::json!({"devices": devices})))
    }

    #[derive(Debug)]
    struct MountInfo {
        device: String,
        mount_point: String,
        fstype: String,
    }

    fn read_mounts() -> Result<Vec<MountInfo>, String> {
        let content = fs::read_to_string("/proc/mounts").map_err(|e| e.to_string())?;
        let mut mounts = Vec::new();
        
        for line in content.lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 3 {
                let device = parts[0].to_string();
                let mount_point = parts[1].to_string();
                let fstype = parts[2].to_string();
                
                // Skip virtual filesystems
                if !["proc", "sysfs", "devtmpfs", "devpts", "tmpfs", "cgroup", "cgroup2", "pstore", "efivarfs", "mqueue", "hugetlbfs", "debugfs", "tracefs", "configfs", "fuse.gvfsd-fuse", "fusectl", "binfmt_misc", "autofs", "rpc_pipefs", "nfsd", "overlay"].contains(&fstype.as_str()) {
                    mounts.push(MountInfo { device, mount_point, fstype });
                }
            }
        }
        
        Ok(mounts)
    }

    fn get_disk_usage(path: &str) -> Result<Value, String> {
        let stat = std::fs::metadata(path).map_err(|e| e.to_string())?;
        
        // Use statvfs via a simple approach
        use std::os::unix::fs::MetadataExt;
        let dev = stat.dev();
        
        // Read from /proc/self/mountinfo to find the mount
        let content = fs::read_to_string("/proc/self/mountinfo").map_err(|e| e.to_string())?;
        let mut mount_id = 0u64;
        
        for line in content.lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 5 && parts[4] == path {
                mount_id = parts[0].parse().unwrap_or(0);
                break;
            }
        }
        
        // Use statfs via std::fs
        let mut statfs = libc::statfs {
            f_type: 0,
            f_bsize: 0,
            f_blocks: 0,
            f_bfree: 0,
            f_bavail: 0,
            f_files: 0,
            f_ffree: 0,
            f_fsid: libc::fsid_t { __val: [0, 0] },
            f_namelen: 0,
            f_frsize: 0,
            f_flags: 0,
            f_spare: [0; 4],
        };
        
        let c_path = std::ffi::CString::new(path).map_err(|e| e.to_string())?;
        let result = unsafe { libc::statfs(c_path.as_ptr(), &mut statfs) };
        
        if result != 0 {
            return Err("statfs failed".to_string());
        }
        
        let block_size = statfs.f_bsize as u64;
        let total_blocks = statfs.f_blocks as u64;
        let free_blocks = statfs.f_bfree as u64;
        let avail_blocks = statfs.f_bavail as u64;
        
        let total_bytes = total_blocks * block_size;
        let free_bytes = free_blocks * block_size;
        let used_bytes = total_bytes - free_bytes;
        let available_bytes = avail_blocks * block_size;
        
        Ok(serde_json::json!({
            "mount_point": path,
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "available_bytes": available_bytes,
            "usage_percent": if total_bytes > 0 { (used_bytes as f64 / total_bytes as f64) * 100.0 } else { 0.0 },
        }))
    }
}