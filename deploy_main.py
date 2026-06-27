# ollama_deployer/deploy_main.py

#!/usr/bin/env python3
"""
Ollama PRO+ Cluster Deployer (Python V15 core)
Tinh gọn – đồng bộ chuẩn Ollama Cloud Gateway.
Hoàn chỉnh, kiểm tra lỗi, đồng bộ logic.
"""

import argparse
import os
import subprocess
from secrets import token_hex
from typing import List

from ollama_deployer.settings import (
    DOMAINS,
    CONFIG_DIR,
    PROJECT_CONFIG_FILE,
    API_KEY_FILE,
    ProjectConfig,
)

import ollama_deployer.backends as be
import ollama_deployer.nginx as ngx

from ollama_deployer.auto_update import auto_update_mode
from ollama_deployer.rolling_restart import rolling_restart
from ollama_deployer.monitoring import setup_monitoring
from ollama_deployer.firewall import setup_firewall
from ollama_deployer.backup import setup_backup

from ollama_deployer.system_services import (
    install_ollama,
    configure_ollama_service,
    install_nginx,
    install_certbot,
    issue_ssl_for_domain,
)

from ollama_deployer.health_cluster import main as health_check
from ollama_deployer.auto_drain import main as auto_drain


# ============================================================
#  UTILS
# ============================================================
def is_linux() -> bool:
    return os.name == "posix"


def require_root() -> None:
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise SystemExit("Please run as root (sudo).")


def log(msg: str) -> None:
    print(msg)


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    log(f"[RUN] {' '.join(cmd)}")
    return subprocess.run(cmd, check=check)


# ============================================================
#  PROJECT CONFIG (CHUẨN OLLAMA) – LUÔN TẠO MỚI
# ============================================================
def backup_project_config() -> None:
    if not PROJECT_CONFIG_FILE.exists():
        return
    backup_path = PROJECT_CONFIG_FILE.with_suffix(".bak")
    log(f"[INFO] Backing up old project config to {backup_path}")
    try:
        backup_path.write_text(PROJECT_CONFIG_FILE.read_text())
    except Exception as e:
        log(f"[WARN] Could not backup old config: {e}")


def init_project_config() -> ProjectConfig:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not DOMAINS:
        raise SystemExit("[ERROR] No domains configured in DOMAINS.")

    if len(set(DOMAINS)) != len(DOMAINS):
        raise SystemExit("[ERROR] Duplicate domains detected in DOMAINS.")

    base_url = f"https://{DOMAINS[0]}"

    api_generate = f"{base_url}/api/v12/chat/stream"
    api_completion = f"{base_url}/api/v12/chat"
    api_pull = f"{base_url}/api/v12/pull"
    api_health = f"{base_url}/api/v12/health"

    backup_project_config()

    log("[INFO] Creating fresh project config (v1.0)...")

    api_key = token_hex(64)
    token_secret = token_hex(64)

    PROJECT_CONFIG_FILE.write_text(
        "CONFIG_VERSION=1.0\n"
        f"BASE_URL={base_url}\n"
        f"API_GENERATE={api_generate}\n"
        f"API_COMPLETION={api_completion}\n"
        f"API_PULL={api_pull}\n"
        f"API_HEALTH={api_health}\n"
        f"API_KEY={api_key}\n"
        f"TOKEN_SECRET={token_secret}\n"
    )

    data: dict[str, str] = {}
    for line in PROJECT_CONFIG_FILE.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()

    try:
        API_KEY_FILE.unlink(missing_ok=True)
    except Exception:
        pass

    API_KEY_FILE.write_text(f"OLLAMA_API_KEY={data['API_KEY']}\n")

    cfg = ProjectConfig.from_dict(data)

    log("[INFO] Project config loaded:")
    for k, v in data.items():
        log(f"  {k} = {v}")

    return cfg


# ============================================================
#  DNS CHECK
# ============================================================
def check_dns() -> None:
    if not is_linux():
        log("[WARN] Non-Linux system — skipping DNS check.")
        return

    log("[INFO] Checking DNS...")
    for domain in DOMAINS:
        result = subprocess.run(["getent", "hosts", domain], capture_output=True)
        if result.returncode != 0:
            raise SystemExit(f"[ERROR] DNS for {domain} not resolved.")
        log(f"[OK] DNS OK for {domain}")


# ============================================================
#  SYSTEM UPDATE
# ============================================================
def update_system() -> None:
    if not is_linux():
        log("[WARN] Non-Linux system — skipping system update.")
        return

    log("[INFO] Updating system...")
    run(["apt", "update"])
    run(["apt", "upgrade", "-y"])


