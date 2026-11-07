//! Hardware Abstraction Layer for JARVIS-OS
//!
//! Provides unified hardware detection, monitoring, and management

use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;
use tokio::fs;
use tokio::process::Command;

/// GPU Information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuInfo {
    pub vendor: String,
    pub model: String,
    pub driver_version: String,
    pub compute_api: Vec<String>, // CUDA, ROCm, OpenCL, Vulkan
    pub memory_total_mb: u64,
    pub memory_free_mb: u64,
    pub utilization_percent: f32,
    pub temperature_c: Option<f32>,
    pub power_watts: Option<f32>,
    pub pcie_link: String,
}

/// CPU Information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CpuInfo {
    pub vendor: String,
    pub model: String,
    pub cores: u32,
    pub threads: u32,
    pub base_freq_mhz: u32,
    pub max_freq_mhz: u32,
    pub cache_l1_kb: u32,
    pub cache_l2_kb: u32,
    pub cache_l3_kb: u32,
    pub features: Vec<String>, // AVX, AVX2, AVX-512, SSE, etc.
    pub microcode_version: String,
    pub temperature_c: Option<f32>,
    pub power_watts: Option<f32>,
}

/// Memory Information
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryInfo {
    pub total_gb: f32,
    pub available_gb: f32,
    pub used_gb: f32,
    pub speed_mhz: u32,
    pub type_: String, // DDR4, DDR5, LPDDR5
    pub channels: u32,
    pub ecc: bool,
    pub modules: Vec<MemoryModule>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MemoryModule {
    pub slot: String,
    pub size_gb: u32,
    pub vendor: String,
    pub part_number: String,
    pub serial: String,
    pub speed_mhz: u32,
}

/// Storage Device
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageDevice {
    pub name: String,
    pub path: String,
    pub type_: StorageType,
    pub size_bytes: u64,
    pub model: String,
    pub serial: String,
    pub firmware: String,
    pub health_percent: u8,
    pub temperature_c: Option<f32>,
    pub smart_data: HashMap<String, String>,
    pub partitions: Vec<Partition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum StorageType {
    NVMe,
    SATA,
    SCSI,
    USB,
    eMMC,
    Loop,
    Ram,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Partition {
    pub name: String,
    pub path: String,
    pub start_sector: u64,
    pub size_sectors: u64,
    pub fs_type: Option<String>,
    pub mount_point: Option<String>,
    pub uuid: Option<String>,
}

/// Network Interface
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkInterface {
    pub name: String,
    pub index: u32,
    pub mac: String,
    pub mtu: u32,
    pub speed_mbps: Option<u32>,
    pub duplex: Option<String>,
    pub addresses: Vec<IpAddress>,
    pub stats: InterfaceStats,
    pub driver: String,
    pub firmware: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IpAddress {
    pub family: String, // inet, inet6
    pub address: String,
    pub prefix_len: u8,
    pub scope: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InterfaceStats {
    pub rx_bytes: u64,
    pub rx_packets: u64,
    pub rx_errors: u64,
    pub rx_dropped: u64,
    pub tx_bytes: u64,
    pub tx_packets: u64,
    pub tx_errors: u64,
    pub tx_dropped: u64,
}

/// System Hardware Summary
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardwareSummary {
    pub hostname: String,
    pub bios: BiosInfo,
    pub chassis: ChassisInfo,
    pub motherboard: MotherboardInfo,
    pub cpu: CpuInfo,
    pub gpus: Vec<GpuInfo>,
    pub memory: MemoryInfo,
    pub storage: Vec<StorageDevice>,
    pub network: Vec<NetworkInterface>,
    pub sensors: Vec<SensorReading>,
    pub pci_devices: Vec<PciDevice>,
    pub usb_devices: Vec<UsbDevice>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BiosInfo {
    pub vendor: String,
    pub version: String,
    pub date: String,
    pub revision: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChassisInfo {
    pub vendor: String,
    pub type_: String,
    pub version: String,
    pub serial: String,
    pub asset_tag: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MotherboardInfo {
    pub vendor: String,
    pub name: String,
    pub version: String,
    pub serial: String,
    pub asset_tag: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SensorReading {
    pub name: String,
    pub type_: SensorType,
    pub value: f32,
    pub unit: String,
    pub min: Option<f32>,
    pub max: Option<f32>,
    pub critical: Option<f32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SensorType {
    Temperature,
    Voltage,
    Current,
    Power,
    Fan,
    Humidity,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PciDevice {
    pub address: String,
    pub class: String,
    pub vendor_id: String,
    pub device_id: String,
    pub vendor_name: String,
    pub device_name: String,
    pub driver: Option<String>,
    pub numa_node: Option<i32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsbDevice {
    pub bus: u32,
    pub device: u32,
    pub vendor_id: String,
    pub product_id: String,
    pub vendor_name: String,
    pub product_name: String,
    pub speed: String,
    pub driver: Option<String>,
}

/// Hardware Manager
pub struct HardwareManager {
    cache: std::sync::Mutex<Option<HardwareSummary>>,
}

impl HardwareManager {
    pub fn new() -> Self {
        Self {
            cache: std::sync::Mutex::new(None),
        }
    }
    
    pub async fn discover(&self) -> Result<HardwareSummary> {
        let mut summary = HardwareSummary {
            hostname: self.get_hostname().await?,
            bios: self.get_bios_info().await?,
            chassis: self.get_chassis_info().await?,
            motherboard: self.get_motherboard_info().await?,
            cpu: self.get_cpu_info().await?,
            gpus: self.get_gpu_info().await?,
            memory: self.get_memory_info().await?,
            storage: self.get_storage_devices().await?,
            network: self.get_network_interfaces().await?,
            sensors: self.get_sensor_readings().await?,
            pci_devices: self.get_pci_devices().await?,
            usb_devices: self.get_usb_devices().await?,
        };
        
        *self.cache.lock().unwrap() = Some(summary.clone());
        Ok(summary)
    }
    
    pub async fn get_cached(&self) -> Option<HardwareSummary> {
        self.cache.lock().unwrap().clone()
    }
    
    // --- Discovery Methods ---
    
    async fn get_hostname(&self) -> Result<String> {
        Ok(fs::read_to_string("/etc/hostname").await?.trim().to_string())
    }
    
    async fn get_bios_info(&self) -> Result<BiosInfo> {
        let vendor = fs::read_to_string("/sys/class/dmi/id/bios_vendor").await.unwrap_or_default().trim().to_string();
        let version = fs::read_to_string("/sys/class/dmi/id/bios_version").await.unwrap_or_default().trim().to_string();
        let date = fs::read_to_string("/sys/class/dmi/id/bios_date").await.unwrap_or_default().trim().to_string();
        let revision = fs::read_to_string("/sys/class/dmi/id/bios_revision").await.unwrap_or_default().trim().to_string();
        Ok(BiosInfo { vendor, version, date, revision })
    }
    
    async fn get_chassis_info(&self) -> Result<ChassisInfo> {
        let vendor = fs::read_to_string("/sys/class/dmi/id/chassis_vendor").await.unwrap_or_default().trim().to_string();
        let type_ = fs::read_to_string("/sys/class/dmi/id/chassis_type").await.unwrap_or_default().trim().to_string();
        let version = fs::read_to_string("/sys/class/dmi/id/chassis_version").await.unwrap_or_default().trim().to_string();
        let serial = fs::read_to_string("/sys/class/dmi/id/chassis_serial").await.unwrap_or_default().trim().to_string();
        let asset_tag = fs::read_to_string("/sys/class/dmi/id/chassis_asset_tag").await.unwrap_or_default().trim().to_string();
        Ok(ChassisInfo { vendor, type_, version, serial, asset_tag })
    }
    
    async fn get_motherboard_info(&self) -> Result<MotherboardInfo> {
        let vendor = fs::read_to_string("/sys/class/dmi/id/board_vendor").await.unwrap_or_default().trim().to_string();
        let name = fs::read_to_string("/sys/class/dmi/id/board_name").await.unwrap_or_default().trim().to_string();
        let version = fs::read_to_string("/sys/class/dmi/id/board_version").await.unwrap_or_default().trim().to_string();
        let serial = fs::read_to_string("/sys/class/dmi/id/board_serial").await.unwrap_or_default().trim().to_string();
        let asset_tag = fs::read_to_string("/sys/class/dmi/id/board_asset_tag").await.unwrap_or_default().trim().to_string();
        Ok(MotherboardInfo { vendor, name, version, serial, asset_tag })
    }
    
    async fn get_cpu_info(&self) -> Result<CpuInfo> {
        let content = fs::read_to_string("/proc/cpuinfo").await?;
        let mut vendor = String::new();
        let mut model = String::new();
        let mut cores = 0;
        let mut threads = 0;
        let mut features = Vec::new();
        let mut microcode = String::new();
        
        for line in content.lines() {
            if line.starts_with("vendor_id") && vendor.is_empty() {
                vendor = line.split(':').nth(1).unwrap_or("").trim().to_string();
            } else if line.starts_with("model name") && model.is_empty() {
                model = line.split(':').nth(1).unwrap_or("").trim().to_string();
            } else if line.starts_with("cpu cores") {
                cores = line.split(':').nth(1).unwrap_or("").trim().parse().unwrap_or(0);
            } else if line.starts_with("siblings") {
                threads = line.split(':').nth(1).unwrap_or("").trim().parse().unwrap_or(0);
            } else if line.starts_with("flags") && features.is_empty() {
                features = line.split(':').nth(1).unwrap_or("").split_whitespace().map(|s| s.to_string()).collect();
            } else if line.starts_with("microcode") && microcode.is_empty() {
                microcode = line.split(':').nth(1).unwrap_or("").trim().to_string();
            }
        }
        
        // Get frequency info
        let base_freq = fs::read_to_string("/sys/devices/system/cpu/cpu0/cpufreq/base_frequency").await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0) / 1000;
        let max_freq = fs::read_to_string("/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq").await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0) / 1000;
        
        // Cache info
        let l1 = fs::read_to_string("/sys/devices/system/cpu/cpu0/cache/index0/size").await.unwrap_or("0K".to_string());
        let l2 = fs::read_to_string("/sys/devices/system/cpu/cpu0/cache/index1/size").await.unwrap_or("0K".to_string());
        let l3 = fs::read_to_string("/sys/devices/system/cpu/cpu0/cache/index2/size").await.unwrap_or("0K".to_string());
        
        Ok(CpuInfo {
            vendor,
            model,
            cores,
            threads,
            base_freq_mhz: base_freq,
            max_freq_mhz: max_freq,
            cache_l1_kb: parse_size_kb(&l1),
            cache_l2_kb: parse_size_kb(&l2),
            cache_l3_kb: parse_size_kb(&l3),
            features,
            microcode_version: microcode,
            temperature_c: None,
            power_watts: None,
        })
    }
    
    async fn get_gpu_info(&self) -> Result<Vec<GpuInfo>> {
        let mut gpus = Vec::new();
        
        // NVIDIA via nvidia-smi
        if let Ok(output) = Command::new("nvidia-smi")
            .args(["--query-gpu=name,driver_version,memory.total,memory.free,utilization.gpu,temperature.gpu,power.draw,pcie.link.gen.current", "--format=csv,noheader,nounits"])
            .output()
            .await
        {
            for line in String::from_utf8_lossy(&output.stdout).lines() {
                let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
                if parts.len() >= 8 {
                    gpus.push(GpuInfo {
                        vendor: "NVIDIA".to_string(),
                        model: parts[0].to_string(),
                        driver_version: parts[1].to_string(),
                        compute_api: vec!["CUDA".to_string(), "OpenCL".to_string(), "Vulkan".to_string()],
                        memory_total_mb: parts[2].parse().unwrap_or(0),
                        memory_free_mb: parts[3].parse().unwrap_or(0),
                        utilization_percent: parts[4].parse().unwrap_or(0.0),
                        temperature_c: Some(parts[5].parse().unwrap_or(0.0)),
                        power_watts: Some(parts[6].parse().unwrap_or(0.0)),
                        pcie_link: format!("Gen {}", parts[7]),
                    });
                }
            }
        }
        
        // AMD via rocm-smi
        if let Ok(output) = Command::new("rocm-smi")
            .args(["--showproductname", "--showdriverversion", "--showmeminfo", "vram", "--showuse", "--showtemp", "--showpower", "--showpciereplay"])
            .output()
            .await
        {
            // Parse rocm-smi output
            // Simplified - real implementation would parse properly
        }
        
        // Intel via intel_gpu_top or sysfs
        
        Ok(gpus)
    }
    
    async fn get_memory_info(&self) -> Result<MemoryInfo> {
        let meminfo = fs::read_to_string("/proc/meminfo").await?;
        let mut total_kb = 0;
        let mut available_kb = 0;
        
        for line in meminfo.lines() {
            if line.starts_with("MemTotal:") {
                total_kb = line.split_whitespace().nth(1).unwrap_or("0").parse().unwrap_or(0);
            } else if line.starts_with("MemAvailable:") {
                available_kb = line.split_whitespace().nth(1).unwrap_or("0").parse().unwrap_or(0);
            }
        }
        
        // Get DIMM info from dmidecode
        let modules = self.get_memory_modules().await?;
        let speed = if !modules.is_empty() { modules[0].speed_mhz } else { 0 };
        let type_ = if !modules.is_empty() { "DDR4".to_string() } else { "Unknown".to_string() };
        
        Ok(MemoryInfo {
            total_gb: total_kb as f32 / 1024.0 / 1024.0,
            available_gb: available_kb as f32 / 1024.0 / 1024.0,
            used_gb: (total_kb - available_kb) as f32 / 1024.0 / 1024.0,
            speed_mhz: speed,
            type_,
            channels: modules.len() as u32,
            ecc: false, // Would need dmidecode to check
            modules,
        })
    }
    
    async fn get_memory_modules(&self) -> Result<Vec<MemoryModule>> {
        // Use dmidecode -t memory
        let output = Command::new("dmidecode").arg("-t").arg("memory").output().await?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        // Parse dmidecode output
        // Simplified - return empty for now
        Ok(Vec::new())
    }
    
    async fn get_storage_devices(&self) -> Result<Vec<StorageDevice>> {
        let mut devices = Vec::new();
        
        // Use lsblk JSON output
        let output = Command::new("lsblk")
            .args(["-J", "-o", "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,FIRMWARE,MOUNTPOINT,FSTYPE,UUID,PARTUUID"])
            .output()
            .await?;
        
        let stdout = String::from_utf8_lossy(&output.stdout);
        let json: serde_json::Value = serde_json::from_str(&stdout)?;
        
        if let Some(blockdevices) = json.get("blockdevices").and_then(|v| v.as_array()) {
            for device in blockdevices {
                let name = device.get("name").and_then(|v| v.as_str()).unwrap_or("");
                let path = device.get("path").and_then(|v| v.as_str()).unwrap_or("");
                let type_ = device.get("type").and_then(|v| v.as_str()).unwrap_or("");
                let size = device.get("size").and_then(|v| v.as_str()).unwrap_or("0");
                let model = device.get("model").and_then(|v| v.as_str()).unwrap_or("");
                let serial = device.get("serial").and_then(|v| v.as_str()).unwrap_or("");
                let firmware = device.get("firmware").and_then(|v| v.as_str()).unwrap_or("");
                
                // Determine storage type
                let storage_type = match type_ {
                    "disk" => {
                        if path.contains("nvme") { StorageType::NVMe }
                        else if path.contains("sd") { StorageType::SATA }
                        else { StorageType::SCSI }
                    }
                    "loop" => StorageType::Loop,
                    _ => StorageType::SATA,
                };
                
                // Get SMART data
                let smart_data = self.get_smart_data(path).await.unwrap_or_default();
                let health = self.calculate_health(&smart_data);
                let temperature = self.get_drive_temperature(path).await;
                
                // Get partitions
                let mut partitions = Vec::new();
                if let Some(children) = device.get("children").and_then(|v| v.as_array()) {
                    for child in children {
                        partitions.push(Partition {
                            name: child.get("name").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            path: child.get("path").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                            start_sector: 0, // Would need more parsing
                            size_sectors: 0,
                            fs_type: child.get("fstype").and_then(|v| v.as_str()).map(|s| s.to_string()),
                            mount_point: child.get("mountpoint").and_then(|v| v.as_str()).map(|s| s.to_string()),
                            uuid: child.get("uuid").and_then(|v| v.as_str()).map(|s| s.to_string()),
                        });
                    }
                }
                
                devices.push(StorageDevice {
                    name: name.to_string(),
                    path: path.to_string(),
                    type_: storage_type,
                    size_bytes: parse_size_bytes(size),
                    model: model.to_string(),
                    serial: serial.to_string(),
                    firmware: firmware.to_string(),
                    health_percent: health,
                    temperature_c: temperature,
                    smart_data,
                    partitions,
                });
            }
        }
        
        Ok(devices)
    }
    
    async fn get_smart_data(&self, path: &str) -> Result<HashMap<String, String>> {
        let output = Command::new("smartctl").args(["-A", path]).output().await?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut data = HashMap::new();
        
        for line in stdout.lines().skip(7) { // Skip header
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 10 {
                data.insert(parts[1].to_string(), parts[9].to_string());
            }
        }
        Ok(data)
    }
    
    fn calculate_health(&self, smart: &HashMap<String, String>) -> u8 {
        // Simplified health calculation based on key SMART attributes
        let mut score = 100u8;
        
        if let Some(val) = smart.get("Reallocated_Sector_Ct").or_else(|| smart.get("5")) {
            if val.parse::<u32>().unwrap_or(0) > 0 { score -= 10; }
        }
        if let Some(val) = smart.get("Current_Pending_Sector").or_else(|| smart.get("197")) {
            if val.parse::<u32>().unwrap_or(0) > 0 { score -= 15; }
        }
        if let Some(val) = smart.get("Offline_Uncorrectable").or_else(|| smart.get("198")) {
            if val.parse::<u32>().unwrap_or(0) > 0 { score -= 20; }
        }
        
        score
    }
    
    async fn get_drive_temperature(&self, path: &str) -> Option<f32> {
        // Try NVMe temp
        if path.contains("nvme") {
            let temp_path = path.replace("nvme", "nvme").replace("p1", "").replace("p2", "").replace("p3", "");
            if let Ok(content) = fs::read_to_string(format!("/sys/class/hwmon/hwmon*/temp1_input")).await {
                return content.trim().parse::<f32>().ok().map(|v| v / 1000.0);
            }
        }
        
        // Try smartctl
        if let Ok(output) = Command::new("smartctl").args(["-A", path]).output().await {
            let stdout = String::from_utf8_lossy(&output.stdout);
            for line in stdout.lines() {
                if line.contains("Temperature_Celsius") || line.contains("Airflow_Temperature_Cel") {
                    let parts: Vec<&str> = line.split_whitespace().collect();
                    if parts.len() >= 10 {
                        return parts[9].parse().ok();
                    }
                }
            }
        }
        
        None
    }
    
    async fn get_network_interfaces(&self) -> Result<Vec<NetworkInterface>> {
        let mut interfaces = Vec::new();
        
        // Use ip -j link
        let output = Command::new("ip").args(["-j", "link", "show"]).output().await?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let links: serde_json::Value = serde_json::from_str(&stdout)?;
        
        if let Some(arr) = links.as_array() {
            for link in arr {
                let name = link.get("ifname").and_then(|v| v.as_str()).unwrap_or("");
                let index = link.get("ifindex").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
                let mtu = link.get("mtu").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
                let mac = link.get("address").and_then(|v| v.as_str()).unwrap_or("");
                
                // Get addresses
                let addr_output = Command::new("ip").args(["-j", "addr", "show", "dev", name]).output().await?;
                let addr_stdout = String::from_utf8_lossy(&addr_output.stdout);
                let addrs: serde_json::Value = serde_json::from_str(&addr_stdout)?;
                
                let mut addresses = Vec::new();
                if let Some(arr) = addrs.as_array() {
                    for addr_info in arr {
                        if let Some(addr_data) = addr_info.get("addr_info").and_then(|v| v.as_array()) {
                            for addr in addr_data {
                                addresses.push(IpAddress {
                                    family: addr.get("family").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                    address: addr.get("local").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                    prefix_len: addr.get("prefixlen").and_then(|v| v.as_u64()).unwrap_or(0) as u8,
                                    scope: addr.get("scope").and_then(|v| v.as_str()).unwrap_or("").to_string(),
                                });
                            }
                        }
                    }
                }
                
                // Get stats
                let stats = self.get_interface_stats(name).await?;
                
                // Get driver
                let driver = fs::read_to_string(format!("/sys/class/net/{}/device/driver/module/name", name))
                    .await.unwrap_or_default().trim().to_string();
                
                interfaces.push(NetworkInterface {
                    name: name.to_string(),
                    index,
                    mac: mac.to_string(),
                    mtu,
                    speed_mbps: None, // Would need ethtool
                    duplex: None,
                    addresses,
                    stats,
                    driver,
                    firmware: None,
                });
            }
        }
        
        Ok(interfaces)
    }
    
    async fn get_interface_stats(&self, name: &str) -> Result<InterfaceStats> {
        let content = fs::read_to_string(format!("/sys/class/net/{}/statistics/", name)).await?;
        // Parse individual stat files
        Ok(InterfaceStats {
            rx_bytes: fs::read_to_string(format!("/sys/class/net/{}/statistics/rx_bytes", name)).await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0),
            rx_packets: fs::read_to_string(format!("/sys/class/net/{}/statistics/rx_packets", name)).await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0),
            rx_errors: fs::read_to_string(format!("/sys/class/net/{}/statistics/rx_errors", name)).await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0),
            rx_dropped: fs::read_to_string(format!("/sys/class/net/{}/statistics/rx_dropped", name)).await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0),
            tx_bytes: fs::read_to_string(format!("/sys/class/net/{}/statistics/tx_bytes", name)).await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0),
            tx_packets: fs::read_to_string(format!("/sys/class/net/{}/statistics/tx_packets", name)).await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0),
            tx_errors: fs::read_to_string(format!("/sys/class/net/{}/statistics/tx_errors", name)).await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0),
            tx_dropped: fs::read_to_string(format!("/sys/class/net/{}/statistics/tx_dropped", name)).await.unwrap_or("0".to_string()).trim().parse().unwrap_or(0),
        })
    }
    
    async fn get_sensor_readings(&self) -> Result<Vec<SensorReading>> {
        let mut sensors = Vec::new();
        
        // hwmon sensors
        if let Ok(entries) = fs::read_dir("/sys/class/hwmon").await {
            let mut entries = entries;
            while let Some(entry) = entries.next_entry().await? {
                let name = fs::read_to_string(entry.path().join("name")).await.unwrap_or_default().trim().to_string();
                
                if let Ok(files) = fs::read_dir(entry.path()).await {
                    let mut files = files;
                    while let Some(file) = files.next_entry().await? {
                        let fname = file.file_name().to_string_lossy().to_string();
                        if fname.starts_with("temp") && fname.ends_with("_input") {
                            if let Ok(val) = fs::read_to_string(file.path()).await {
                                sensors.push(SensorReading {
                                    name: format!("{} {}", name, fname),
                                    type_: SensorType::Temperature,
                                    value: val.trim().parse::<f32>().unwrap_or(0.0) / 1000.0,
                                    unit: "°C".to_string(),
                                    min: None, max: None, critical: None,
                                });
                            }
                        } else if fname.starts_with("in") && fname.ends_with("_input") {
                            if let Ok(val) = fs::read_to_string(file.path()).await {
                                sensors.push(SensorReading {
                                    name: format!("{} {}", name, fname),
                                    type_: SensorType::Voltage,
                                    value: val.trim().parse::<f32>().unwrap_or(0.0) / 1000.0,
                                    unit: "V".to_string(),
                                    min: None, max: None, critical: None,
                                });
                            }
                        } else if fname.starts_with("fan") && fname.ends_with("_input") {
                            if let Ok(val) = fs::read_to_string(file.path()).await {
                                sensors.push(SensorReading {
                                    name: format!("{} {}", name, fname),
                                    type_: SensorType::Fan,
                                    value: val.trim().parse::<f32>().unwrap_or(0.0),
                                    unit: "RPM".to_string(),
                                    min: None, max: None, critical: None,
                                });
                            }
                        } else if fname.starts_with("power") && fname.ends_with("_input") {
                            if let Ok(val) = fs::read_to_string(file.path()).await {
                                sensors.push(SensorReading {
                                    name: format!("{} {}", name, fname),
                                    type_: SensorType::Power,
                                    value: val.trim().parse::<f32>().unwrap_or(0.0) / 1000000.0,
                                    unit: "W".to_string(),
                                    min: None, max: None, critical: None,
                                });
                            }
                        }
                    }
                }
            }
        }
        
        Ok(sensors)
    }
    
    async fn get_pci_devices(&self) -> Result<Vec<PciDevice>> {
        let output = Command::new("lspci").args(["-nnmm"]).output().await?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut devices = Vec::new();
        
        for line in stdout.lines() {
            // Parse lspci -nnmm format
            let parts: Vec<&str> = line.split('"').collect();
            if parts.len() >= 7 {
                devices.push(PciDevice {
                    address: parts[0].trim().to_string(),
                    class: parts[1].to_string(),
                    vendor_id: parts[2].to_string(),
                    device_id: parts[3].to_string(),
                    vendor_name: parts[4].to_string(),
                    device_name: parts[5].to_string(),
                    driver: None, // Would need lspci -k
                    numa_node: None,
                });
            }
        }
        
        Ok(devices)
    }
    
    async fn get_usb_devices(&self) -> Result<Vec<UsbDevice>> {
        let output = Command::new("lsusb").args(["-t"]).output().await?;
        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut devices = Vec::new();
        
        for line in stdout.lines() {
            // Parse lsusb -t output
            // Simplified
        }
        
        Ok(devices)
    }
}

fn parse_size_kb(s: &str) -> u32 {
    s.trim().trim_end_matches('K').trim().parse().unwrap_or(0)
}

fn parse_size_bytes(s: &str) -> u64 {
    let s = s.trim();
    if s.ends_with("G") || s.ends_with("GB") {
        s.trim_end_matches(|c: char| !c.is_ascii_digit() && c != '.').parse::<f64>().unwrap_or(0.0) * 1024.0 * 1024.0 * 1024.0
    } else if s.ends_with("M") || s.ends_with("MB") {
        s.trim_end_matches(|c: char| !c.is_ascii_digit() && c != '.').parse::<f64>().unwrap_or(0.0) * 1024.0 * 1024.0
    } else if s.ends_with("K") || s.ends_with("KB") {
        s.trim_end_matches(|c: char| !c.is_ascii_digit() && c != '.').parse::<f64>().unwrap_or(0.0) * 1024.0
    } else {
        s.parse().unwrap_or(0)
    } as u64
}