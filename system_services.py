# ollama_deployer/system_services.py

#!/usr/bin/env python3
"""
System services setup module for Ollama PRO+ Cluster.

Chức năng:
- Cài đặt Ollama, Nginx, Certbot, Fail2ban (Ubuntu/Debian)
- Tạo systemd service cho Ollama
- Cấp SSL bằng Certbot standalone
"""

import os
import shutil
import subprocess
from pathlib import Path

from ollama_deployer.settings import EMAIL


# ============================================================
#  UTILS
# ============================================================
def log(msg: str) -> None:
    print(f"[SERVICE] {msg}")


def run(cmd: list[str], check: bool = True):
    log(f"RUN: {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


def require_root() -> None:
    """Cross‑platform safe root check."""
    if hasattr(os, "geteuid"):
        if os.geteuid() != 0:
            raise SystemExit("Please run as root (sudo).")
    else:
        return


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def is_linux() -> bool:
    return os.name == "posix"


def apt_exists() -> bool:
    return shutil.which("apt") is not None


def systemctl_available() -> bool:
    return shutil.which("systemctl") is not None


# ============================================================
#  INSTALL OLLAMA
# ============================================================
def install_ollama() -> None:
    """Install Ollama if not installed."""
    if not is_linux():
        log("Non-Linux system detected — skipping Ollama install script.")
        return

    if shutil.which("ollama"):
        log("Ollama already installed — skipping.")
        return

    if shutil.which("curl") is None:
        log("curl not found — cannot install Ollama.")
        return

    log("Installing Ollama...")
    result = run(["bash", "-c", "curl -fsSL https://ollama.com/install.sh | sh"], check=False)

    if result.returncode != 0:
        log("ERROR: Ollama install script failed.")
        return

    log("Ollama installed.")


# ============================================================
#  CONFIGURE OLLAMA SERVICE
# ============================================================
def configure_ollama_service() -> None:
    """Create and enable systemd service for Ollama."""
    if not is_linux():
        log("Non-Linux system detected — skipping Ollama service configuration.")
        return

    if not systemctl_available():
        log("systemd not available — skipping Ollama service configuration.")
        return

    require_root()

    if not Path("/usr/local/bin/ollama").exists():
        log("Ollama binary not found — skipping service creation.")
        return

    service_file = Path("/etc/systemd/system/ollama.service")

    content = """[Unit]
Description=Ollama Server
After=network.target

[Service]
ExecStart=/usr/local/bin/ollama serve
Restart=always
RestartSec=3
User=root
LimitNOFILE=65535

Environment=OLLAMA_NUM_THREADS=4
Environment=OLLAMA_TEMPERATURE=0.7
Environment=OLLAMA_TOP_P=1.0
Environment=OLLAMA_TOP_K=40
Environment=OLLAMA_NUM_PREDICT=12000
Environment=OLLAMA_STREAM=1
Environment=OLLAMA_HOST=0.0.0.0

[Install]
WantedBy=multi-user.target
"""

    atomic_write(service_file, content)

    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "ollama"])
    run(["systemctl", "restart", "ollama"])

    log("Ollama service configured and running.")


# ============================================================
#  INSTALL NGINX
# ============================================================
def install_nginx() -> None:
    if shutil.which("nginx"):
        log("Nginx already installed — skipping.")
        return

    if not is_linux() or not apt_exists():
        log("Cannot install Nginx — non-Linux or apt not available.")
        return

    log("Installing Nginx...")
    result = run(["apt", "install", "nginx", "-y"], check=False)

    if result.returncode != 0:
        log("ERROR: Failed to install Nginx.")
        return

    log("Nginx installed.")


# ============================================================
#  INSTALL CERTBOT
# ============================================================
def install_certbot() -> None:
    if shutil.which("certbot"):
        log("Certbot already installed — skipping.")
        return

    if not is_linux() or not apt_exists():
        log("Cannot install Certbot — non-Linux or apt not available.")
        return

    log("Installing Certbot...")
    result = run(["apt", "install", "certbot", "-y"], check=False)

    if result.returncode != 0:
        log("ERROR: Failed to install Certbot.")
        return

    log("Certbot installed.")


# ============================================================
#  ISSUE SSL
# ============================================================
def issue_ssl_for_domain(domain: str) -> None:
    """Issue SSL certificate using certbot standalone."""
    if not is_linux():
        log("Non-Linux system detected — skipping SSL issue.")
        return

    require_root()

    if shutil.which("certbot") is None:
        log("Certbot not installed — cannot issue SSL.")
        return

    log(f"Requesting SSL for {domain}...")

    live_dir = Path(f"/etc/letsencrypt/live/{domain}")
    if live_dir.exists():
        log(f"SSL for {domain} already exists — skipping.")
        return

    if systemctl_available():
        subprocess.run(["systemctl", "stop", "nginx"], check=False)

    result = run([
        "certbot", "certonly", "--standalone",
        "-d", domain,
        "--non-interactive",
        "--agree-tos",
        "--no-eff-email",
        "-m", EMAIL,
    ], check=False)

    if result.returncode != 0:
        log("ERROR: Certbot failed to obtain SSL.")
        return

    log(f"SSL obtained for {domain}.")


# ============================================================
#  INSTALL FAIL2BAN
# ============================================================
def install_fail2ban() -> None:
    """Install and configure Fail2ban for Nginx."""
    if not is_linux() or not apt_exists():
        log("Cannot install Fail2ban — non-Linux or apt not available.")
        return

    if not systemctl_available():
        log("systemd not available — skipping Fail2ban configuration.")
        return

    require_root()

    log("Installing Fail2ban...")

    result = run(["apt", "install", "fail2ban", "-y"], check=False)
    if result.returncode != 0:
        log("ERROR: Failed to install Fail2ban.")
        return

    jail = Path("/etc/fail2ban/jail.d/nginx-ollama.conf")
    jail_content = """[nginx-ollama]
enabled = true
port = http,https
filter = nginx-ollama
logpath = /var/log/nginx/access.log
maxretry = 20
bantime = 3600
"""
    atomic_write(jail, jail_content)

    flt = Path("/etc/fail2ban/filter.d/nginx-ollama.conf")
    flt_content = """[Definition]
failregex = ^<HOST> -.*"(GET|POST).*"
"""
    atomic_write(flt, flt_content)

    run(["systemctl", "restart", "fail2ban"])

    log("Fail2ban configured for Nginx.")