# ============================================================
#  DEPLOY STEPS
# ============================================================
def deploy_services() -> None:
    install_ollama()
    configure_ollama_service()
    install_certbot()
    install_nginx()


def configure_nginx_and_ssl() -> None:
    ngx.generate_upstream_block()

    for domain in DOMAINS:
        result = issue_ssl_for_domain(domain)
        # Cho phép issue_ssl_for_domain trả về None hoặc bool
        if result is False:
            raise SystemExit(f"[ERROR] Failed to issue SSL for {domain}")
        ngx.configure_nginx_site_for_domain(domain)

    ngx.reload_nginx()


def finalize_security() -> None:
    setup_monitoring()
    setup_backup()
    setup_firewall()


def print_api_info(cfg: ProjectConfig) -> None:
    log("=== API ENDPOINTS ===")
    log(f"  BASE_URL       : {cfg.base_url}")
    log(f"  HEALTH_URL     : {cfg.api_health}")
    log(f"  GENERATE_URL   : {cfg.api_generate}")
    log(f"  COMPLETION_URL : {cfg.api_completion}")
    log(f"  PULL_URL       : {cfg.api_pull}")
    log(f"  API_KEY        : {cfg.api_key}")
    log(f"  TOKEN_SECRET   : {cfg.token_secret}")

    log("[INFO] Test your API (stream):")
    log(
        f"curl -X POST {cfg.api_generate} "
        f"-H \"Authorization: Bearer {cfg.api_key}\" "
        f"-H \"Content-Type: application/json\" "
        f"-d '{{\"model\":\"llama3:latest\",\"prompt\":\"hello\",\"stream\":true}}'"
    )

    log("[INFO] Test your API (non-stream):")
    log(
        f"curl -X POST {cfg.api_completion} "
        f"-H \"Authorization: Bearer {cfg.api_key}\" "
        f"-H \"Content-Type: application/json\" "
        f"-d '{{\"model\":\"llama3:latest\",\"prompt\":\"hello\",\"stream\":false}}'"
    )


# ============================================================
#  FULL DEPLOY
# ============================================================
def full_deploy() -> None:
    require_root()
    log(f"[INFO] Starting PRO+ Ollama deployment for: {', '.join(DOMAINS)}")

    cfg = init_project_config()
    be.load_backends()

    if not getattr(be, "backends", None):
        log("[WARN] No backends registered. API will not function until you add one.")

    check_dns()
    update_system()

    deploy_services()
    configure_nginx_and_ssl()
    finalize_security()

    # Health-check sau deploy
    try:
        require_root()
        health_check()
        log("[OK] Cluster health-check passed.")
    except SystemExit as e:
        log(f"[WARN] Health-check failed: {e}")

    log("[OK] Core deploy completed.")
    print_api_info(cfg)


# ============================================================
#  UNIFIED CLI
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Ollama PRO+ Cluster Deployer")

    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("deploy")
    sub.add_parser("update")
    sub.add_parser("health-check")
    sub.add_parser("auto-drain")
    sub.add_parser("rolling-restart")

    add_be = sub.add_parser("add-backend")
    add_be.add_argument("backend")

    rm_be = sub.add_parser("remove-backend")
    rm_be.add_argument("backend")

    dr_be = sub.add_parser("drain-backend")
    dr_be.add_argument("backend")

    undr_be = sub.add_parser("undrain-backend")
    undr_be.add_argument("backend")

    return p


def handle_backend_command(cmd: str, backend: str) -> None:
    actions = {
        "add-backend": be.add_backend,
        "remove-backend": be.remove_backend,
        "drain-backend": be.drain_backend,
        "undrain-backend": be.undrain_backend,
    }

    if cmd not in actions:
        raise SystemExit(f"[ERROR] Unknown backend command: {cmd}")

    actions[cmd](backend)

    if cmd in ("add-backend", "remove-backend"):
        ngx.generate_upstream_block()
        ngx.reload_nginx()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    cmd = args.cmd

    if cmd == "deploy":
        full_deploy()

    elif cmd == "update":
        require_root()
        auto_update_mode()

    elif cmd == "health-check":
        require_root()
        health_check()

    elif cmd == "auto-drain":
        require_root()
        auto_drain()

    elif cmd == "rolling-restart":
        require_root()
        rolling_restart()

    elif cmd in ("add-backend", "remove-backend", "drain-backend", "undrain-backend"):
        require_root()
        handle_backend_command(cmd, args.backend)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()

