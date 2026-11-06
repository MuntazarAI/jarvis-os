//! JARVIS OS Bridge — Unix domain socket IPC between JARVIS intelligence and Linux.
//!
//! Provides typed, versioned, policy-gated access to Linux system resources:
//! /proc, /sys, udev, Netlink, D-Bus, journald, process/resource management,
//! hardware discovery, network information, system logs, service inspection.
//!
//! All operations are read-only by default. Any state-changing operation
//! requires explicit PolicyEngine approval via the JARVIS intelligence layer.

pub mod protocol;
pub mod server;
pub mod modules;
pub mod config;

use anyhow::Result;
use clap::Parser;
use std::path::PathBuf;
use tracing::{info, warn};

#[derive(Parser, Debug)]
#[command(name = "jarvis-os-bridge", about = "JARVIS-OS System Bridge")]
pub struct Cli {
    /// Path to the Unix domain socket
    #[arg(long, default_value = "/run/jarvis-os/bridge.sock")]
    pub socket: PathBuf,

    /// Path to configuration file
    #[arg(long, default_value = "/etc/jarvis-os/bridge.toml")]
    pub config: PathBuf,

    /// Enable verbose logging
    #[arg(short, long)]
    pub verbose: bool,

    /// Run once and exit (for testing)
    #[arg(long)]
    pub once: bool,
}

#[tokio::main]
pub async fn main() -> Result<()> {
    let cli = Cli::parse();

    // Initialize logging
    let filter = if cli.verbose {
        "jarvis_os_bridge=debug,tower_http=debug"
    } else {
        "jarvis_os_bridge=info,warn"
    };
    tracing_subscriber::fmt()
        .with_env_filter(filter)
        .init();

    info!("Starting JARVIS-OS Bridge v{}", env!("CARGO_PKG_VERSION"));
    info!("Socket path: {}", cli.socket.display());
    info!("Config path: {}", cli.config.display());

    // Load configuration
    let cfg = match config::Config::load(&cli.config) {
        Ok(c) => c,
        Err(e) => {
            warn!("Failed to load config: {}, using defaults", e);
            config::Config::default()
        }
    };

    // Ensure socket directory exists
    if let Some(parent) = cli.socket.parent() {
        std::fs::create_dir_all(parent)?;
    }

    // Remove stale socket
    if cli.socket.exists() {
        std::fs::remove_file(&cli.socket)?;
    }

    // Create and run the bridge server
    let mut server = server::BridgeServer::new(cli.socket, cfg).await?;
    server.run().await?;

    Ok(())
}