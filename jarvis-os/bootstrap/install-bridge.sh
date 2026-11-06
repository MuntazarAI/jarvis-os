#!/bin/bash
# JARVIS-OS Bridge Installation Script
# Run as root: sudo ./install-bridge.sh

set -euo pipefail

BRIDGE_BINARY="/usr/bin/jarvis-os-bridge"
SERVICE_FILE="/etc/systemd/system/jarvis-os-bridge.service"
CONFIG_FILE="/etc/jarvis-os/bridge.toml"
SOCKET_DIR="/run/jarvis-os"
LOG_DIR="/var/log/jarvis-os"
CONFIG_DIR="/etc/jarvis-os"
STATE_DIR="/var/lib/jarvis-os"
USER="jarvis-os"
GROUP="jarvis-os"

echo "=== JARVIS-OS Bridge Installation ==="

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root"
   exit 1
fi

# Create user and group
if ! id -u "$USER" >/dev/null 2>&1; then
    echo "Creating user: $USER"
    useradd --system --no-create-home --shell /usr/sbin/nologin --comment "JARVIS-OS Bridge" "$USER"
fi

if ! getent group "$GROUP" >/dev/null 2>&1; then
    echo "Creating group: $GROUP"
    groupadd --system "$GROUP"
fi

# Build the bridge binary (assumes Cargo project in current directory)
if [[ -f "Cargo.toml" ]]; then
    echo "Building bridge binary..."
    cargo build --release
    cp target/release/jarvis-os-bridge "$BRIDGE_BINARY"
    chmod 755 "$BRIDGE_BINARY"
else
    echo "Cargo.toml not found. Please run from the bridge source directory."
    exit 1
fi

# Create directories
echo "Creating directories..."
mkdir -p "$SOCKET_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$STATE_DIR"

# Set ownership
chown -R "$USER:$GROUP" "$SOCKET_DIR"
chown -R "$USER:$GROUP" "$LOG_DIR"
chown -R "$USER:$GROUP" "$STATE_DIR"
chown -R "$USER:$GROUP" "$CONFIG_DIR"

# Install systemd service
echo "Installing systemd service..."
cp "$(dirname "$0")/systemd/jarvis-os-bridge.service" "$SERVICE_FILE"
systemctl daemon-reload

# Install config if not exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Installing config file..."
    cp "$(dirname "$0")/../config/bridge.toml" "$CONFIG_FILE"
    chown "$USER:$GROUP" "$CONFIG_FILE"
    chmod 640 "$CONFIG_FILE"
else
    echo "Config file already exists, skipping..."
fi

# Enable and start service
echo "Enabling and starting service..."
systemctl enable jarvis-os-bridge
systemctl start jarvis-os-bridge

# Wait a moment and check status
sleep 2
systemctl status jarvis-os-bridge --no-pager

echo ""
echo "=== Installation Complete ==="
echo "Bridge binary: $BRIDGE_BINARY"
echo "Service file: $SERVICE_FILE"
echo "Config file: $CONFIG_FILE"
echo "Socket: $SOCKET_DIR/bridge.sock"
echo "Logs: journalctl -u jarvis-os-bridge -f"
echo ""
echo "Test the bridge:"
echo "  echo '{\"jsonrpc\":\"2.0\",\"method\":\"bridge.ping\",\"params\":{},\"id\":\"test\"}' | socat - UNIX-CONNECT:$SOCKET_DIR/bridge.sock"