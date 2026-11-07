// build.rs - Build script for eBPF programs
// Place in jarvis-os/bridge/

use aya_build::{cargo_metadata, Toolchain};

fn main() {
    // Detect toolchain
    let toolchain = Toolchain::default();
    
    // Build eBPF programs
    let bpf_dir = std::path::Path::new("bpf");
    
    // List of eBPF programs to build
    let programs = [
        "exec_tracer",
        "net_filter", 
        "fs_monitor",
        "syscall_audit",
        "lsm_hooks",
    ];
    
    for prog in &programs {
        let prog_path = bpf_dir.join(format!("{}.c", prog));
        if prog_path.exists() {
            println!("cargo:rerun-if-changed={}", prog_path.display());
            
            // Compile with aya-build
            aya_build::build_ebpf(prog, None, Some(toolchain.clone()))
                .expect(&format!("Failed to build eBPF program: {}", prog));
        }
    }
    
    // Also watch for header changes
    println!("cargo:rerun-if-changed=bpf/");
    println!("cargo:rerun-if-changed=build.rs");
}