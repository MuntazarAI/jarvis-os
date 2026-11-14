// lsm_hooks.c - LSM hooks for MAC enforcement
// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause

#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

#define MAX_POLICY_RULES 1024

struct policy_rule {
    __u32 subject_uid;
    __u32 object_ino;
    __u32 permissions; // bitmask
    __u8 enabled;
};

struct security_event {
    __u32 pid;
    __u32 uid;
    __u32 hook_id; // 0=bprm, 1=file_open, 2=file_perm, etc.
    __s32 result;
    __u64 timestamp_ns;
    char details[128];
};

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, MAX_POLICY_RULES);
    __type(key, __u64); // combined key: (uid << 32) | ino
    __type(value, struct policy_rule);
} policy_rules SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} security_events SEC(".maps");

static __always_inline int check_policy(__u32 uid, __u32 ino, __u32 required_perm) {
    __u64 key = ((__u64)uid << 32) | ino;
    struct policy_rule *rule = bpf_map_lookup_elem(&policy_rules, &key);
    if (!rule || !rule->enabled)
        return 1; // Allow if no rule (default allow for now)
    
    if (rule->permissions & required_perm)
        return 0; // Allow
    
    return -1; // Deny
}

static __always_inline void emit_security_event(int hook_id, int result, const char *details) {
    struct security_event event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.uid = bpf_get_current_uid_gid() >> 32;
    event.hook_id = hook_id;
    event.result = result;
    event.timestamp_ns = bpf_ktime_get_ns();
    __builtin_memcpy(event.details, details, sizeof(event.details) - 1);
    
    bpf_perf_event_output(ctx, &security_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
}

// bprm_check_security - execve security check
SEC("lsm/bprm_check_security")
int BPF_PROG(bprm_check_security, struct linux_binprm *bprm) {
    struct file *file = bprm->file;
    struct inode *inode = file->f_inode;
    __u32 ino = BPF_CORE_READ(inode, i_ino);
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    
    int result = check_policy(uid, ino, 1); // EXECUTE permission
    emit_security_event(0, result, "execve check");
    
    return result;
}

// file_open
SEC("lsm/file_open")
int BPF_PROG(file_open, struct file *file) {
    struct inode *inode = file->f_inode;
    __u32 ino = BPF_CORE_READ(inode, i_ino);
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    
    int result = check_policy(uid, ino, 2); // READ permission
    emit_security_event(1, result, "file open");
    
    return result;
}

// file_permission
SEC("lsm/file_permission")
int BPF_PROG(file_permission, struct file *file, int mask) {
    struct inode *inode = file->f_inode;
    __u32 ino = BPF_CORE_READ(inode, i_ino);
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    
    __u32 required = 0;
    if (mask & MAY_READ) required |= 2;
    if (mask & MAY_WRITE) required |= 4;
    if (mask & MAY_EXEC) required |= 1;
    
    int result = check_policy(uid, ino, required);
    emit_security_event(2, result, "file permission");
    
    return result;
}

// inode_create
SEC("lsm/inode_create")
int BPF_PROG(inode_create, struct inode *dir, struct dentry *dentry, umode_t mode) {
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    __u32 ino = BPF_CORE_READ(dir, i_ino);
    
    int result = check_policy(uid, ino, 8); // CREATE permission
    emit_security_event(3, result, "inode create");
    
    return result;
}

// inode_unlink
SEC("lsm/inode_unlink")
int BPF_PROG(inode_unlink, struct inode *dir, struct dentry *dentry) {
    struct inode *inode = dentry->d_inode;
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    __u32 ino = inode ? BPF_CORE_READ(inode, i_ino) : 0;
    
    int result = check_policy(uid, ino, 16); // DELETE permission
    emit_security_event(4, result, "inode unlink");
    
    return result;
}

// inode_rename
SEC("lsm/inode_rename")
int BPF_PROG(inode_rename, struct inode *old_dir, struct dentry *old_dentry, struct inode *new_dir, struct dentry *new_dentry) {
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    __u32 ino = BPF_CORE_READ(old_dir, i_ino);
    
    int result = check_policy(uid, ino, 32); // RENAME permission
    emit_security_event(5, result, "inode rename");
    
    return result;
}

// inode_mkdir
SEC("lsm/inode_mkdir")
int BPF_PROG(inode_mkdir, struct inode *dir, struct dentry *dentry, umode_t mode) {
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    __u32 ino = BPF_CORE_READ(dir, i_ino);
    
    int result = check_policy(uid, ino, 8); // CREATE permission
    emit_security_event(6, result, "inode mkdir");
    
    return result;
}

// inode_rmdir
SEC("lsm/inode_rmdir")
int BPF_PROG(inode_rmdir, struct inode *dir, struct dentry *dentry) {
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    __u32 ino = BPF_CORE_READ(dir, i_ino);
    
    int result = check_policy(uid, ino, 16); // DELETE permission
    emit_security_event(7, result, "inode rmdir");
    
    return result;
}

// socket_create
SEC("lsm/socket_create")
int BPF_PROG(socket_create, int family, int type, int protocol, int kern) {
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    
    int result = check_policy(uid, 0, 64); // NETWORK permission
    emit_security_event(8, result, "socket create");
    
    return result;
}

// cred_prepare
SEC("lsm/cred_prepare")
int BPF_PROG(cred_prepare, struct cred *new, const struct cred *old, gfp_t gfp) {
    __u32 uid = bpf_get_current_uid_gid() >> 32;
    
    int result = check_policy(uid, 0, 128); // CRED permission
    emit_security_event(9, result, "cred prepare");
    
    return result;
}

char LICENSE[] SEC("license") = "GPL";