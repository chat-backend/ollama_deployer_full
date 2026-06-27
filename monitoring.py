# ollama_gateway/ollama_deployer/monitoring.py

#!/usr/bin/env python3
"""
Monitoring setup module for Ollama PRO+ Cluster.

Chức năng:
- Cài đặt Prometheus Node Exporter (Linux)
- Tạo systemd service
- Khởi động và verify Node Exporter
"""

import os
import shutil
import subprocess
from pathlib import Path


# ============================================================
#  LOGGING
# ============================================================
def log(msg: str) -> None:
    print(f"[MONITORING] {msg}")


# ============================================================
#  SAFE RUN
# ============================================================
def run(cmd: list[str], check: bool = True):
    """Wrapper cho subprocess.run với logging."""
    log("RUN: " + " ".join(cmd))
    return subprocess.run(cmd, check=check)


# ============================================================
#  CONSTANTS
# ============================================================
NODE_EXPORTER_VERSION = "1.7.0"
NODE_EXPORTER_URL = (
    f"https://github.com/prometheus/node_exporter/releases/download/"
    f"v{NODE_EXPORTER_VERSION}/node_exporter-{NODE_EXPORTER_VERSION}.linux-amd64.tar.gz"
)

SERVICE_FILE = Path("/etc/systemd/system/node_exporter.service")
BIN_PATH = Path("/usr/local/bin/node_exporter")


# ============================================================
#  HELPERS
# ============================================================
def is_linux() -> bool:
    """Kiểm tra hệ điều hành Linux."""
    return os.name == "posix"


def systemctl_available() -> bool:
    """Kiểm tra systemctl có tồn tại không (container có thể không có)."""
    return shutil.which("systemctl") is not None


# ============================================================
#  INSTALL NODE EXPORTER
# ============================================================
def install_node_exporter() -> None:
    """Install Node Exporter nếu chưa có."""
    if shutil.which("node_exporter"):
        log("Node Exporter already installed — skipping install.")
        return

    if not is_linux():
        log("Non-Linux system detected — skipping Node Exporter install.")
        return

    if not systemctl_available():
        log("systemctl not available — cannot install Node Exporter.")
        return

    log(f"Installing Node Exporter v{NODE_EXPORTER_VERSION}...")

    tmp_dir = Path("/tmp/node_exporter_install")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    tar_file = tmp_dir / "node_exporter.tar.gz"

    # Download
    result = run(["curl", "-L", "-o", str(tar_file), NODE_EXPORTER_URL], check=False)
    if result.returncode != 0:
        raise RuntimeError("Failed to download Node Exporter.")

    # Extract
    result = run(["tar", "-xzf", str(tar_file), "-C", str(tmp_dir)], check=False)
    if result.returncode != 0:
        raise RuntimeError("Failed to extract Node Exporter.")

    extracted_dir = tmp_dir / f"node_exporter-{NODE_EXPORTER_VERSION}.linux-amd64"
    extracted_bin = extracted_dir / "node_exporter"

    if not extracted_bin.exists():
        raise RuntimeError("Node Exporter binary not found after extraction.")

    # Move binary
    run(["cp", str(extracted_bin), str(BIN_PATH)])
    run(["chmod", "+x", str(BIN_PATH)])

    # Create systemd service
    SERVICE_FILE.write_text(f"""[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
User=root
ExecStart={BIN_PATH}

[Install]
WantedBy=multi-user.target
""")

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "node_exporter"])
    run(["systemctl", "start", "node_exporter"])

    log("Node Exporter installed and running.")

    shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================
#  VERIFY NODE EXPORTER
# ============================================================
def verify_node_exporter_running() -> None:
    """Ensure Node Exporter is running."""
    if not is_linux():
        log("Non-Linux system detected — skipping Node Exporter status check.")
        return

    if not systemctl_available():
        log("systemctl not available — skipping Node Exporter status check.")
        return

    result = subprocess.run(["systemctl", "is-active", "--quiet", "node_exporter"])
    if result.returncode != 0:
        log("Node Exporter not running — restarting...")
        run(["systemctl", "restart", "node_exporter"], check=False)
    else:
        log("Node Exporter is active.")


# ============================================================
#  MAIN ENTRY
# ============================================================
def setup_monitoring() -> None:
    """Main entry for monitoring setup."""
    log("Setting up monitoring stack...")

    install_node_exporter()
    verify_node_exporter_running()

    log("Monitoring setup completed.")

