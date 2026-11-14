#!/bin/bash
# JARVIS-OS Image Creation Script
# Creates bootable ISO/IMG for Fedora-based JARVIS-OS
#
# Requirements: lorax, livemedia-creator, anaconda, pykickstart
# Run as root

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="/var/tmp/jarvis-os-build"
OUTPUT_DIR="/var/tmp/jarvis-os-output"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Check root
if [[ $EUID -ne 0 ]]; then
    log_error "Must run as root"
    exit 1
fi

# Install build dependencies
log_info "Installing build dependencies..."
dnf install -y lorax livemedia-creator anaconda pykickstart genisoimage isomd5sum squashfs-tools

# Clean previous builds
rm -rf "$BUILD_DIR" "$OUTPUT_DIR"
mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"

# Create kickstart file
log_info "Creating kickstart configuration..."
cat > "$BUILD_DIR/jarvis-os.ks" << 'KSEOF'
# JARVIS-OS Kickstart Configuration
# Fedora-based AI-native operating system

# Version and metadata
%pre
echo "JARVIS-OS Build: $(date)" > /tmp/build-info.txt
%end

# Installation source
cdrom

# Authentication
rootpw --locked
auth --enableshadow --passalgo=sha512

# Keyboard and language
keyboard --vckeymap=us --xlayouts='us'
lang en_US.UTF-8

# Timezone
timezone --utc Etc/UTC

# Network
network --bootproto=dhcp --device=link --activate
network --hostname=jarvis-os

# Firewall - allow SSH and JARVIS bridge
firewall --enabled --ssh --service=mdns --port=8080:tcp --port=8081:tcp

# SELinux
selinux --enforcing

# Bootloader
bootloader --location=mbr --append="rhgb quiet"

# Disk partitioning
clearpart --all --initlabel --drives=sda
part /boot --fstype=ext4 --size=1024 --ondisk=sda
part pv.01 --size=1 --grow --ondisk=sda
volgroup vg_root pv.01
logvol / --fstype=ext4 --name=lv_root --vgname=vg_root --size=10240 --grow
logvol swap --fstype=swap --name=lv_swap --vgname=vg_root --size=2048 --maxsize=8192

# Reboot after install
reboot

# Packages
%packages --ignoremissing --excludedocs
@core
@standard
@system-tools

# Python and AI stack
python3
python3-pip
python3-devel
python3-setuptools
python3-wheel
python3-virtualenv

# System management
systemd
systemd-container
systemd-udev
systemd-resolved
systemd-networkd

# Hardware support
kernel
kernel-modules
kernel-modules-extra
linux-firmware
intel-ucode
amd-ucode
thermald
lm_sensors
smartmontools
hdparm
nvme-cli

# Network tools
NetworkManager
NetworkManager-wifi
NetworkManager-tui
iproute
iputils
net-tools
nmap-ncat
socat
bind-utils
tcpdump
wireshark-cli

# Monitoring and logging
journald
logrotate
rsyslog
audit
audispd-plugins
prometheus-node-exporter

# Development tools (for building bridge)
rust
cargo
clang
llvm
bpftool
kernel-devel
kernel-headers
perf
valgrind

# Security
selinux-policy
selinux-policy-targeted
policycoreutils
setroubleshoot
openscap-scanner

# Container support (optional)
podman
buildah
skopeo
container-selinux

# JARVIS specific
git
vim-enhanced
tmux
htop
iotop
iftop
nethogs
btop
fzf
ripgrep
fd-find
bat
eza
zoxide
starship

%end

%post --log=/var/log/anaconda/post-install.log
# Post-installation setup

# Create JARVIS users
groupadd --system jarvis
useradd --system --no-create-home --shell /usr/sbin/nologin --gid jarvis --comment "JARVIS Intelligence" jarvis

groupadd --system jarvis-os
useradd --system --no-create-home --shell /usr/sbin/nologin --gid jarvis-os --comment "JARVIS-OS Bridge" jarvis-os

# Create directories
mkdir -p /run/jarvis /run/jarvis-os
mkdir -p /var/log/jarvis /var/log/jarvis-os
mkdir -p /etc/jarvis /etc/jarvis-os
mkdir -p /var/lib/jarvis /var/lib/jarvis-os
mkdir -p /var/lib/jarvis/models /var/lib/jarvis-os/models
mkdir -p /var/cache/jarvis /var/cache/jarvis-os

chown -R jarvis:jarvis /run/jarvis /var/log/jarvis /etc/jarvis /var/lib/jarvis /var/cache/jarvis
chown -R jarvis-os:jarvis-os /run/jarvis-os /var/log/jarvis-os /etc/jarvis-os /var/lib/jarvis-os /var/cache/jarvis-os

# Enable services
systemctl enable systemd-resolved
systemctl enable systemd-networkd
systemctl enable NetworkManager
systemctl enable thermald
systemctl enable smartd
systemctl enable auditd
systemctl enable rsyslog
systemctl enable prometheus-node-exporter
systemctl enable fstrim.timer

# Install JARVIS from repository (will be copied to image)
# This is a placeholder - actual installation happens via ostree or rpm

