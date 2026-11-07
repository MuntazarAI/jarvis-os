#!/bin/bash
# Generate vmlinux.h for eBPF development
# Run on target kernel

set -euo pipefail

OUTPUT_DIR="${1:-bpf}"
KERNEL_VERSION=$(uname -r)

mkdir -p "$OUTPUT_DIR"

echo "Generating vmlinux.h for kernel $KERNEL_VERSION..."

# Method 1: Using bpftool (preferred)
if command -v bpftool &> /dev/null; then
    bpftool btf dump file /sys/kernel/btf/vmlinux format c > "$OUTPUT_DIR/vmlinux.h"
    echo "Generated vmlinux.h using bpftool"
    exit 0
fi

# Method 2: Using pahole
if command -v pahole &> /dev/null; then
    pahole -C vmlinux -E -o "$OUTPUT_DIR/vmlinux.h" /sys/kernel/btf/vmlinux 2>/dev/null || true
    if [[ -f "$OUTPUT_DIR/vmlinux.h" ]]; then
        echo "Generated vmlinux.h using pahole"
        exit 0
    fi
fi

# Method 3: Using kernel headers (fallback)
echo "Warning: Could not generate vmlinux.h from BTF"
echo "Creating minimal vmlinux.h from kernel headers..."

cat > "$OUTPUT_DIR/vmlinux.h" << 'EOF'
// Minimal vmlinux.h for eBPF development
// Generated from kernel headers - missing BTF info

#ifndef __VMLINUX_H
#define __VMLINUX_H

