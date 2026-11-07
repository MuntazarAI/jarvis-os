// net_filter.c - XDP network packet filter
// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause

#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/tcp.h>
#include <linux/udp.h>

#define MAX_BLOCKLIST 1024
#define MAX_RATELIMIT 1024

struct blocklist_entry {
    __u32 ip;
    __u8 enabled;
};

struct ratelimit_entry {
    __u32 ip;
    __u64 packets_per_sec;
    __u64 last_update;
    __u64 count;
};

struct packet_event {
    __u32 ifindex;
    __u32 src_ip;
    __u32 dst_ip;
    __u16 src_port;
    __u16 dst_port;
    __u8 protocol;
    __u8 action; // 0=allow, 1=drop, 2=rate_limit
    __u64 timestamp_ns;
};

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, MAX_BLOCKLIST);
    __type(key, __u32);
    __type(value, struct blocklist_entry);
} blocklist SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, MAX_RATELIMIT);
    __type(key, __u32);
    __type(value, struct ratelimit_entry);
} ratelimit SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_ARRAY);
    __uint(key_size, sizeof(__u32));
    __uint(value_size, sizeof(__u32));
} packet_events SEC(".maps");

static __always_inline int check_blocklist(__u32 ip) {
    struct blocklist_entry *entry = bpf_map_lookup_elem(&blocklist, &ip);
    if (entry && entry->enabled)
        return 1;
    return 0;
}

static __always_inline int check_ratelimit(__u32 ip) {
    struct ratelimit_entry *entry = bpf_map_lookup_elem(&ratelimit, &ip);
    if (!entry)
        return 0;
    
    __u64 now = bpf_ktime_get_ns();
    if (now - entry->last_update > 1000000000) { // 1 second window
        entry->count = 1;
        entry->last_update = now;
        return 0;
    }
    
    if (entry->count >= entry->packets_per_sec)
        return 1;
    
    entry->count++;
    return 0;
}

SEC("xdp")
int xdp_filter(struct xdp_md *ctx) {
    void *data_end = (void *)(long)ctx->data_end;
    void *data = (void *)(long)ctx->data;
    
    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return XDP_PASS;
    
    if (eth->h_proto != bpf_htons(ETH_P_IP))
        return XDP_PASS;
    
    struct iphdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end)
        return XDP_PASS;
    
    __u32 src_ip = ip->saddr;
    __u32 dst_ip = ip->daddr;
    __u8 protocol = ip->protocol;
    __u16 src_port = 0, dst_port = 0;
    
    if (protocol == IPPROTO_TCP) {
        struct tcphdr *tcp = (void *)ip + (ip->ihl * 4);
        if ((void *)(tcp + 1) <= data_end) {
            src_port = bpf_ntohs(tcp->source);
            dst_port = bpf_ntohs(tcp->dest);
        }
    } else if (protocol == IPPROTO_UDP) {
        struct udphdr *udp = (void *)ip + (ip->ihl * 4);
        if ((void *)(udp + 1) <= data_end) {
            src_port = bpf_ntohs(udp->source);
            dst_port = bpf_ntohs(udp->dest);
        }
    }
    
    __u8 action = 0; // allow
    
    if (check_blocklist(src_ip) || check_blocklist(dst_ip))
        action = 1; // drop
    else if (check_ratelimit(src_ip))
        action = 2; // rate limit
    
    // Log event
    struct packet_event event = {
        .ifindex = ctx->ingress_ifindex,
        .src_ip = src_ip,
        .dst_ip = dst_ip,
        .src_port = src_port,
        .dst_port = dst_port,
        .protocol = protocol,
        .action = action,
        .timestamp_ns = bpf_ktime_get_ns(),
    };
    
    bpf_perf_event_output(ctx, &packet_events, BPF_F_CURRENT_CPU, &event, sizeof(event));
    
    if (action == 1)
        return XDP_DROP;
    
    return XDP_PASS;
}

char LICENSE[] SEC("license") = "GPL";