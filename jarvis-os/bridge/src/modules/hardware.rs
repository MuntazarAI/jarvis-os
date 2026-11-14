//! Hardware information module.

use crate::modules::{ModuleHandler, result_ok};
use async_trait::async_trait;
use serde_json::Value;
use std::fs;

pub struct HardwareModule;

#[async_trait]
impl ModuleHandler for HardwareModule {
    async fn handle(&self, method: &str, _params: &Value) -> Result<Value, String> {
        match method {
            "computer" => self.computer_info().await,
            "bios" => self.bios_info().await,
            "chassis" => self.chassis_info().await,
            "motherboard" => self.motherboard_info().await,
            _ => Err(format!("Unknown hardware method: {}", method)),
        }
    }
}

impl HardwareModule {
    async fn computer_info(&self) -> Result<Value, String> {
        let mut info = serde_json::Map::new();
        
        // Read from /sys/class/dmi/id
        let dmi_path = "/sys/class/dmi/id";
        let fields = [
            ("vendor", "sys_vendor"),
            ("product_name", "product_name"),
            ("version", "product_version"),
            ("serial", "product_serial"),
            ("uuid", "product_uuid"),
            ("family", "product_family"),
            ("sku", "product_sku"),
        ];
        
        for (key, file) in fields {
            if let Ok(val) = fs::read_to_string(format!("{}/{}", dmi_path, file)) {
                info.insert(key.to_string(), Value::String(val.trim().to_string()));
            }
        }
        
        Ok(result_ok(Value::Object(info)))
    }

    async fn bios_info(&self) -> Result<Value, String> {
        let mut info = serde_json::Map::new();
        
        let dmi_path = "/sys/class/dmi/id";
        let fields = [
            ("vendor", "bios_vendor"),
            ("version", "bios_version"),
            ("date", "bios_date"),
            ("release", "bios_release"),
        ];
        
        for (key, file) in fields {
            if let Ok(val) = fs::read_to_string(format!("{}/{}", dmi_path, file)) {
                info.insert(key.to_string(), Value::String(val.trim().to_string()));
            }
        }
        
        Ok(result_ok(Value::Object(info)))
    }

    async fn chassis_info(&self) -> Result<Value, String> {
        let mut info = serde_json::Map::new();
        
        let dmi_path = "/sys/class/dmi/id";
        let fields = [
            ("vendor", "chassis_vendor"),
            ("type", "chassis_type"),
            ("version", "chassis_version"),
            ("serial", "chassis_serial"),
            ("asset_tag", "chassis_asset_tag"),
        ];
        
        for (key, file) in fields {
            if let Ok(val) = fs::read_to_string(format!("{}/{}", dmi_path, file)) {
                info.insert(key.to_string(), Value::String(val.trim().to_string()));
            }
        }
        
        // Map chassis type
        if let Some(ty) = info.get("type").and_then(|v| v.as_str()) {
            let chassis_type = match ty {
                "1" => "Other",
                "2" => "Unknown",
                "3" => "Desktop",
                "4" => "Low Profile Desktop",
                "5" => "Pizza Box",
                "6" => "Mini Tower",
                "7" => "Tower",
                "8" => "Portable",
                "9" => "Laptop",
                "10" => "Notebook",
                "11" => "Hand Held",
                "12" => "Docking Station",
                "13" => "All in One",
                "14" => "Sub Notebook",
                "15" => "Space-Saving",
                "16" => "Lunch Box",
                "17" => "Main System Chassis",
                "18" => "Expansion Chassis",
                "19" => "Sub Chassis",
                "20" => "Bus Expansion Chassis",
                "21" => "Peripheral Chassis",
                "22" => "Storage Chassis",
                "23" => "Rack Mount Chassis",
                "24" => "Sealed-Case PC",
                _ => "Unknown",
            };
            info.insert("type_description".to_string(), Value::String(chassis_type.to_string()));
        }
        
        Ok(result_ok(Value::Object(info)))
    }

    async fn motherboard_info(&self) -> Result<Value, String> {
        let mut info = serde_json::Map::new();
        
        let dmi_path = "/sys/class/dmi/id";
        let fields = [
            ("vendor", "board_vendor"),
            ("name", "board_name"),
            ("version", "board_version"),
            ("serial", "board_serial"),
            ("asset_tag", "board_asset_tag"),
        ];
        
        for (key, file) in fields {
            if let Ok(val) = fs::read_to_string(format!("{}/{}", dmi_path, file)) {
                info.insert(key.to_string(), Value::String(val.trim().to_string()));
            }
        }
        
        Ok(result_ok(Value::Object(info)))
    }
}