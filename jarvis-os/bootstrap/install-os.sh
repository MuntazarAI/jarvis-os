#!/bin/bash
# JARVIS-OS Full Installation Script
# Run as root: sudo ./install-os.sh
#
# Installs:
# - JARVIS Intelligence (Python package)
# - JARVIS-OS Bridge (Rust system service)
# - Systemd services
# - Configuration
# - SELinux policies
# - User/group setup

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# Configuration
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JARVIS_USER="jarvis"
JARVIS_GROUP="jarvis"
JARVIS_HOME="/var/lib/jarvis"
BRIDGE_USER="jarvis-os"
BRIDGE_GROUP="jarvis-os"
BRIDGE_HOME="/var/lib/jarvis-os"

echo "======================================"
echo "  JARVIS-OS Installation Script"
echo "======================================"
echo ""

# Check root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root"
    exit 1
fi

# Check Fedora
if [[ ! -f /etc/fedora-release ]]; then
    log_warn "This script is designed for Fedora Linux. Proceeding anyway..."
fi

# Check Fedora version
if [[ -f /etc/fedora-release ]]; then
    FEDORA_VERSION=$(grep -oP '\d+' /etc/fedora-release | head -1)
    if [[ "$FEDORA_VERSION" -lt 40 ]]; then
        log_warn "Fedora $FEDORA_VERSION detected. JARVIS-OS is tested on Fedora 40+."
    fi
fi

# Install system dependencies
log_info "Installing system dependencies..."
dnf install -y \
    python3 python3-pip python3-devel \
    rust cargo \
    systemd-devel \
    libseccomp-devel \
    openssl-devel \
    pkgconfig \
    clang \
    llvm \
    bpftool \
    linux-headers-$(uname -r) 2>/dev/null || dnf install -y kernel-devel-$(uname -r)

# Create users and groups
log_info "Creating users and groups..."

for user_group in "$JARVIS_USER:$JARVIS_GROUP" "$BRIDGE_USER:$BRIDGE_GROUP"; do
    user=$(echo $user_group | cut -d: -f1)
    group=$(echo $user_group | cut -d: -f2)
    
    if ! getent group "$group" >/dev/null; then
        groupadd --system "$group"
        log_success "Created group: $group"
    fi
    
    if ! id -u "$user" >/dev/null 2>&1; then
        useradd --system --no-create-home --shell /usr/sbin/nologin \
            --gid "$group" --comment "JARVIS Service" "$user"
        log_success "Created user: $user"
    fi
done

# Create directories
log_info "Creating directories..."
dirs=(
    "/run/jarvis" "/run/jarvis-os"
    "/var/log/jarvis" "/var/log/jarvis-os"
    "/etc/jarvis" "/etc/jarvis-os"
    "/var/lib/jarvis" "/var/lib/jarvis-os"
    "/var/lib/jarvis/models" "/var/lib/jarvis-os/models"
    "/var/cache/jarvis" "/var/cache/jarvis-os"
)

for dir in "${dirs[@]}"; do
    mkdir -p "$dir"
done

# Set ownership
chown -R "$JARVIS_USER:$JARVIS_GROUP" /run/jarvis /var/log/jarvis /etc/jarvis /var/lib/jarvis /var/cache/jarvis
chown -R "$BRIDGE_USER:$BRIDGE_GROUP" /run/jarvis-os /var/log/jarvis-os /etc/jarvis-os /var/lib/jarvis-os /var/cache/jarvis-os

# Build and install JARVIS Python package
log_info "Installing JARVIS Python package..."
cd "$REPO_ROOT"
pip3 install -e . --break-system-packages
log_success "JARVIS Python package installed"

# Build and install JARVIS-OS Bridge
log_info "Building JARVIS-OS Bridge..."
cd "$REPO_ROOT/jarvis-os/bridge"
cargo build --release
cp target/release/jarvis-os-bridge /usr/bin/jarvis-os-bridge
chmod 755 /usr/bin/jarvis-os-bridge
log_success "JARVIS-OS Bridge installed to /usr/bin/jarvis-os-bridge"

# Install systemd services
log_info "Installing systemd services..."

SERVICES=(
    "$REPO_ROOT/jarvis-os/bridge/systemd/jarvis-os-bridge.service"
)

for svc in "${SERVICES[@]}"; do
    if [[ -f "$svc" ]]; then
        cp "$svc" /etc/systemd/system/
        log_success "Installed $(basename "$svc")"
    else
        log_warn "Service file not found: $svc"
    fi
done

systemctl daemon-reload

# Install configuration files
log_info "Installing configuration files..."

CONFIGS=(
    "$REPO_ROOT/jarvis-os/config/bridge.toml:/etc/jarvis-os/bridge.toml"
    "$REPO_ROOT/jarvis/core/config.py:/etc/jarvis/config.py"
)

for config_pair in "${CONFIGS[@]}"; do
    src=$(echo $config_pair | cut -d: -f1)
    dst=$(echo $config_pair | cut -d: -f2)
    if [[ -f "$src" ]]; then
        mkdir -p "$(dirname "$dst")"
        cp "$src" "$dst"
        log_success "Installed config: $dst"
    fi
done

# Set config permissions
chown -R "$BRIDGE_USER:$BRIDGE_GROUP" /etc/jarvis-os
chmod 640 /etc/jarvis-os/bridge.toml
chown -R "$JARVIS_USER:$JARVIS_GROUP" /etc/jarvis
chmod 640 /etc/jarvis/config.py

