// exec_tracer.c - Process execution tracer
// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause

#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#define MAX_ARGV 16
#define MAX_ARG_LEN 256
#define MAX_FILENAME 256

struct exec_event {
    __u32 pid;
    __u32 ppid;
    __u32 uid;
    __u32 gid;
    __u64 timestamp_ns;
    char comm[TASK_COMM_LEN];
    char filename[MAX_FILENAME];
    char argv[MAX_ARGV][MAX_ARG_LEN];
    int argc;
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} exec_events SEC(".maps");

SEC("tracepoint/syscalls/sys_enter_execve")
int trace_execve(struct trace_event_raw_sys_enter *ctx) {
    struct exec_event event = {};
    __u64 pid_tgid = bpf_get_current_pid_tgid();
    event.pid = pid_tgid >> 32;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    // Get task info
    struct task_struct *task = (struct task_struct *)bpf_get_current_task();
    event.ppid = BPF_CORE_READ(task, real_parent, tgid);
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.gid = bpf_get_current_uid_gid() & 0xFFFFFFFF;
    bpf_get_current_comm(&event.comm, sizeof(event.comm));
    
    // Get filename
    const char *filename = (const char *)ctx->args[0];
    bpf_probe_read_user_str(&event.filename, sizeof(event.filename), filename);
    
    // Get argv
    const char *const *argv = (const char *const *)ctx->args[1];
    event.argc = 0;
    for (int i = 0; i < MAX_ARGV; i++) {
        const char *arg;
        if (bpf_probe_read_user(&arg, sizeof(arg), &argv[i]) != 0 || !arg)
            break;
        if (bpf_probe_read_user_str(&event.argv[i], sizeof(event.argv[i]), arg) != 0)
            break;
        event.argc++;
    }
    
    bpf_perf_event_output(ctx, &exec_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    return 0;
}

SEC("tracepoint/syscalls/sys_enter_execveat")
int trace_execveat(struct trace_event_raw_sys_enter *ctx) {
    struct exec_event event = {};
    __u64 pid_tgid = bpf_get_current_pid_tgid();
    event.pid = pid_tgid >> 32;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    struct task_struct *task = (struct task_struct *)bpf_get_current_task();
    event.ppid = BPF_CORE_READ(task, real_parent, tgid);
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.gid = bpf_get_current_uid_gid() & 0xFFFFFFFF;
    bpf_get_current_comm(&event.comm, sizeof(event.comm));
    
    // Get filename (fd, path, flags, argv, envp)
    const char *filename = (const char *)ctx->args[1];
    bpf_probe_read_user_str(&event.filename, sizeof(event.filename), filename);
    
    const char *const *argv = (const char *const *)ctx->args[3];
    event.argc = 0;
    for (int i = 0; i < MAX_ARGV; i++) {
        const char *arg;
        if (bpf_probe_read_user(&arg, sizeof(arg), &argv[i]) != 0 || !arg)
            break;
        if (bpf_probe_read_user_str(&event.argv[i], sizeof(event.argv[i]), arg) != 0)
            break;
        event.argc++;
    }
    
    bpf_perf_event_output(ctx, &exec_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    return 0;
}

SEC("tracepoint/syscalls/sys_exit_execve")
int trace_exit_execve(struct trace_event_raw_sys_exit *ctx) {
    // Could capture return value here
    return 0;
}

char LICENSE[] SEC("license") = "GPL";