// fs_monitor.c - Filesystem monitor using fentry/fexit
// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause

#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#define MAX_PATH 256

struct fs_event {
    __u32 pid;
    __u32 uid;
    __u8 operation; // 0=open, 1=read, 2=write, 3=unlink, 4=rename, 5=mkdir, 6=rmdir, 7=chmod, 8=chown, 9=statx, 10=permission
    __s32 result;
    __u64 timestamp_ns;
    char path[MAX_PATH];
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} fs_events SEC(".maps");

static __always_inline void emit_fs_event(int op, struct file *file, int ret) {
    struct fs_event event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.operation = op;
    event.result = ret;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    if (file) {
        struct path path = BPF_CORE_READ(file, f_path);
        struct dentry *dentry = BPF_CORE_READ(path, dentry);
        bpf_probe_read_kernel_str(&event.path, sizeof(event.path), BPF_CORE_READ(dentry, d_name.name));
    }
    
    bpf_perf_event_output(ctx, &fs_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
}

// vfs_open
SEC("fentry/vfs_open")
int BPF_PROG(vfs_open_enter, struct path *path, struct file *file, struct cred *cred) {
    // Store file pointer for exit
    return 0;
}

SEC("fexit/vfs_open")
int BPF_PROG(vfs_open_exit, struct path *path, struct file *file, struct cred *cred, int ret) {
    emit_fs_event(0, file, ret);
    return 0;
}

// vfs_read
SEC("fexit/vfs_read")
int BPF_PROG(vfs_read_exit, struct file *file, char __user *buf, size_t count, loff_t *pos, ssize_t ret) {
    emit_fs_event(1, file, ret);
    return 0;
}

// vfs_write
SEC("fexit/vfs_write")
int BPF_PROG(vfs_write_exit, struct file *file, const char __user *buf, size_t count, loff_t *pos, ssize_t ret) {
    emit_fs_event(2, file, ret);
    return 0;
}

// vfs_unlink
SEC("fexit/vfs_unlink")
int BPF_PROG(vfs_unlink_exit, struct inode *dir, struct dentry *dentry, struct inode **delegated_inode, int ret) {
    struct fs_event event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.operation = 3;
    event.result = ret;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    bpf_probe_read_kernel_str(&event.path, sizeof(event.path), BPF_CORE_READ(dentry, d_name.name));
    
    bpf_perf_event_output(ctx, &fs_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    return 0;
}

// vfs_rename
SEC("fexit/vfs_rename")
int BPF_PROG(vfs_rename_exit, struct inode *old_dir, struct dentry *old_dentry, struct inode *new_dir, struct dentry *new_dentry, unsigned int flags, int ret) {
    struct fs_event event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.operation = 4;
    event.result = ret;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    bpf_probe_read_kernel_str(&event.path, sizeof(event.path), BPF_CORE_READ(old_dentry, d_name.name));
    
    bpf_perf_event_output(ctx, &fs_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    return 0;
}

// vfs_mkdir
SEC("fexit/vfs_mkdir")
int BPF_PROG(vfs_mkdir_exit, struct inode *dir, struct dentry *dentry, umode_t mode, int ret) {
    struct fs_event event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.operation = 5;
    event.result = ret;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    bpf_probe_read_kernel_str(&event.path, sizeof(event.path), BPF_CORE_READ(dentry, d_name.name));
    
    bpf_perf_event_output(ctx, &fs_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    return 0;
}

// vfs_rmdir
SEC("fexit/vfs_rmdir")
int BPF_PROG(vfs_rmdir_exit, struct inode *dir, struct dentry *dentry, int ret) {
    struct fs_event event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.operation = 6;
    event.result = ret;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    bpf_probe_read_kernel_str(&event.path, sizeof(event.path), BPF_CORE_READ(dentry, d_name.name));
    
    bpf_perf_event_output(ctx, &fs_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    return 0;
}

// vfs_chmod
SEC("fexit/vfs_chmod")
int BPF_PROG(vfs_chmod_exit, struct mnt_idmap *idmap, struct dentry *dentry, struct iattr *attr, int ret) {
    struct fs_event event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.operation = 7;
    event.result = ret;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    bpf_probe_read_kernel_str(&event.path, sizeof(event.path), BPF_CORE_READ(dentry, d_name.name));
    
    bpf_perf_event_output(ctx, &fs_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    return 0;
}

// security_inode_permission
SEC("fexit/security_inode_permission")
int BPF_PROG(security_inode_permission_exit, struct inode *inode, int mask, int ret) {
    struct fs_event event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.operation = 10;
    event.result = ret;
    event.timestamp_ns = bpf_ktime_get_ns();
    
    struct dentry *dentry;
    // Get dentry from inode
    bpf_perf_event_output(ctx, &fs_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    return 0;
}

char LICENSE[] SEC("license") = "GPL";