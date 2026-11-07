//! Filesystem Monitor using eBPF fentry/fexit
//!
//! Tracks file operations: open, read, write, unlink, rename, chmod

use crate::bpf::{BpfEvent, BpfProgram};
use anyhow::Result;
use aya::{maps::PerfEventArray, programs::FEntry, Bpf};
use aya_log::BpfLogger;
use std::sync::Arc;
use tokio::sync::mpsc;

const FS_MONITOR_BPF: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/fs_monitor.bpf.o"));

pub struct FsMonitor {
    bpf: Option<Bpf>,
    event_tx: mpsc::UnboundedSender<BpfEvent>,
    watch_paths: Arc<std::sync::Mutex<Vec<String>>>,
}

impl FsMonitor {
    pub async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        let mut bpf = Bpf::load(FS_MONITOR_BPF)?;
        BpfLogger::init(&mut bpf)?;
        
        // Attach fentry/fexit probes for filesystem operations
        let ops = [
            "vfs_open", "vfs_read", "vfs_write", "vfs_unlink",
            "vfs_rename", "vfs_mkdir", "vfs_rmdir", "vfs_chmod",
            "vfs_chown", "vfs_statx", "security_inode_permission",
        ];
        
        for op in ops {
            if let Some(prog) = bpf.program_mut(op) {
                let mut fentry: FEntry = prog.try_into()?;
                fentry.attach(op)?;
            }
            if let Some(prog) = bpf.program_mut(&format!("{}_exit", op)) {
                let mut fexit: FEntry = prog.try_into()?;
                fexit.attach(&format!("{}_exit", op))?;
            }
        }
        
        // Perf event setup
        let mut perf_array = PerfEventArray::try_from(bpf.map_mut("FS_EVENTS").unwrap())?;
        let tx = event_tx.clone();
        
        for cpu_id in 0..num_cpus::get() {
            let mut buf = perf_array.open(cpu_id as u32, None)?;
            let tx = tx.clone();
            tokio::spawn(async move {
                let mut buffers = vec![vec![0u8; 4096]; 4];
                loop {
                    let events = buf.read_events(&mut buffers).await.unwrap();
                    for buf in events {
                        if let Ok(event) = parse_fs_event(buf) {
                            let _ = tx.send(event);
                        }
                    }
                }
            });
        }
        
        Ok(Self {
            bpf: Some(bpf),
            event_tx,
            watch_paths: Arc::new(std::sync::Mutex::new(Vec::new())),
        })
    }
    
    pub fn add_watch_path(&self, path: String) {
        self.watch_paths.lock().unwrap().push(path);
        // Update BPF map with watch paths
    }
    
    pub fn remove_watch_path(&self, path: &str) {
        self.watch_paths.lock().unwrap().retain(|p| p != path);
    }
}

fn parse_fs_event(data: &[u8]) -> Result<BpfEvent> {
    use std::mem;
    
    #[repr(C)]
    struct FsEvent {
        pid: u32,
        uid: u32,
        operation: u8,  // 0=open, 1=read, 2=write, 3=unlink, etc.
        result: i32,
        timestamp_ns: u64,
        path: [u8; 256],
    }
    
    if data.len() < mem::size_of::<FsEvent>() {
        return Err(anyhow::anyhow!("Event too small"));
    }
    
    let event = unsafe { &*(data.as_ptr() as *const FsEvent) };
    let path = String::from_utf8_lossy(&event.path).trim_end_matches('\0').to_string();
    let operation = match event.operation {
        0 => "open", 1 => "read", 2 => "write", 3 => "unlink",
        4 => "rename", 5 => "mkdir", 6 => "rmdir", 7 => "chmod",
        8 => "chown", 9 => "statx", 10 => "permission", _ => "unknown",
    }.to_string();
    
    Ok(BpfEvent::FileAccess {
        pid: event.pid,
        uid: event.uid,
        path,
        operation,
        result: event.result,
        timestamp_ns: event.timestamp_ns,
    })
}

#[async_trait::async_trait]
impl BpfProgram for FsMonitor {
    async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        Self::load(event_tx).await
    }
    
    async fn unload(&mut self) -> Result<()> {
        self.bpf.take();
        Ok(())
    }
    
    fn name(&self) -> &str {
        "fs_monitor"
    }
    
    fn is_loaded(&self) -> bool {
        self.bpf.is_some()
    }
}