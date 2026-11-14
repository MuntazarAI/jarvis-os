//! Syscall Audit using eBPF raw tracepoints
//!
//! Comprehensive syscall monitoring with argument capture

use crate::bpf::{BpfEvent, BpfProgram};
use anyhow::Result;
use aya::{maps::PerfEventArray, programs::TracePoint, Bpf};
use aya_log::BpfLogger;
use std::sync::Arc;
use tokio::sync::mpsc;

const SYSCALL_AUDIT_BPF: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/syscall_audit.bpf.o"));

pub struct SyscallAudit {
    bpf: Option<Bpf>,
    event_tx: mpsc::UnboundedSender<BpfEvent>,
    syscall_filter: Arc<std::sync::Mutex<Vec<i64>>>,
}

impl SyscallAudit {
    pub async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        let mut bpf = Bpf::load(SYSCALL_AUDIT_BPF)?;
        BpfLogger::init(&mut bpf)?;
        
        // Attach to sys_enter and sys_exit tracepoints
        let program: &mut TracePoint = bpf.program_mut("sys_enter").unwrap().try_into()?;
        program.attach("raw_syscalls", "sys_enter")?;
        
        let program: &mut TracePoint = bpf.program_mut("sys_exit").unwrap().try_into()?;
        program.attach("raw_syscalls", "sys_exit")?;
        
        // Perf event reader
        let mut perf_array = PerfEventArray::try_from(bpf.map_mut("SYSCALL_EVENTS").unwrap())?;
        let tx = event_tx.clone();
        
        for cpu_id in 0..num_cpus::get() {
            let mut buf = perf_array.open(cpu_id as u32, None)?;
            let tx = tx.clone();
            tokio::spawn(async move {
                let mut buffers = vec![vec![0u8; 4096]; 4];
                loop {
                    let events = buf.read_events(&mut buffers).await.unwrap();
                    for buf in events {
                        if let Ok(event) = parse_syscall_event(buf) {
                            let _ = tx.send(event);
                        }
                    }
                }
            });
        }
        
        Ok(Self {
            bpf: Some(bpf),
            event_tx,
            syscall_filter: Arc::new(std::sync::Mutex::new(Vec::new())),
        })
    }
    
    pub fn filter_syscall(&self, syscall_nr: i64) {
        self.syscall_filter.lock().unwrap().push(syscall_nr);
        // Update BPF map
    }
    
    pub fn unfilter_syscall(&self, syscall_nr: i64) {
        self.syscall_filter.lock().unwrap().retain(|&x| x != syscall_nr);
    }
}

fn parse_syscall_event(data: &[u8]) -> Result<BpfEvent> {
    use std::mem;
    
    #[repr(C)]
    struct SyscallEvent {
        pid: u32,
        tid: u32,
        syscall_nr: i64,
        args: [u64; 6],
        ret: i64,
        timestamp_ns: u64,
    }
    
    if data.len() < mem::size_of::<SyscallEvent>() {
        return Err(anyhow::anyhow!("Event too small"));
    }
    
    let event = unsafe { &*(data.as_ptr() as *const SyscallEvent) };
    
    Ok(BpfEvent::Syscall {
        pid: event.pid,
        tid: event.tid,
        syscall_nr: event.syscall_nr,
        args: event.args,
        ret: event.ret,
        timestamp_ns: event.timestamp_ns,
    })
}

#[async_trait::async_trait]
impl BpfProgram for SyscallAudit {
    async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        Self::load(event_tx).await
    }
    
    async fn unload(&mut self) -> Result<()> {
        self.bpf.take();
        Ok(())
    }
    
    fn name(&self) -> &str {
        "syscall_audit"
    }
    
    fn is_loaded(&self) -> bool {
        self.bpf.is_some()
    }
}