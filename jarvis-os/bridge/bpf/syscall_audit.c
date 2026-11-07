// syscall_audit.c - Syscall auditor using raw tracepoints
// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause

#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

struct syscall_event {
    __u32 pid;
    __u32 tid;
    __s64 syscall_nr;
    __u64 args[6];
    __s64 ret;
    __u64 timestamp_ns;
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} syscall_events SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 512);
    __type(key, __s64);
    __type(value, __u8);
} syscall_filter SEC(".maps");

// sys_enter
SEC("tp/raw_syscalls/sys_enter")
int trace_sys_enter(struct bpf_raw_tracepoint_args *ctx) {
    __u64 pid_tgid = bpf_get_current_pid_tgid();
    struct syscall_event event = {};
    event.pid = pid_tgid >> 32;
    event.tid = (__u32)pid_tgid;
    event.syscall_nr = ctx->args[1];
    event.timestamp_ns = bpf_ktime_get_ns();
    
    // Check filter
    __u8 *filtered = bpf_map_lookup_elem(&syscall_filter, &event.syscall_nr);
    if (filtered && *filtered) {
        // Capture args
        #pragma unroll
        for (int i = 0; i < 6; i++) {
            event.args[i] = ctx->args[i + 2];
        }
        
        bpf_perf_event_output(ctx, &syscall_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    }
    
    return 0;
}

// sys_exit
SEC("tp/raw_syscalls/sys_exit")
int trace_sys_exit(struct bpf_raw_tracepoint_args *ctx) {
    __u64 pid_tgid = bpf_get_current_pid_tgid();
    struct syscall_event event = {};
    event.pid = pid_tgid >> 32;
    event.tid = (__u32)pid_tgid;
    event.syscall_nr = ctx->args[1];
    event.ret = ctx->args[0];
    event.timestamp_ns = bpf_ktime_get_ns();
    
    __u8 *filtered = bpf_map_lookup_elem(&syscall_filter, &event.syscall_nr);
    if (filtered && *filtered) {
        bpf_perf_event_output(ctx, &syscall_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    }
    
    return 0;
}

char LICENSE[] SEC("license") = "GPL";