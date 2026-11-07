//! LSM (Linux Security Module) Hooks using eBPF
//!
//! Implements Mandatory Access Control at kernel level

use crate::bpf::{BpfEvent, BpfProgram};
use anyhow::Result;
use aya::{maps::HashMap, programs::Lsm, Bpf};
use aya_log::BpfLogger;
use std::sync::Arc;
use tokio::sync::mpsc;

const LSM_HOOKS_BPF: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/lsm_hooks.bpf.o"));

pub struct LsmHooks {
    bpf: Option<Bpf>,
    event_tx: mpsc::UnboundedSender<BpfEvent>,
    policy_map: Arc<std::sync::Mutex<std::collections::HashMap<String, Vec<String>>>>,
}

impl LsmHooks {
    pub async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        let mut bpf = Bpf::load(LSM_HOOKS_BPF)?;
        BpfLogger::init(&mut bpf)?;
        
        // Attach LSM hooks
        let hooks = [
            "bprm_check_security",      // execve security check
            "file_open",                // file open check
            "file_permission",          // file permission check
            "inode_create",             // inode creation
            "inode_unlink",             // inode unlink
            "inode_rename",             // inode rename
            "inode_mkdir",              // directory creation
            "inode_rmdir",              // directory removal
            "inode_setattr",            // attribute changes
            "socket_create",            // socket creation
            "socket_connect",           // socket connect
            "socket_bind",              // socket bind
            "task_alloc",               // task allocation
            "task_free",                // task free
            "cred_prepare",             // credential preparation
            "cred_commit",              // credential commit
            "kernel_read_file",         // kernel module loading
            "kernel_post_read_file",    // post module read
            "mmap_file",                // memory mapping
            "mprotect",                 // memory protection changes
        ];
        
        for hook in hooks {
            if let Some(prog) = bpf.program_mut(hook) {
                let mut lsm: Lsm = prog.try_into()?;
                lsm.attach()?;
            }
        }
        
        Ok(Self {
            bpf: Some(bpf),
            event_tx,
            policy_map: Arc::new(std::sync::Mutex::new(std::collections::HashMap::new())),
        })
    }
    
    pub fn add_rule(&self, subject: &str, object: &str, permissions: Vec<String>) {
        self.policy_map.lock().unwrap().insert(
            format!("{}->{}", subject, object),
            permissions
        );
        // Update BPF policy map
    }
    
    pub fn remove_rule(&self, subject: &str, object: &str) {
        self.policy_map.lock().unwrap().remove(&format!("{}->{}", subject, object));
    }
}

#[async_trait::async_trait]
impl BpfProgram for LsmHooks {
    async fn load(event_tx: mpsc::UnboundedSender<BpfEvent>) -> Result<Self> {
        Self::load(event_tx).await
    }
    
    async fn unload(&mut self) -> Result<()> {
        self.bpf.take();
        Ok(())
    }
    
    fn name(&self) -> &str {
        "lsm_hooks"
    }
    
    fn is_loaded(&self) -> bool {
        self.bpf.is_some()
    }
}