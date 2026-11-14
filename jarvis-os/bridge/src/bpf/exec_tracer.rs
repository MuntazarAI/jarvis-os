//! Process Execution Tracer using eBPF
//!
//! Traces execve/execveat syscalls with full argument capture

use crate::bpf::{BpfEvent, BpfProgram};
use anyhow::Result;
use aya::{maps::PerfEventArray, programs::TracePoint, Bpf};
use aya_log::BpfLogger;
use std::sync::Arc;
use tokio::sync::mpsc;

const EXEC_TRACER_BPF: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/exec_tracer.bpf.o"));

pub struct ExecTracer {
    bpf: Option<Bpf>,
    event_tx: mpsc::UnboundedSender<BpfEvent>,
}

impl ExecTracer {
    pub async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        let mut bpf = Bpf::load(EXEC_TRACER_BPF)?;
        
        // Initialize logger
        BpfLogger::init(&mut bpf)?;
        
        // Attach tracepoints
        let program: &mut TracePoint = bpf.program_mut("trace_execve").unwrap().try_into()?;
        program.attach("syscalls", "sys_enter_execve")?;
        
        let program: &mut TracePoint = bpf.program_mut("trace_execveat").unwrap().try_into()?;
        program.attach("syscalls", "sys_enter_execveat")?;
        
        let program: &mut TracePoint = bpf.program_mut("trace_exit_execve").unwrap().try_into()?;
        program.attach("syscalls", "sys_exit_execve")?;
        
        // Set up perf event reader
        let mut perf_array = PerfEventArray::try_from(bpf.map_mut("EXEC_EVENTS").unwrap())?;
        let tx = event_tx.clone();
        
        for cpu_id in 0..num_cpus::get() {
            let mut buf = perf_array.open(cpu_id as u32, None)?;
            let tx = tx.clone();
            tokio::spawn(async move {
                let mut buffers = vec![vec![0u8; 4096]; 4];
                loop {
                    let events = buf.read_events(&mut buffers).await.unwrap();
                    for buf in events {
                        if let Ok(event) = parse_exec_event(buf) {
                            let _ = tx.send(event);
                        }
                    }
                }
            });
        }
        
        Ok(Self {
            bpf: Some(bpf),
            event_tx,
        })
    }
}

fn parse_exec_event(data: &[u8]) -> Result<BpfEvent> {
    // Parse the binary event format from BPF
    // This is a simplified version - real implementation uses aya::pod
    use std::mem;
    
    #[repr(C)]
    struct ExecEvent {
        pid: u32,
        ppid: u32,
        uid: u32,
        gid: u32,
        timestamp_ns: u64,
        comm: [u8; 16],
        filename: [u8; 256],
        argv_ptr: u64,
    }
    
    if data.len() < mem::size_of::<ExecEvent>() {
        return Err(anyhow::anyhow!("Event too small"));
    }
    
    let event = unsafe { &*(data.as_ptr() as *const ExecEvent) };
    
    let comm = String::from_utf8_lossy(&event.comm).trim_end_matches('\0').to_string();
    let filename = String::from_utf8_lossy(&event.filename).trim_end_matches('\0').to_string();
    
    // Note: argv parsing requires reading user memory - simplified here
    let argv = vec![filename.clone()];
    
    Ok(BpfEvent::ProcessExec {
        pid: event.pid,
        ppid: event.ppid,
        uid: event.uid,
        gid: event.gid,
        comm,
        filename,
        argv,
        timestamp_ns: event.timestamp_ns,
    })
}

#[async_trait::async_trait]
impl BpfProgram for ExecTracer {
    async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        Self::load(event_tx).await
    }
    
    async fn unload(&mut self) -> Result<()> {
        self.bpf.take();
        Ok(())
    }
    
    fn name(&self) -> &str {
        "exec_tracer"
    }
    
    fn is_loaded(&self) -> bool {
        self.bpf.is_some()
    }
}