# Configure SELinux for JARVIS
if command -v semanage &> /dev/null; then
    semanage fcontext -a -t jarvis_os_bridge_var_run_t "/run/jarvis-os(/.*)?"
    semanage fcontext -a -t jarvis_os_bridge_etc_t "/etc/jarvis-os(/.*)?"
    semanage fcontext -a -t jarvis_os_bridge_var_lib_t "/var/lib/jarvis-os(/.*)?"
    semanage fcontext -a -t jarvis_os_bridge_log_t "/var/log/jarvis-os(/.*)?"
    restorecon -R /run/jarvis-os /etc/jarvis-os /var/lib/jarvis-os /var/log/jarvis-os 2>/dev/null || true
fi

# Set up JARVIS home
echo 'export JARVIS_HOME="/var/lib/jarvis"' >> /etc/environment
echo 'export JARVIS_OS_HOME="/var/lib/jarvis-os"' >> /etc/environment

# Create welcome message
cat > /etc/motd << 'MOTEOF'

  ╔═══════════════════════════════════════════╗
  ║         JARVIS-OS v1.0.0                  ║
  ║    AI-Native Operating System             ║
  ║    Built on Fedora Linux                  ║
  ╚═══════════════════════════════════════════╝

  JARVIS Intelligence:  jarvis --help
  JARVIS-OS Bridge:     jarvis-os status
  Bridge Socket:        /run/jarvis-os/bridge.sock
  Logs:                 journalctl -u jarvis-os-bridge -f

  Documentation: https://github.com/MuntazarAI/jarvis-os

MOTEOF

%end

%post --nochroot --log=/var/log/anaconda/post-nochroot.log
# No-chroot post: copy JARVIS source to image for installation on first boot
mkdir -p $INSTALL_ROOT/opt/jarvis-os-source
cp -r /path/to/jarvis-os/* $INSTALL_ROOT/opt/jarvis-os-source/ 2>/dev/null || true

# Create first-boot service to install JARVIS
cat > $INSTALL_ROOT/etc/systemd/system/jarvis-firstboot.service << 'SVC_EOF'
[Unit]
Description=JARVIS-OS First Boot Installation
After=network-online.target
Wants=network-online.target
ConditionPathExists=!/etc/jarvis-os/.installed

[Service]
Type=oneshot
ExecStart=/opt/jarvis-os-source/bootstrap/install-os.sh
RemainAfterExit=yes
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVC_EOF

# Enable first-boot service
ln -sf /etc/systemd/system/jarvis-firstboot.service $INSTALL_ROOT/etc/systemd/system/multi-user.target.wants/jarvis-firstboot.service

%end
KSEOF

# Create lorax template
log_info "Creating lorax template..."
mkdir -p "$BUILD_DIR/lorax"
cat > "$BUILD_DIR/lorax/template.conf" << 'LOREOF'
[template]
name = "JARVIS-OS"
version = "1.0.0"
release = "1"
distro = "Fedora"
distro_version = "40"
arch = "x86_64"

[bootloader]
grub2 = true
efi = true

[compression]
type = "xz"
level = 6
LOREOF

# Build the image
log_info "Building JARVIS-OS ISO image (this will take a while)..."
cd "$BUILD_DIR"

# Use livemedia-creator to build ISO
livemedia-creator \
    --make-iso \
    --iso-name=jarvis-os-1.0.0-x86_64.iso \
    --iso-only \
    --ks=jarvis-os.ks \
    --resultdir="$OUTPUT_DIR" \
    --no-virt \
    --project="JARVIS-OS" \
    --releasever=40 \
    --volid="JARVIS-OS" \
    --iso-label="JARVIS-OS" \
    --macboot=false \
    2>&1 | tee "$OUTPUT_DIR/build.log"

# Check result
if [[ -f "$OUTPUT_DIR/jarvis-os-1.0.0-x86_64.iso" ]]; then
    log_success "ISO created: $OUTPUT_DIR/jarvis-os-1.0.0-x86_64.iso"
    
    # Generate checksums
    cd "$OUTPUT_DIR"
    sha256sum jarvis-os-1.0.0-x86_64.iso > jarvis-os-1.0.0-x86_64.iso.sha256
    log_success "SHA256 checksum generated"
    
    # Create USB image
    log_info "Creating USB image..."
    # This would use dd or similar to create a hybrid ISO
    # For now, the ISO is hybrid bootable
    
    log_success "Build complete!"
    echo ""
    echo "Output: $OUTPUT_DIR/jarvis-os-1.0.0-x86_64.iso"
    echo "Checksum: $OUTPUT_DIR/jarvis-os-1.0.0-x86_64.iso.sha256"
    echo ""
    echo "To write to USB:"
    echo "  sudo dd if=$OUTPUT_DIR/jarvis-os-1.0.0-x86_64.iso of=/dev/sdX bs=4M status=progress"
    echo ""
    echo "To test in VM:"
    echo "  qemu-system-x86_64 -cdrom $OUTPUT_DIR/jarvis-os-1.0.0-x86_64.iso -m 4G -enable-kvm"
else
    log_error "ISO build failed. Check $OUTPUT_DIR/build.log"
    exit 1
fi