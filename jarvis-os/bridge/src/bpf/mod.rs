//! eBPF Programs for JARVIS-OS Kernel Integration
//!
//! Provides kernel-level observability and enforcement:
//! - Process execution tracing (execve, clone, fork)
// - Network packet filtering (XDP)
// - Filesystem monitoring (fentry/fexit)
// - Syscall auditing (raw tracepoints)
// - LSM hooks for MAC enforcement

mod exec_tracer;
mod net_filter;
mod fs_monitor;
mod syscall_audit;
mod lsm_hooks;

pub use exec_tracer::ExecTracer;
pub use net_filter::NetFilter;
pub use fs_monitor::FsMonitor;
pub use syscall_audit::SyscallAudit;
pub use lsm_hooks::LsmHooks;

use anyhow::Result;
use std::sync::Arc;
use tokio::sync::mpsc;

/// Events emitted by eBPF programs
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub enum BpfEvent {
    ProcessExec {
        pid: u32,
        ppid: u32,
        uid: u32,
        gid: u32,
        comm: String,
        filename: String,
        argv: Vec<String>,
        timestamp_ns: u64,
    },
    ProcessExit {
        pid: u32,
        ppid: u32,
        exit_code: i32,
        timestamp_ns: u64,
    },
    NetworkPacket {
        ifindex: u32,
        src_ip: String,
        dst_ip: String,
        src_port: u16,
        dst_port: u16,
        protocol: u8,
        action: String,
        timestamp_ns: u64,
    },
    FileAccess {
        pid: u32,
        uid: u32,
        path: String,
        operation: String,
        result: i32,
        timestamp_ns: u64,
    },
    Syscall {
        pid: u32,
        tid: u32,
        syscall_nr: i64,
        args: [u64; 6],
        ret: i64,
        timestamp_ns: u64,
    },
    SecurityCheck {
        hook: String,
        pid: u32,
        uid: u32,
        result: i32,
        details: String,
        timestamp_ns: u64,
    },
}

/// eBPF manager coordinating all programs
pub struct BpfManager {
    exec_tracer: Option<ExecTracer>,
    net_filter: Option<NetFilter>,
    fs_monitor: Option<FsMonitor>,
    syscall_audit: Option<SyscallAudit>,
    lsm_hooks: Option<LsmHooks>,
    event_tx: mpsc::UnboundedSender<BpfEvent>,
    _event_rx: Arc<tokio::sync::Mutex<mpsc::UnboundedReceiver<BpfEvent>>>,
}

impl BpfManager {
    pub fn new() -> Self {
        let (tx, rx) = mpsc::unbounded_channel();
        Self {
            exec_tracer: None,
            net_filter: None,
            fs_monitor: None,
            syscall_audit: None,
            lsm_hooks: None,
            event_tx: tx,
            _event_rx: Arc::new(tokio::sync::Mutex::new(rx)),
        }
    }

    pub async fn load_all(&mut self) -> Result<()> {
        // Load programs in order of dependency
        self.exec_tracer = Some(ExecTracer::load(self.event_tx.clone()).await?);
        self.net_filter = Some(NetFilter::load(self.event_tx.clone()).await?);
        self.fs_monitor = Some(FsMonitor::load(self.event_tx.clone()).await?);
        self.syscall_audit = Some(SyscallAudit::load(self.event_tx.clone()).await?);
        self.lsm_hooks = Some(LsmHooks::load(self.event_tx.clone()).await?);
        Ok(())
    }

    pub async fn unload_all(&mut self) -> Result<()> {
        if let Some(t) = self.lsm_hooks.take() { t.unload().await?; }
        if let Some(t) = self.syscall_audit.take() { t.unload().await?; }
        if let Some(t) = self.fs_monitor.take() { t.unload().await?; }
        if let Some(t) = self.net_filter.take() { t.unload().await?; }
        if let Some(t) = self.exec_tracer.take() { t.unload().await?; }
        Ok(())
    }

    pub fn event_sender(&self) -> mpsc::UnboundedSender<BpfEvent> {
        self.event_tx.clone()
    }
}

/// Base trait for eBPF programs
#[async_trait::async_trait]
pub trait BpfProgram: Send + Sync {
    async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> where Self: Sized;
    async fn unload(&mut self) -> Result<()>;
    fn name(&self) -> &str;
    fn is_loaded(&self) -> bool;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_bpf_manager_creation() {
        let manager = BpfManager::new();
        assert!(manager.exec_tracer.is_none());
    }
}