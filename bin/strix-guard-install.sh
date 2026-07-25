#!/bin/bash
# strix-guard-install.sh — install the kill switch + overload guard.
#
#   sudo bash bin/strix-guard-install.sh
#
# Installs:
#   /usr/local/sbin/strix-guard           the daemon
#   /etc/strix-guard/guard.conf           config (from the example, if absent)
#   /etc/strix-guard/token                random bearer token, 0600
#   /etc/strix-guard/telegram.env         optional alerting, 0600
#   /etc/systemd/system/strix-guard.service
#
# Re-running is safe: it keeps an existing token and config.
#
# Uninstall:
#   sudo systemctl disable --now strix-guard
#   sudo rm -rf /usr/local/sbin/strix-guard /etc/strix-guard \
#               /etc/systemd/system/strix-guard.service
#   sudo systemctl daemon-reload

set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "must run as root:  sudo bash $0" >&2
    exit 1
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> daemon"
install -m 0755 -o root -g root "$REPO/bin/strix-guard" /usr/local/sbin/strix-guard
python3 -m py_compile /usr/local/sbin/strix-guard
echo "    syntax ok"

echo "==> config"
install -d -m 0700 -o root -g root /etc/strix-guard
if [ ! -e /etc/strix-guard/guard.conf ]; then
    install -m 0600 -o root -g root \
        "$REPO/configs/strix-guard.conf.example" /etc/strix-guard/guard.conf
    echo "    created /etc/strix-guard/guard.conf — EDIT IT, then restart"
else
    echo "    keeping existing /etc/strix-guard/guard.conf"
fi
if [ ! -s /etc/strix-guard/token ]; then
    python3 -c "import secrets;print(secrets.token_urlsafe(24))" \
        > /etc/strix-guard/token
    chmod 0600 /etc/strix-guard/token
    echo "    generated a new token"
else
    echo "    keeping existing token"
fi
if [ ! -e /etc/strix-guard/telegram.env ]; then
    cat > /etc/strix-guard/telegram.env <<'EOF'
# Optional. Fill in for overload / kill / reboot alerts on Telegram.
STRIX_GUARD_TG_TOKEN=
STRIX_GUARD_TG_CHAT=
EOF
    chmod 0600 /etc/strix-guard/telegram.env
fi

echo "==> kernel recovery settings"
# SysRq must permit reboot (bit 128) or the HARD REBOOT button silently does
# nothing. 1 enables all SysRq functions. Without this there is no working
# emergency reboot path at all.
if [ ! -e /etc/sysctl.d/99-strix-recovery.conf ]; then
    cat > /etc/sysctl.d/99-strix-recovery.conf <<'EOF'
# Make the box remotely recoverable when userspace wedges.
kernel.sysrq = 1
# Auto-reboot 10s after a panic instead of sitting there dead.
kernel.panic = 10
kernel.panic_on_oops = 1
# Panic (and therefore reboot) on a CPU stuck in the kernel.
kernel.softlockup_panic = 1
kernel.hardlockup_panic = 1
EOF
    sysctl -p /etc/sysctl.d/99-strix-recovery.conf >/dev/null
    echo "    installed /etc/sysctl.d/99-strix-recovery.conf"
else
    echo "    keeping existing /etc/sysctl.d/99-strix-recovery.conf"
fi
printf '    kernel.sysrq = %s (needs bit 128 for the hard reboot button)\n' \
    "$(sysctl -n kernel.sysrq)"

# NOTE: kernel.hung_task_panic is NOT set here. It only exists if the kernel
# was built with CONFIG_DETECT_HUNG_TASK; many vanilla/custom kernels are not.
# Check with: ls /proc/sys/kernel/ | grep hung
if [ -e /proc/sys/kernel/hung_task_panic ]; then
    echo "    (this kernel HAS hung-task detection; consider enabling"
    echo "     kernel.hung_task_panic=1 with a generous hung_task_timeout_secs)"
else
    echo "    (this kernel has NO hung-task detection — a D-state pile-up will"
    echo "     not be logged or recovered; the overload guard covers that gap)"
fi

echo "==> service"
install -m 0644 -o root -g root \
    "$REPO/systemd/strix-guard.service" /etc/systemd/system/strix-guard.service
systemctl daemon-reload
systemctl enable --now strix-guard.service
sleep 3
systemctl --no-pager --lines=12 status strix-guard.service || true

IP="$(tailscale ip -4 2>/dev/null | head -1 || true)"
echo
echo "============================================================"
if [ -n "$IP" ]; then
    echo " strix-guard:  http://$IP:$(grep -E '^PORT=' /etc/strix-guard/guard.conf | cut -d= -f2 || echo 7799)/?t=<token>"
    echo
    echo " Your token:   sudo cat /etc/strix-guard/token"
else
    echo " No Tailscale IPv4 found — the daemon will wait for one."
fi
echo
echo " Bookmark that URL on your phone. It is reachable only over your"
echo " tailnet, never from the LAN or the internet."
echo "============================================================"
