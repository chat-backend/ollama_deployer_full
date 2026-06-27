# ollama_gateway/ollama_deployer/firewall.py

#!/usr/bin/env python3
"""
Firewall setup module for Ollama PRO+ Cluster.

Chức năng:
- Kiểm tra và cài đặt UFW (Ubuntu/Debian)
- Thêm rule cho các port quan trọng: 22, 80, 443, 9100
- Không phá SSH
- Safe khi chạy nhiều lần
"""

import os
import shutil
import subprocess


# ============================================================
#  LOGGING
# ============================================================
def log(msg: str) -> None:
    print(f"[FIREWALL] {msg}")


# ============================================================
#  SAFE RUN
# ============================================================
def run(cmd: list[str], check: bool = True):
    """Wrapper cho subprocess.run với logging."""
    log("RUN: " + " ".join(cmd))
    return subprocess.run(cmd, check=check)


# ============================================================
#  ROOT CHECK
# ============================================================
def require_root() -> None:
    """Yêu cầu root trên Linux, Windows thì bỏ qua."""
    if hasattr(os, "geteuid"):
        if os.geteuid() != 0:
            raise SystemExit("Please run as root (sudo).")
    else:
        # Windows: skip
        return


# ============================================================
#  HELPERS
# ============================================================
def is_linux() -> bool:
    return os.name == "posix"


def ufw_exists() -> bool:
    return shutil.which("ufw") is not None


def apt_exists() -> bool:
    return shutil.which("apt") is not None


def ufw_is_enabled() -> bool:
    """Check if UFW is active."""
    try:
        result = subprocess.run(
            ["ufw", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        return "Status: active" in result.stdout
    except Exception:
        log("Failed to check UFW status.")
        return False


def allow_port(port: str) -> None:
    """Add UFW rule only if not already present."""
    try:
        result = subprocess.run(
            ["ufw", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        log("Failed to read UFW status — cannot add port rule.")
        return

    lines = result.stdout.splitlines()
    for line in lines:
        # Avoid substring match (e.g., 22 matching 2222)
        if line.strip().startswith(port + " "):
            log(f"Port {port} already allowed.")
            return

    run(["ufw", "allow", port])


# ============================================================
#  MAIN ENTRY
# ============================================================
def setup_firewall() -> None:
    """
    Setup firewall rules:
    - Safe for multiple runs
    - Does not break SSH
    - Adds rules for 22, 80, 443, 9100
    """
    if not is_linux():
        log("Non-Linux system detected — skipping firewall setup.")
        return

    require_root()

    log("Configuring UFW firewall...")

    # 1) Install UFW if missing
    if not ufw_exists():
        if not apt_exists():
            log("UFW not installed and apt not available — skipping UFW install.")
            return
        log("UFW not installed — installing via apt...")
        run(["apt", "install", "ufw", "-y"])
    else:
        log("UFW already installed.")

    # 2) Allow essential ports
    allow_port("22")     # SSH
    allow_port("80")     # HTTP
    allow_port("443")    # HTTPS
    allow_port("9100")   # Node Exporter

    # 3) Enable UFW if not active
    if not ufw_is_enabled():
        log("Enabling UFW...")
        run(["ufw", "--force", "enable"])
    else:
        log("UFW already active.")

    log("Firewall configured successfully.")

