#!/bin/bash
# JARVIS-OS Installation Validator
# Runs comprehensive checks after installation

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

log_info() { echo -e "${BLUE}[CHECK]${NC} $*"; }
log_pass() { echo -e "${GREEN}[PASS]${NC} $*"; ((PASS++)); }
log_fail() { echo -e "${RED}[FAIL]${NC} $*"; ((FAIL++)); }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; ((WARN++)); }

echo "======================================"
echo "  JARVIS-OS Installation Validation"
echo "======================================"
echo ""

# 1. Check users and groups
log_info "Checking users and groups..."
for user_group in "jarvis:jarvis" "jarvis-os:jarvis-os"; do
    user=$(echo $user_group | cut -d: -f1)
    group=$(echo $user_group | cut -d: -f2)
    
    if id -u "$user" >/dev/null 2>&1; then
        log_pass "User $user exists"
    else
        log_fail "User $user missing"
    fi
    
    if getent group "$group" >/dev/null; then
        log_pass "Group $group exists"
    else
        log_fail "Group $group missing"
    fi
done

# 2. Check directories
log_info "Checking directories..."
dirs=(
    "/run/jarvis:/jarvis:jarvis"
    "/run/jarvis-os:/jarvis-os:jarvis-os"
    "/var/log/jarvis:/jarvis:jarvis"
    "/var/log/jarvis-os:/jarvis-os:jarvis-os"
    "/etc/jarvis:/jarvis:jarvis"
    "/etc/jarvis-os:/jarvis-os:jarvis-os"
    "/var/lib/jarvis:/jarvis:jarvis"
    "/var/lib/jarvis-os:/jarvis-os:jarvis-os"
    "/var/cache/jarvis:/jarvis:jarvis"
    "/var/cache/jarvis-os:/jarvis-os:jarvis-os"
)

for entry in "${dirs[@]}"; do
    path=$(echo $entry | cut -d: -f1)
    user=$(echo $entry | cut -d: -f2)
    group=$(echo $entry | cut -d: -f3)
    
    if [[ -d "$path" ]]; then
        log_pass "Directory $path exists"
        owner=$(stat -c "%U:%G" "$path")
        if [[ "$owner" == "$user:$group" ]]; then
            log_pass "Directory $path ownership correct ($owner)"
        else
            log_fail "Directory $path ownership incorrect: $owner (expected $user:$group)"
        fi
    else
        log_fail "Directory $path missing"
    fi
done

# 3. Check bridge binary
log_info "Checking bridge binary..."
if [[ -f /usr/bin/jarvis-os-bridge ]]; then
    log_pass "Bridge binary exists"
    if [[ -x /usr/bin/jarvis-os-bridge ]]; then
        log_pass "Bridge binary is executable"
    else
        log_fail "Bridge binary not executable"
    fi
    
    # Check version
    version=$(/usr/bin/jarvis-os-bridge --version 2>&1 || echo "unknown")
    log_pass "Bridge version: $version"
else
    log_fail "Bridge binary missing at /usr/bin/jarvis-os-bridge"
fi

# 4. Check systemd service
log_info "Checking systemd service..."
if systemctl is-enabled jarvis-os-bridge >/dev/null 2>&1; then
    log_pass "Service is enabled"
else
    log_fail "Service not enabled"
fi

if systemctl is-active jarvis-os-bridge >/dev/null 2>&1; then
    log_pass "Service is active"
else
    log_fail "Service not active"
    systemctl status jarvis-os-bridge --no-pager | head -20
fi

# 5. Check socket
log_info "Checking Unix domain socket..."
sleep 2
if [[ -S /run/jarvis-os/bridge.sock ]]; then
    log_pass "Socket exists at /run/jarvis-os/bridge.sock"
    owner=$(stat -c "%U:%G" /run/jarvis-os/bridge.sock)
    log_pass "Socket ownership: $owner"
else
    log_fail "Socket missing"
fi

