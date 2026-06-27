# ollama_deployer/rolling_restart.py

#!/usr/bin/env python3
"""
Rolling restart module for Ollama PRO+ Cluster.

Chức năng:
- Drain từng backend
- Restart backend (local hoặc remote)
- Chờ backend healthy trở lại
- Undrain backend
- Sync upstream sau mỗi bước
"""

import subprocess
from time import sleep, time

from ollama_deployer.backends import (
    load_backends,
    drain_backend,
    undrain_backend,
)
from ollama_deployer.health_cluster import main as health_check_once


# ============================================================
#  LOGGING
# ============================================================
def log(msg: str) -> None:
    print(f"[ROLLING] {msg}")


# ============================================================
#  HEALTH CHECK
# ============================================================
def curl_health(backend: str, timeout: int = 5) -> bool:
    """Check health of a backend via /api/health."""
    try:
        subprocess.run(
            [
                "curl", "-fsS",
                "--max-time", str(timeout),
                f"http://{backend}/api/health"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except Exception:
        return False


# ============================================================
#  RESTART LOCAL BACKEND
# ============================================================
def restart_local_backend() -> None:
    """Restart local Ollama service (Linux)."""
    subprocess.run(["systemctl", "restart", "ollama"], check=False)


# ============================================================
#  RESTART REMOTE BACKEND (placeholder)
# ============================================================
def restart_remote_backend(host: str) -> None:
    """
    Restart remote backend qua SSH.
    Hiện tại chỉ log — có thể mở rộng sau.
    """
    log(f"Remote backend {host} — restart manually or implement SSH restart.")


# ============================================================
#  WAIT FOR HEALTHY
# ============================================================
def wait_for_healthy(backend: str, timeout: int) -> bool:
    """Chờ backend healthy trở lại trong timeout giây."""
    start = time()
    while time() - start < timeout:
        if curl_health(backend):
            return True
        sleep(3)
    return False


# ============================================================
#  ROLLING RESTART
# ============================================================
def rolling_restart(timeout_per_node: int = 60) -> None:
    """
    Rolling restart toàn bộ backend:
    1) drain node
    2) restart node
    3) chờ node healthy
    4) undrain node
    5) sync upstream
    """
    backends = load_backends()
    log(f"Starting rolling restart for: {', '.join(backends)}")

    for backend in backends:
        host, port = backend.split(":")

        log(f"--- Restarting backend: {backend} ---")

        # ============================================================
        # 1) Drain backend
        # ============================================================
        drain_backend(backend)
        health_check_once()
        sleep(2)

        # ============================================================
        # 2) Restart backend
        # ============================================================
        if host in ("127.0.0.1", "localhost"):
            log(f"Restarting local Ollama for {backend}")
            restart_local_backend()
        else:
            restart_remote_backend(host)

        # ============================================================
        # 3) Wait for backend to become healthy
        # ============================================================
        log(f"Waiting for backend {backend} to recover...")

        if not wait_for_healthy(backend, timeout_per_node):
            log(f"❌ Backend {backend} did NOT recover — keeping it drained.")
            continue

        log(f"✅ Backend {backend} healthy again.")

        # ============================================================
        # 4) Undrain backend
        # ============================================================
        undrain_backend(backend)
        sleep(1)

        # ============================================================
        # 5) Sync upstream
        # ============================================================
        health_check_once()

        log(f"--- Backend {backend} restarted successfully ---")

    log("🎉 Rolling restart completed.")