# Install SELinux policy
log_info "Installing SELinux policy..."
if [[ -f "$REPO_ROOT/jarvis-os/security/jarvis-os.te" ]]; then
    cd "$REPO_ROOT/jarvis-os/security"
    make -f /usr/share/selinux/devel/Makefile jarvis-os.pp
    semodule -i jarvis-os.pp
    log_success "SELinux policy installed"
else
    log_warn "SELinux policy source not found, skipping"
fi

# Enable and start services
log_info "Enabling and starting services..."
systemctl enable jarvis-os-bridge
systemctl start jarvis-os-bridge

# Wait for services
sleep 3

# Check service status
if systemctl is-active --quiet jarvis-os-bridge; then
    log_success "jarvis-os-bridge is running"
else
    log_error "jarvis-os-bridge failed to start"
    systemctl status jarvis-os-bridge --no-pager
    exit 1
fi

# Test bridge connection
log_info "Testing bridge connection..."
if echo '{"jsonrpc":"2.0","method":"bridge.ping","params":{},"id":"test"}' | \
   socat - UNIX-CONNECT:/run/jarvis-os/bridge.sock 2>/dev/null | grep -q '"status":"ok"'; then
    log_success "Bridge communication test passed"
else
    log_warn "Bridge communication test failed (socat may not be installed)"
fi

# Generate initial policy grants
log_info "Generating initial policy grants..."
cat > /etc/jarvis-os/policy-grants.json << 'EOF'
{
  "jarvis-core-system-info": {
    "id": "jarvis-core-system-info",
    "subject": "jarvis-core",
    "resource": "system.info",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  },
  "jarvis-core-cpu-info": {
    "id": "jarvis-core-cpu-info",
    "subject": "jarvis-core",
    "resource": "cpu.info",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  },
  "jarvis-core-memory-info": {
    "id": "jarvis-core-memory-info",
    "subject": "jarvis-core",
    "resource": "memory.info",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  },
  "jarvis-core-storage-info": {
    "id": "jarvis-core-storage-info",
    "subject": "jarvis-core",
    "resource": "storage.info",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  },
  "jarvis-core-network-interfaces": {
    "id": "jarvis-core-network-interfaces",
    "subject": "jarvis-core",
    "resource": "network.interfaces",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  },
  "jarvis-core-process-list": {
    "id": "jarvis-core-process-list",
    "subject": "jarvis-core",
    "resource": "process.list",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  },
  "jarvis-core-service-list": {
    "id": "jarvis-core-service-list",
    "subject": "jarvis-core",
    "resource": "service.list",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  },
  "jarvis-core-hardware-computer": {
    "id": "jarvis-core-hardware-computer",
    "subject": "jarvis-core",
    "resource": "hardware.computer",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  },
  "jarvis-core-logs-journald": {
    "id": "jarvis-core-logs-journald",
    "subject": "jarvis-core",
    "resource": "logs.journald",
    "action": "allow",
    "conditions": [],
    "granted_at": "2024-01-01T00:00:00Z",
    "expires_at": null,
    "granted_by": "installer"
  }
}
EOF

chown "$BRIDGE_USER:$BRIDGE_GROUP" /etc/jarvis-os/policy-grants.json
chmod 640 /etc/jarvis-os/policy-grants.json

# Create JARVIS CLI wrapper
log_info "Creating JARVIS CLI wrapper..."
cat > /usr/bin/jarvis-os << 'EOF'
#!/bin/bash
# JARVIS-OS CLI Wrapper

set -euo pipefail

JARVIS_HOME="${JARVIS_HOME:-/var/lib/jarvis}"
BRIDGE_SOCKET="${BRIDGE_SOCKET:-/run/jarvis-os/bridge.sock}"

case "${1:-}" in
    bridge)
        shift
        exec jarvis-os-bridge "$@"
        ;;
    status)
        systemctl status jarvis-os-bridge --no-pager
        ;;
    start)
        systemctl start jarvis-os-bridge
        ;;
    stop)
        systemctl stop jarvis-os-bridge
        ;;
    restart)
        systemctl restart jarvis-os-bridge
        ;;
    logs)
        journalctl -u jarvis-os-bridge -f
        ;;
    test-bridge)
        echo '{"jsonrpc":"2.0","method":"bridge.ping","params":{},"id":"test"}' | \
        socat - UNIX-CONNECT:"$BRIDGE_SOCKET"
        ;;
    *)
        echo "Usage: jarvis-os {bridge|status|start|stop|restart|logs|test-bridge}"
        exit 1
        ;;
esac
EOF

chmod 755 /usr/bin/jarvis-os

# Final verification
echo ""
echo "======================================"
echo "  JARVIS-OS Installation Complete"
echo "======================================"
echo ""
echo "Services:"
systemctl status jarvis-os-bridge --no-pager | head -10
echo ""
echo "Commands:"
echo "  jarvis-os status     - Check service status"
echo "  jarvis-os logs       - View bridge logs"
echo "  jarvis-os test-bridge - Test bridge connection"
echo ""
echo "Configuration:"
echo "  Bridge config: /etc/jarvis-os/bridge.toml"
echo "  Policy grants: /etc/jarvis-os/policy-grants.json"
echo "  JARVIS config: /etc/jarvis/config.py"
echo ""
echo "Logs:"
echo "  journalctl -u jarvis-os-bridge -f"
echo ""
echo "Socket:"
echo "  /run/jarvis-os/bridge.sock"
echo ""
log_success "Installation complete! JARVIS-OS is ready."