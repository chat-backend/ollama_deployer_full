# ollama_gateway/ollama-deployer/auto_update.py
#!/usr/bin/env python3
"""
Auto-update module for Ollama PRO+ Cluster.
"""

import os
import shutil
import subprocess
from time import sleep


# ============================================================
#  UTILS
# ============================================================
def log(msg: str) -> None:
    print(f"[AUTO-UPDATE] {msg}")


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    log(f"RUN: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def is_linux_root() -> bool:
    """
    Trả về True nếu đang chạy Linux và user là root.
    Trả về False nếu Windows hoặc không phải root.
    """
    if hasattr(os, "geteuid"):
        return os.geteuid() == 0
    return False  # Windows


def require_root() -> None:
    """
    Yêu cầu root trên Linux. Windows thì bỏ qua.
    """
    if hasattr(os, "geteuid"):
        if not is_linux_root():
            raise SystemExit("Please run as root (sudo).")


def check_internet() -> None:
    log("Checking internet connectivity...")

    ping_cmd = ["ping", "-n", "1", "8.8.8.8"] if os.name == "nt" else ["ping", "-c", "1", "8.8.8.8"]

    result = subprocess.run(
        ping_cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if result.returncode != 0:
        log("❌ No internet connection — aborting update.")
        raise SystemExit(1)

    log("✅ Internet OK.")


# ============================================================
#  SYSTEM UPDATE
# ============================================================
def update_system() -> None:
    apt = shutil.which("apt")
    if not apt:
        log("apt not found — skipping system update.")
        return

    log("Updating system packages...")

    run(["rm", "-f", "/var/lib/dpkg/lock-frontend"], check=False)
    run(["rm", "-f", "/var/lib/dpkg/lock"], check=False)

    run([apt, "update", "-y"])
    run([apt, "upgrade", "-y"])
    run([apt, "autoremove", "-y"])

    log("✅ System packages updated.")


# ============================================================
#  UPDATE OLLAMA
# ============================================================
def update_ollama() -> None:
    ollama_bin = shutil.which("ollama")
    if not ollama_bin:
        log("Ollama not installed — skipping.")
        return

    log("Updating Ollama (if new version available)...")
    run(["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"])
    sleep(2)

    systemctl = shutil.which("systemctl")
    if systemctl:
        run([systemctl, "restart", "ollama"], check=False)
        log("Ollama restarted via systemctl.")
    else:
        log("systemctl not found — please restart Ollama manually.")


# ============================================================
#  UPDATE NGINX
# ============================================================
def update_nginx() -> None:
    nginx_bin = shutil.which("nginx")
    if not nginx_bin:
        log("Nginx not installed — skipping.")
        return

    log("Reloading Nginx...")

    test_result = run([nginx_bin, "-t"], check=False)
    if test_result.returncode == 0:
        run([nginx_bin, "-s", "reload"], check=False)
        log("✅ Nginx reloaded.")
    else:
        log("❌ Nginx config invalid — NOT reloading.")


# ============================================================
#  UPDATE NODE EXPORTER
# ============================================================
def update_node_exporter() -> None:
    node_exporter = shutil.which("node_exporter")
    if not node_exporter:
        log("Node Exporter not installed — skipping.")
        return

    log("Restarting Node Exporter...")

    systemctl = shutil.which("systemctl")
    if systemctl:
        run([systemctl, "restart", "node_exporter"], check=False)
        log("✅ Node Exporter restarted.")
    else:
        log("systemctl not found — please restart node_exporter manually.")


# ============================================================
#  UPDATE FAIL2BAN
# ============================================================
def update_fail2ban() -> None:
    fail2ban = shutil.which("fail2ban-client")
    if not fail2ban:
        log("Fail2ban not installed — skipping.")
        return

    log("Reloading Fail2ban...")

    systemctl = shutil.which("systemctl")
    if systemctl:
        run([systemctl, "reload", "fail2ban"], check=False)
        run([systemctl, "restart", "fail2ban"], check=False)
        log("✅ Fail2ban reloaded & restarted.")
    else:
        log("systemctl not found — please manage Fail2ban manually.")


# ============================================================
#  AUTO UPDATE MODE (FULL)
# ============================================================
def auto_update_mode() -> None:
    require_root()
    check_internet()

    log("🚀 Starting AUTO-UPDATE mode...")

    update_system()
    update_ollama()
    update_nginx()
    update_node_exporter()
    update_fail2ban()

    log("✅ AUTO-UPDATE completed successfully.")
