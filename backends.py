# ollama_deployer/backends.py

from pathlib import Path
from typing import List
import requests

from ollama_deployer.settings import (
    BACKENDS_CONFIG,
    DRAIN_CONFIG,
    DEFAULT_BACKENDS,
)

# ============================================================
#  UTILS
# ============================================================

def log(msg: str) -> None:
    print(f"[BACKENDS] {msg}")


def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)


def normalize_backend(backend: str) -> str:
    return backend.strip().lower()


def validate_backend_format(backend: str) -> bool:
    if ":" not in backend:
        return False
    host, port = backend.split(":", 1)
    return bool(host) and port.isdigit()


# ============================================================
#  LOAD / SAVE BACKENDS
# ============================================================

def load_backends() -> List[str]:
    if BACKENDS_CONFIG.exists():
        return [
            normalize_backend(line)
            for line in BACKENDS_CONFIG.read_text().splitlines()
            if line.strip()
        ]

    BACKENDS_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(BACKENDS_CONFIG, "\n".join(DEFAULT_BACKENDS) + "\n")
    return [normalize_backend(b) for b in DEFAULT_BACKENDS]


def save_backends(backends: List[str]) -> None:
    atomic_write(BACKENDS_CONFIG, "\n".join(backends) + "\n")


# ============================================================
#  ACTIVE BACKENDS (exclude draining)
# ============================================================

def load_drain_list() -> List[str]:
    if not DRAIN_CONFIG.exists():
        return []
    return [
        normalize_backend(line)
        for line in DRAIN_CONFIG.read_text().splitlines()
        if line.strip()
    ]


def get_active_backends() -> List[str]:
    """
    Trả về danh sách backend đang active (không bị draining).
    """
    backends = load_backends()
    drains = load_drain_list()
    return [b for b in backends if b not in drains]


# ============================================================
#  ADD / REMOVE BACKEND
# ============================================================

def add_backend(backend: str) -> None:
    backend = normalize_backend(backend)

    if not validate_backend_format(backend):
        log(f"❌ Invalid backend format: {backend} (must be host:port)")
        return

    backends = load_backends()

    if backend in backends:
        log(f"ℹ Backend {backend} already exists.")
        return

    backends.append(backend)
    save_backends(backends)

    log(f"✅ Added backend: {backend}")


def remove_backend(backend: str) -> None:
    backend = normalize_backend(backend)

    if not BACKENDS_CONFIG.exists():
        log("⚠ No backends.conf found.")
        return

    backends = load_backends()

    if backend not in backends:
        log(f"⚠ Backend {backend} not found.")
    else:
        backends = [b for b in backends if b != backend]
        save_backends(backends)
        log(f"🗑 Removed backend: {backend}")

    # Remove from drain list
    if DRAIN_CONFIG.exists():
        drains = load_drain_list()
        drains = [d for d in drains if d != backend]
        atomic_write(DRAIN_CONFIG, "\n".join(drains) + "\n")


# ============================================================
#  DRAIN / UNDRAIN BACKEND
# ============================================================

def drain_backend(backend: str) -> None:
    backend = normalize_backend(backend)

    drains = load_drain_list()
    if backend in drains:
        log(f"ℹ Backend {backend} already draining.")
        return

    drains.append(backend)
    DRAIN_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(DRAIN_CONFIG, "\n".join(drains) + "\n")

    log(f"🟡 Backend {backend} marked as draining.")


def undrain_backend(backend: str) -> None:
    backend = normalize_backend(backend)

    if not DRAIN_CONFIG.exists():
        log("⚠ No drain config file.")
        return

    drains = load_drain_list()
    drains = [d for d in drains if d != backend]
    atomic_write(DRAIN_CONFIG, "\n".join(drains) + "\n")

    log(f"🟢 Backend {backend} removed from draining.")


# ============================================================
#  HEALTH CHECK (auto-drain unhealthy backend)
# ============================================================

def health_check_backends(timeout: float = 2.0) -> None:
    """
    Kiểm tra health của từng backend:
    - Nếu backend lỗi → tự động drain
    - Nếu backend OK → giữ nguyên
    """
    backends = load_backends()

    for backend in backends:
        url = f"http://{backend}/api/health"

        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                log(f"🟢 Backend healthy: {backend}")
            else:
                log(f"🔴 Backend unhealthy (status {r.status_code}): {backend}")
                drain_backend(backend)

        except Exception as e:
            log(f"🔴 Backend unreachable: {backend} ({e})")
            drain_backend(backend)


