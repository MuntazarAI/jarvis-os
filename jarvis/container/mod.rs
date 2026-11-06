//! Container and VM Orchestration for JARVIS-OS
//!
//! Policy-gated container/VM management with:
//! - Podman/Buildah integration
// - KVM/QEMU micro-VMs
// - Firecracker lightweight VMs
// - GPU passthrough
// - Resource quotas and limits

use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use tokio::process::Command;
use uuid::Uuid;

/// Container runtime type
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum RuntimeType {
    Podman,
    Docker,
    Crun,
    Runsc, // gVisor
}

/// Container specification
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContainerSpec {
    pub id: String,
    pub name: String,
    pub image: String,
    pub runtime: RuntimeType,
    pub command: Vec<String>,
    pub args: Vec<String>,
    pub env: HashMap<String, String>,
    pub volumes: Vec<VolumeMount>,
    pub ports: Vec<PortMapping>,
    pub resources: ResourceLimits,
    pub security: SecurityConfig,
    pub network: NetworkConfig,
    pub gpu: Option<GpuConfig>,
    pub labels: HashMap<String, String>,
    pub annotations: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VolumeMount {
    pub source: String,
    pub destination: String,
    pub read_only: bool,
    pub type_: VolumeType,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum VolumeType {
    Bind,
    Volume,
    Tmpfs,
    Devpts,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortMapping {
    pub container_port: u16,
    pub host_port: Option<u16>,
    pub protocol: String, // tcp, udp, sctp
    pub host_ip: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResourceLimits {
    pub cpu_quota: Option<u64>,      // microseconds per period
    pub cpu_period: Option<u64>,     // microseconds
    pub cpu_shares: Option<u64>,     // relative weight
    pub cpuset_cpus: Option<String>, // e.g., "0-3"
    pub cpuset_mems: Option<String>, // NUMA nodes
    pub memory_limit_bytes: Option<u64>,
    pub memory_swap_limit_bytes: Option<u64>,
    pub memory_reservation_bytes: Option<u64>,
    pub kernel_memory_limit_bytes: Option<u64>,
    pub pids_limit: Option<u64>,
    pub ulimits: Vec<Ulimit>,
    pub blkio_weight: Option<u16>,
    pub blkio_device_read_bps: Vec<ThrottleDevice>,
    pub blkio_device_write_bps: Vec<ThrottleDevice>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Ulimit {
    pub name: String,
    pub soft: u64,
    pub hard: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThrottleDevice {
    pub path: String,
    pub rate: u64, // bytes per second
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecurityConfig {
    pub privileged: bool,
    pub capabilities_add: Vec<String>,
    pub capabilities_drop: Vec<String>,
    pub seccomp_profile: Option<String>, // path to profile or "unconfined"
    pub apparmor_profile: Option<String>,
    pub selinux_label: Option<String>,
    pub no_new_privileges: bool,
    pub read_only_rootfs: bool,
    pub user: Option<String>, // uid:gid
    pub group_add: Vec<String>,
    pub sysctls: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkConfig {
    pub mode: NetworkMode,
    pub network_name: Option<String>,
    pub dns: Vec<String>,
    pub dns_search: Vec<String>,
    pub dns_options: Vec<String>,
    pub extra_hosts: HashMap<String, String>,
    pub mac_address: Option<String>,
    pub ipv4_address: Option<String>,
    pub ipv6_address: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum NetworkMode {
    Bridge,
    Host,
    None,
    Container(String), // container:name
    Custom(String),    // custom network name
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuConfig {
    pub device_ids: Vec<String>, // UUIDs or indices
    pub capabilities: Vec<String>, // compute, graphics, video, display
    pub driver_version: Option<String>,
}

/// Container state
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ContainerState {
    Created,
    Running,
    Paused,
    Stopped,
    Exited,
    Dead,
    Removing,
}

/// Container status
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContainerStatus {
    pub id: String,
    pub name: String,
    pub state: ContainerState,
    pub pid: Option<u32>,
    pub exit_code: Option<i32>,
    pub started_at: Option<String>,
    pub finished_at: Option<String>,
    pub health: Option<HealthStatus>,
    pub resources: ResourceUsage,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthStatus {
    pub status: String, // healthy, unhealthy, starting
    pub failing_streak: u32,
    pub log: Vec<HealthCheckLog>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthCheckLog {
    pub start: String,
    pub end: String,
    pub exit_code: i32,
    pub output: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ResourceUsage {
    pub cpu_percent: f64,
    pub memory_bytes: u64,
    pub memory_limit_bytes: u64,
    pub memory_percent: f64,
    pub network_rx_bytes: u64,
    pub network_tx_bytes: u64,
    pub block_read_bytes: u64,
    pub block_write_bytes: u64,
    pub pids_current: u64,
}

/// VM specification (for micro-VMs)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VmSpec {
    pub id: String,
    pub name: String,
    pub vcpu_count: u32,
    pub memory_mib: u64,
    pub kernel_path: PathBuf,
    pub initrd_path: Option<PathBuf>,
    pub cmdline: String,
    pub disks: Vec<VmDisk>,
    pub network_interfaces: Vec<VmNetworkInterface>,
    pub gpu_devices: Vec<VmGpuDevice>,
    pub vsock_port: Option<u32>,
    pub entropy_source: Option<PathBuf>,
    pub balloon: bool,
    pub console: VmConsole,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VmDisk {
    pub path: PathBuf,
    pub read_only: bool,
    pub format: DiskFormat,
    pub interface: DiskInterface,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum DiskFormat {
    Raw,
    Qcow2,
    Vmdk,
    Vdi,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum DiskInterface {
    Virtio,
    Scsi,
    Sata,
    Nvme,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VmNetworkInterface {
    pub mac: Option<String>,
    pub ip: Option<String>,
    pub tap_device: Option<String>,
    pub bridge: Option<String>,
    pub vhost_user: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VmGpuDevice {
    pub gpu_id: String,
    pub type_: GpuPassthroughType,
    pub display: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum GpuPassthroughType {
    VirtioGpu,
    VirtioGpuVirgl,
    VirtioGpuNative,
    VfioPci,
    MediatedDevice, // vGPU
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum VmConsole {
    None,
    Serial,
    Pty,
    Vsock(u32),
}

/// Container/VM Manager
pub struct ContainerManager {
    runtime: RuntimeType,
    podman_path: PathBuf,
    firecracker_path: Option<PathBuf>,
    qemu_path: Option<PathBuf>,
}

impl ContainerManager {
    pub fn new() -> Result<Self> {
        // Detect available runtimes
        let runtime = if Self::command_exists("podman") {
            RuntimeType::Podman
        } else if Self::command_exists("docker") {
            RuntimeType::Docker
        } else {
            RuntimeType::Crun
        };
        
        let podman_path = Self::find_binary("podman")?;
        let firecracker_path = Self::find_binary("firecracker").ok();
        let qemu_path = Self::find_binary("qemu-system-x86_64").ok();
        
        Ok(Self {
            runtime,
            podman_path,
            firecracker_path,
            qemu_path,
        })
    }
    
    fn command_exists(cmd: &str) -> bool {
        std::process::Command::new("which").arg(cmd).output().map(|o| o.status.success()).unwrap_or(false)
    }
    
    fn find_binary(name: &str) -> Result<PathBuf> {
        let output = std::process::Command::new("which").arg(name).output()?;
        let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if path.is_empty() {
            return Err(anyhow::anyhow!("{} not found", name));
        }
        Ok(PathBuf::from(path))
    }
    
    // --- Container Operations ---
    
    pub async fn create_container(&self, spec: ContainerSpec) -> Result<String> {
        let mut args = vec!["create".to_string()];
        
        // Name
        args.push("--name".to_string());
        args.push(spec.name.clone());
        
        // Image
        args.push(spec.image.clone());
        
        // Command
        if !spec.command.is_empty() {
            args.push("--entrypoint".to_string());
            args.push(spec.command.join(" "));
        }
        if !spec.args.is_empty() {
            args.extend(spec.args);
        }
        
        // Environment
        for (k, v) in spec.env {
            args.push("--env".to_string());
            args.push(format!("{}={}", k, v));
        }
        
        // Volumes
        for vol in spec.volumes {
            args.push("--volume".to_string());
            let ro = if vol.read_only { ":ro" } else { "" };
            args.push(format!("{}:{}{}", vol.source, vol.destination, ro));
        }
        
        // Ports
        for port in spec.ports {
            let host = port.host_port.map(|p| p.to_string()).unwrap_or_default();
            args.push("--publish".to_string());
            args.push(format!("{}:{}/{}", host, port.container_port, port.protocol));
        }
        
        // Resources
        if let Some(cpu_quota) = spec.resources.cpu_quota {
            args.push("--cpu-quota".to_string());
            args.push(cpu_quota.to_string());
        }
        if let Some(cpu_period) = spec.resources.cpu_period {
            args.push("--cpu-period".to_string());
            args.push(cpu_period.to_string());
        }
        if let Some(cpu_shares) = spec.resources.cpu_shares {
            args.push("--cpu-shares".to_string());
            args.push(cpu_shares.to_string());
        }
        if let Some(cpuset) = spec.resources.cpuset_cpus {
            args.push("--cpuset-cpus".to_string());
            args.push(cpuset);
        }
        if let Some(mem) = spec.resources.memory_limit_bytes {
            args.push("--memory".to_string());
            args.push(format!("{}b", mem));
        }
        if let Some(pids) = spec.resources.pids_limit {
            args.push("--pids-limit".to_string());
            args.push(pids.to_string());
        }
        
        // Security
        if spec.security.privileged {
            args.push("--privileged".to_string());
        }
        for cap in spec.security.capabilities_add {
            args.push("--cap-add".to_string());
            args.push(cap);
        }
        for cap in spec.security.capabilities_drop {
            args.push("--cap-drop".to_string());
            args.push(cap);
        }
        if let Some(seccomp) = spec.security.seccomp_profile {
            args.push("--security-opt".to_string());
            args.push(format!("seccomp={}", seccomp));
        }
        if spec.security.no_new_privileges {
            args.push("--security-opt".to_string());
            args.push("no-new-privileges".to_string());
        }
        if spec.security.read_only_rootfs {
            args.push("--read-only".to_string());
        }
        if let Some(user) = spec.security.user {
            args.push("--user".to_string());
            args.push(user);
        }
        for (k, v) in spec.security.sysctls {
            args.push("--sysctl".to_string());
            args.push(format!("{}={}", k, v));
        }
        
        // Network
        match spec.network.mode {
            NetworkMode::Bridge => {
                args.push("--network".to_string());
                args.push("bridge".to_string());
            }
            NetworkMode::Host => {
                args.push("--network".to_string());
                args.push("host".to_string());
            }
            NetworkMode::None => {
                args.push("--network".to_string());
                args.push("none".to_string());
            }
            NetworkMode::Container(name) => {
                args.push("--network".to_string());
                args.push(format!("container:{}", name));
            }
            NetworkMode::Custom(name) => {
                args.push("--network".to_string());
                args.push(name);
            }
        }
        
        // GPU
        if let Some(gpu) = spec.gpu {
            for dev in gpu.device_ids {
                args.push("--device".to_string());
                args.push(format!("/dev/dri/{}", dev));
            }
        }
        
        // Labels
        for (k, v) in spec.labels {
            args.push("--label".to_string());
            args.push(format!("{}={}", k, v));
        }
        
        // Execute
        let output = Command::new(&self.podman_path)
            .args(&args)
            .output()
            .await?;
        
        if !output.status.success() {
            return Err(anyhow::anyhow!("Failed to create container: {}", String::from_utf8_lossy(&output.stderr)));
        }
        
        let container_id = String::from_utf8_lossy(&output.stdout).trim().to_string();
        Ok(container_id)
    }
    
    pub async fn start_container(&self, id: &str) -> Result<()> {
        let output = Command::new(&self.podman_path)
            .args(["start", id])
            .output()
            .await?;
        
        if !output.status.success() {
            return Err(anyhow::anyhow!("Failed to start container: {}", String::from_utf8_lossy(&output.stderr)));
        }
        Ok(())
    }
    
    pub async fn stop_container(&self, id: &str, timeout: Option<u32>) -> Result<()> {
        let mut args = vec!["stop".to_string()];
        if let Some(t) = timeout {
            args.push("--time".to_string());
            args.push(t.to_string());
        }
        args.push(id.to_string());
        
        let output = Command::new(&self.podman_path)
            .args(&args)
            .output()
            .await?;
        
        if !output.status.success() {
            return Err(anyhow::anyhow!("Failed to stop container: {}", String::from_utf8_lossy(&output.stderr)));
        }
        Ok(())
    }
    
    pub async fn remove_container(&self, id: &str, force: bool) -> Result<()> {
        let mut args = vec!["rm".to_string()];
        if force {
            args.push("--force".to_string());
        }
        args.push(id.to_string());
        
        let output = Command::new(&self.podman_path)
            .args(&args)
            .output()
            .await?;
        
        if !output.status.success() {
            return Err(anyhow::anyhow!("Failed to remove container: {}", String::from_utf8_lossy(&output.stderr)));
        }
        Ok(())
    }
    
    pub async fn list_containers(&self, all: bool) -> Result<Vec<ContainerStatus>> {
        let mut args = vec!["ps".to_string(), "--format".to_string(), "json".to_string()];
        if all {
            args.push("--all".to_string());
        }
        
        let output = Command::new(&self.podman_path)
            .args(&args)
            .output()
            .await?;
        
        let stdout = String::from_utf8_lossy(&output.stdout);
        let containers: Vec<ContainerStatus> = serde_json::from_str(&stdout)?;
        Ok(containers)
    }
    
    pub async fn get_container_stats(&self, id: &str) -> Result<ResourceUsage> {
        let output = Command::new(&self.podman_path)
            .args(["stats", "--no-stream", "--format", "json", id])
            .output()
            .await?;
        
        let stdout = String::from_utf8_lossy(&output.stdout);
        let stats: ResourceUsage = serde_json::from_str(&stdout)?;
        Ok(stats)
    }
    
    pub async fn exec_in_container(&self, id: &str, command: Vec<String>) -> Result<String> {
        let mut args = vec!["exec".to_string(), id.to_string()];
        args.extend(command);
        
        let output = Command::new(&self.podman_path)
            .args(&args)
            .output()
            .await?;
        
        Ok(String::from_utf8_lossy(&output.stdout).to_string())
    }
    
    // --- Image Operations ---
    
    pub async fn pull_image(&self, image: &str) -> Result<()> {
        let output = Command::new(&self.podman_path)
            .args(["pull", image])
            .output()
            .await?;
        
        if !output.status.success() {
            return Err(anyhow::anyhow!("Failed to pull image: {}", String::from_utf8_lossy(&output.stderr)));
        }
        Ok(())
    }
    
    pub async fn build_image(&self, context: &str, tag: &str, dockerfile: Option<&str>) -> Result<()> {
        let mut args = vec!["build".to_string(), "-t".to_string(), tag.to_string()];
        if let Some(df) = dockerfile {
            args.push("-f".to_string());
            args.push(df.to_string());
        }
        args.push(context.to_string());
        
        let output = Command::new(&self.podman_path)
            .args(&args)
            .output()
            .await?;
        
        if !output.status.success() {
            return Err(anyhow::anyhow!("Failed to build image: {}", String::from_utf8_lossy(&output.stderr)));
        }
        Ok(())
    }
    
    // --- VM Operations (Firecracker) ---
    
    pub async fn create_microvm(&self, spec: VmSpec) -> Result<String> {
        let firecracker = self.firecracker_path.as_ref()
            .ok_or_else(|| anyhow::anyhow!("Firecracker not installed"))?;
        
        // Generate Firecracker config JSON
        let config = self.generate_firecracker_config(&spec)?;
        let config_path = format!("/tmp/firecracker-{}.json", spec.id);
        tokio::fs::write(&config_path, serde_json::to_string_pretty(&config)?).await?;
        
        // Start Firecracker
        let output = Command::new(firecracker)
            .args(["--config-file", &config_path, "--no-api"])
            .spawn()?;
        
        Ok(spec.id)
    }
    
    fn generate_firecracker_config(&self, spec: &VmSpec) -> Result<serde_json::Value> {
        let mut config = serde_json::json!({
            "boot-source": {
                "kernel_image_path": spec.kernel_path,
                "boot_args": spec.cmdline,
            },
            "drives": [],
            "machine-config": {
                "vcpu_count": spec.vcpu_count,
                "mem_size_mib": spec.memory_mib,
                "balloon": spec.balloon,
            },
            "network-interfaces": [],
        });
        
        // Add initrd if present
        if let Some(initrd) = &spec.initrd_path {
            config["boot-source"]["initrd_path"] = serde_json::Value::String(initrd.to_string_lossy().to_string());
        }
        
        // Add disks
        let mut drives = Vec::new();
        for (i, disk) in spec.disks.iter().enumerate() {
            drives.push(serde_json::json!({
                "drive_id": format!("disk{}", i),
                "path_on_host": disk.path,
                "is_read_only": disk.read_only,
                "is_root_device": i == 0,
                "io_engine": "Sync",
            }));
        }
        config["drives"] = serde_json::Value::Array(drives);
        
        // Add network interfaces
        let mut netifs = Vec::new();
        for (i, net) in spec.network_interfaces.iter().enumerate() {
            let mut netif = serde_json::json!({
                "iface_id": format!("eth{}", i),
                "host_dev_name": net.tap_device.clone().unwrap_or_default(),
            });
            if let Some(mac) = &net.mac {
                netif["mac_address"] = serde_json::Value::String(mac.clone());
            }
            netifs.push(netif);
        }
        config["network-interfaces"] = serde_json::Value::Array(netifs);
        
        // Add vsock if configured
        if let Some(port) = spec.vsock_port {
            config["vsock"] = serde_json::json!({
                "vsock_id": "vsock0",
                "guest_cid": 3,
                "uds_path": format!("/tmp/firecracker-{}.vsock", spec.id),
            });
        }
        
        Ok(config)
    }
    
    // --- GPU Passthrough ---
    
    pub async fn list_gpus(&self) -> Result<Vec<GpuDeviceInfo>> {
        let mut gpus = Vec::new();
        
        // NVIDIA
        if let Ok(output) = Command::new("nvidia-smi")
            .args(["--query-gpu=uuid,name,memory.total,driver_version", "--format=csv,noheader,nounits"])
            .output()
            .await
        {
            for line in String::from_utf8_lossy(&output.stdout).lines() {
                let parts: Vec<&str> = line.split(',').map(|s| s.trim()).collect();
                if parts.len() >= 4 {
                    gpus.push(GpuDeviceInfo {
                        uuid: parts[0].to_string(),
                        name: parts[1].to_string(),
                        memory_mb: parts[2].parse().unwrap_or(0),
                        driver_version: parts[3].to_string(),
                        vendor: "NVIDIA".to_string(),
                        type_: GpuType::Nvidia,
                    });
                }
            }
        }
        
        // AMD
        // ... rocm-smi parsing
        
        Ok(gpus)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GpuDeviceInfo {
    pub uuid: String,
    pub name: String,
    pub memory_mb: u64,
    pub driver_version: String,
    pub vendor: String,
    pub type_: GpuType,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum GpuType {
    Nvidia,
    Amd,
    Intel,
    Other,
}

/// Policy-gated wrapper
pub struct PolicyGatedContainerManager {
    manager: ContainerManager,
    policy_engine: crate::os::policy::SystemPolicyEngine,
}

impl PolicyGatedContainerManager {
    pub fn new(policy_engine: crate::os::policy::SystemPolicyEngine) -> Result<Self> {
        Ok(Self {
            manager: ContainerManager::new()?,
            policy_engine,
        })
    }
    
    pub async fn create_container(&self, subject: &str, spec: ContainerSpec) -> Result<String> {
        let allowed = self.policy_engine.evaluate(
            subject,
            crate::os::policy::SystemResource::PROCESS_LIST, // Reuse for now
            None
        ).await;
        
        if allowed != crate::os::policy::PolicyAction::ALLOW {
            return Err(anyhow::anyhow!("Container creation not authorized for {}", subject));
        }
        
        self.manager.create_container(spec).await
    }
    
    // ... other methods with policy checks
}