# 6. Test bridge communication
log_info "Testing bridge communication..."
if command -v socat >/dev/null 2>&1; then
    if echo '{"jsonrpc":"2.0","method":"bridge.ping","params":{},"id":"test"}' | \
       timeout 5 socat - UNIX-CONNECT:/run/jarvis-os/bridge.sock 2>/dev/null | \
       grep -q '"status":"ok"'; then
        log_pass "Bridge ping successful"
    else
        log_fail "Bridge ping failed"
    fi
    
    # Test a few methods
    for method in "system.info" "cpu.info" "memory.info" "bridge.version"; do
        if echo "{\"jsonrpc\":\"2.0\",\"method\":\"$method\",\"params\":{},\"id\":\"test\"}" | \
           timeout 5 socat - UNIX-CONNECT:/run/jarvis-os/bridge.sock 2>/dev/null | \
           grep -q '"ok":true'; then
            log_pass "Bridge method $method works"
        else
            log_warn "Bridge method $method failed or not implemented"
        fi
    done
else
    log_warn "socat not installed, skipping communication test"
fi

# 7. Check configuration
log_info "Checking configuration..."
if [[ -f /etc/jarvis-os/bridge.toml ]]; then
    log_pass "Config file exists"
    if [[ -r /etc/jarvis-os/bridge.toml ]]; then
        log_pass "Config file is readable"
    else
        log_fail "Config file not readable"
    fi
else
    log_fail "Config file missing"
fi

if [[ -f /etc/jarvis-os/policy-grants.json ]]; then
    log_pass "Policy grants file exists"
    grant_count=$(jq '. | length' /etc/jarvis-os/policy-grants.json 2>/dev/null || echo "0")
    log_pass "Policy grants count: $grant_count"
else
    log_warn "Policy grants file missing"
fi

# 8. Check SELinux
log_info "Checking SELinux..."
if command -v getenforce >/dev/null 2>&1; then
    selinux_mode=$(getenforce)
    log_pass "SELinux mode: $selinux_mode"
    
    if semodule -l | grep -q jarvis-os; then
        log_pass "JARVIS-OS SELinux module loaded"
    else
        log_warn "JARVIS-OS SELinux module not loaded"
    fi
else
    log_warn "SELinux tools not available"
fi

# 9. Check Python integration
log_info "Checking Python integration..."
if python3 -c "import jarvis.os.bridge" 2>/dev/null; then
    log_pass "Python bridge module importable"
else
    log_warn "Python bridge module not importable (may need pip install -e .)"
fi

if python3 -c "import jarvis.neural.torch_integration" 2>/dev/null; then
    log_pass "PyTorch integration module importable"
else
    log_warn "PyTorch integration not importable (torch may not be installed)"
fi

if python3 -c "import jarvis.hardware" 2>/dev/null; then
    log_pass "Hardware module importable"
else
    log_warn "Hardware module not importable"
fi

if python3 -c "import jarvis.container" 2>/dev/null; then
    log_pass "Container module importable"
else
    log_warn "Container module not importable"
fi

# 10. Check required system tools
log_info "Checking required system tools..."
tools=("jq" "socat" "bc" "dmidecode" "smartctl" "nvidia-smi" "rocm-smi" "lsblk" "ip" "lsusb" "lspci" "num_cpus" "tpm2_pcrread" "ukify" "sbctl")
for tool in "${tools[@]}"; do
    if command -v "$tool" >/dev/null 2>&1; then
        log_pass "Tool $tool available"
    else
        log_warn "Tool $tool not installed (optional)"
    fi
done

# 11. Check kernel features
log_info "Checking kernel features..."
if [[ -f /sys/kernel/security/ima/ascii_runtime_measurements ]]; then
    log_pass "IMA measurements available"
else
    log_warn "IMA not enabled in kernel"
fi

if [[ -f /sys/kernel/security/lockdown ]]; then
    log_pass "Kernel lockdown available"
else
    log_warn "Kernel lockdown not available"
fi

if [[ -c /dev/tpmrm0 ]] || [[ -c /dev/tpm0 ]]; then
    log_pass "TPM device available"
else
    log_warn "TPM device not found"
fi

# 12. Check logs
log_info "Checking service logs..."
if journalctl -u jarvis-os-bridge --no-pager -n 20 >/dev/null 2>&1; then
    log_pass "Service logs accessible"
else
    log_fail "Cannot access service logs"
fi

# Summary
echo ""
echo "======================================"
echo "  Validation Summary"
echo "======================================"
echo -e "Passed: ${GREEN}$PASS${NC}"
echo -e "Failed: ${RED}$FAIL${NC}"
echo -e "Warnings: ${YELLOW}$WARN${NC}"
echo ""

if [[ $FAIL -eq 0 ]]; then
    log_pass "All critical checks passed!"
    exit 0
else
    log_fail "Some checks failed. Review output above."
    exit 1
fi