#include <linux/types.h>
#include <linux/errno.h>
#include <linux/fs.h>
#include <linux/sched.h>
#include <linux/cred.h>
#include <linux/path.h>
#include <linux/dcache.h>
#include <linux/inode.h>
#include <linux/file.h>
#include <linux/binfmts.h>
#include <linux/lsm_hooks.h>
#include <linux/tcp.h>
#include <linux/udp.h>
#include <linux/ip.h>
#include <linux/if_ether.h>
#include <linux/netdevice.h>
#include <linux/skbuff.h>
#include <linux/ptrace.h>
#include <linux/version.h>
#include <linux/bpf.h>
#include <linux/filter.h>
#include <linux/perf_event.h>
#include <linux/tracepoint.h>
#include <linux/syscalls.h>
#include <linux/trace_events.h>
#include <linux/kprobes.h>
#include <linux/uprobes.h>
#include <linux/namei.h>
#include <linux/mount.h>
#include <linux/nsproxy.h>
#include <linux/pid.h>
#include <linux/signal.h>
#include <linux/security.h>
#include <linux/capability.h>
#include <linux/audit.h>
#include <linux/ima.h>
#include <linux/evm.h>
#include <linux/key.h>
#include <linux/key-type.h>
#include <linux/user_namespace.h>
#include <linux/uidgid.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/mman.h>
#include <linux/mm.h>
#include <linux/swap.h>
#include <linux/pagemap.h>
#include <linux/writeback.h>
#include <linux/buffer_head.h>
#include <linux/blkdev.h>
#include <linux/genhd.h>
#include <linux/hdreg.h>
#include <linux/scatterlist.h>
#include <linux/dma-mapping.h>
#include <linux/dma-buf.h>
#include <linux/dma-fence.h>
#include <linux/sync_file.h>
#include <linux/dma-resv.h>
#include <linux/dma-heap.h>
#include <linux/vmalloc.h>
#include <linux/slab.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/init.h>
#include <linux/kobject.h>
#include <linux/device.h>
#include <linux/platform_device.h>
#include <linux/of.h>
#include <linux/of_device.h>
#include <linux/acpi.h>
#include <linux/pci.h>
#include <linux/usb.h>
#include <linux/input.h>
#include <linux/hid.h>
#include <linux/gpio.h>
#include <linux/irq.h>
#include <linux/interrupt.h>
#include <linux/timer.h>
#include <linux/hrtimer.h>
#include <linux/ktime.h>
#include <linux/jiffies.h>
#include <linux/time.h>
#include <linux/timekeeping.h>
#include <linux/clocksource.h>
#include <linux/clockchips.h>
#include <linux/cpu.h>
#include <linux/cpumask.h>
#include <linux/cpufreq.h>
#include <linux/topology.h>
#include <linux/numa.h>
#include <linux/memory.h>
#include <linux/memcontrol.h>
#include <linux/cgroup.h>
#include <linux/cgroup-defs.h>
#include <linux/container_of.h>
#include <linux/list.h>
#include <linux/rbtree.h>
#include <linux/hash.h>
#include <linux/idr.h>
#include <linux/xarray.h>
#include <linux/bitmap.h>
#include <linux/string.h>
#include <linux/kstrtox.h>
#include <linux/err.h>
#include <linux/bug.h>
#include <linux/panic_notifier.h>
#include <linux/reboot.h>
#include <linux/kexec.h>
#include <linux/kallsyms.h>
#include <linux/trace.h>
#include <linux/ftrace.h>
#include <linux/kprobes.h>
#include <linux/uprobes.h>
#include <linux/bpf.h>
#include <linux/bpf_verifier.h>
#include <linux/bpf_lsm.h>
#include <linux/bpf_syscall.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <linux/audit.h>
#include <linux/ptrace.h>
#include <linux/kallsyms.h>
#include <linux/perf_event.h>
#include <linux/hw_breakpoint.h>
#include <linux/debugfs.h>
#include <linux/proc_fs.h>
#include <linux/seq_file.h>
#include <linux/sysfs.h>
#include <linux/kobject.h>
#include <linux/device.h>
#include <linux/module.h>
#include <linux/init.h>
#include <linux/kmod.h>
#include <linux/firmware.h>
#include <linux/elf.h>
#include <linux/binfmts.h>
#include <linux/fs.h>
#include <linux/fcntl.h>
#include <linux/stat.h>
#include <linux/poll.h>
#include <linux/select.h>
#include <linux/eventpoll.h>
#include <linux/signalfd.h>
#include <linux/timerfd.h>
#include <linux/eventfd.h>
#include <linux/aio.h>
#include <linux/io_uring.h>
#include <linux/mman.h>
#include <linux/shm.h>
#include <linux/mqueue.h>
#include <linux/sem.h>
#include <linux/msg.h>
#include <linux/ipc.h>
#include <linux/ipc_namespace.h>
#include <linux/utsname.h>
#include <linux/uts_namespace.h>
#include <linux/user_namespace.h>
#include <linux/pid_namespace.h>
#include <linux/net_namespace.h>
#include <linux/mnt_namespace.h>
#include <linux/cgroup_namespace.h>
#include <linux/time_namespace.h>
#include <linux/nsproxy.h>
#include <linux/sched.h>
#include <linux/sched/task.h>
#include <linux/sched/signal.h>
#include <linux/sched/mm.h>
#include <linux/sched/cputime.h>
#include <linux/sched/clock.h>
#include <linux/sched/debug.h>
#include <linux/sched/stat.h>
#include <linux/sched/autogroup.h>
#include <linux/sched/isolation.h>
#include <linux/sched/loadavg.h>
#include <linux/sched/task_stack.h>
#include <linux/sched/coredump.h>
#include <linux/sched/deadline.h>
#include <linux/sched/fair.h>
#include <linux/sched/rt.h>
#include <linux/sched/idle.h>
#include <linux/sched/topology.h>
#include <linux/sched/clock.h>
#include <linux/sched/signal.h>
#include <linux/sched/clock.h>
#include <linux/sched/debug.h>
#include <linux/sched/stat.h>
#include <linux/sched/autogroup.h>
#include <linux/sched/isolation.h>
#include <linux/sched/loadavg.h>
#include <linux/sched/task_stack.h>
#include <linux/sched/coredump.h>
#include <linux/sched/deadline.h>
#include <linux/sched/fair.h>
#include <linux/sched/rt.h>
#include <linux/sched/idle.h>
#include <linux/sched/topology.h>

#endif /* __VMLINUX_H */
EOF

echo "Created minimal vmlinux.h at $OUTPUT_DIR/vmlinux.h"
echo "Note: For production, use bpftool on target kernel for full BTF support"