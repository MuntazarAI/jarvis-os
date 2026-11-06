//! Network Packet Filter using XDP eBPF
//!
//! Provides L3/L4 filtering, DDoS protection, and traffic analysis

use crate::bpf::{BpfEvent, BpfProgram};
use anyhow::Result;
use aya::{maps::{HashMap, XskMap}, programs::Xdp, Bpf};
use aya_log::BpfLogger;
use std::net::Ipv4Addr;
use std::sync::Arc;
use tokio::sync::mpsc;

const NET_FILTER_BPF: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/net_filter.bpf.o"));

pub struct NetFilter {
    bpf: Option<Bpf>,
    event_tx: mpsc::UnboundedSender<BpfEvent>,
    blocklist: Arc<std::sync::Mutex<Vec<Ipv4Addr>>>,
    ratelimit_buckets: Arc<std::sync::Mutex<std::collections::HashMap<u32, u64>>>,
}

impl NetFilter {
    pub async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        let mut bpf = Bpf::load(NET_FILTER_BPF)?;
        BpfLogger::init(&mut bpf)?;
        
        // Attach XDP program to all interfaces
        let program: &mut Xdp = bpf.program_mut("xdp_filter").unwrap().try_into()?;
        
        // Get interface list and attach
        // In practice, attach to specific interfaces or use generic XDP
        // program.attach("eth0", aya::netlink::XdpFlags::default())?;
        
        // Set up perf event reader for packet logs
        // ... perf event setup similar to exec_tracer
        
        Ok(Self {
            bpf: Some(bpf),
            event_tx,
            blocklist: Arc::new(std::sync::Mutex::new(Vec::new())),
            ratelimit_buckets: Arc::new(std::sync::Mutex::new(std::collections::HashMap::new())),
        })
    }
    
    pub fn block_ip(&self, ip: Ipv4Addr) {
        self.blocklist.lock().unwrap().push(ip);
        // Update BPF map
        if let Some(bpf) = &self.bpf {
            if let Ok(mut map) = bpf.map_mut("BLOCKLIST") {
                let mut hash_map: HashMap<_, u32, u8> = HashMap::try_from(map).unwrap();
                let key = u32::from(ip);
                let _ = hash_map.insert(&key, &1, 0);
            }
        }
    }
    
    pub fn unblock_ip(&self, ip: Ipv4Addr) {
        self.blocklist.lock().unwrap().retain(|&x| x != ip);
        if let Some(bpf) = &self.bpf {
            if let Ok(mut map) = bpf.map_mut("BLOCKLIST") {
                let mut hash_map: HashMap<_, u32, u8> = HashMap::try_from(map).unwrap();
                let key = u32::from(ip);
                let _ = hash_map.remove(&key);
            }
        }
    }
    
    pub fn set_ratelimit(&self, ip: Ipv4Addr, packets_per_sec: u64) {
        self.ratelimit_buckets.lock().unwrap().insert(ip.into(), packets_per_sec);
        if let Some(bpf) = &self.bpf {
            if let Ok(mut map) = bpf.map_mut("RATELIMIT") {
                let mut hash_map: HashMap<_, u32, u64> = HashMap::try_from(map).unwrap();
                let key = u32::from(ip);
                let _ = hash_map.insert(&key, &packets_per_sec, 0);
            }
        }
    }
}

#[async_trait::async_trait]
impl BpfProgram for NetFilter {
    async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        Self::load(event_tx).await
    }
    
    async fn unload(&mut self) -> Result<()> {
        self.bpf.take();
        Ok(())
    }
    
    fn name(&self) -> &str {
        "net_filter"
    }
    
    fn is_loaded(&self) -> bool {
        self.bpf.is_some()
    }
}