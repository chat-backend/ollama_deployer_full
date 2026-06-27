# ollama_deployer/nginx.py

import subprocess
from pathlib import Path
from typing import List

from ollama_deployer.settings import (
    UPSTREAM_FILE,
    PROJECT_CONFIG_FILE,
    DOMAINS,
)

from ollama_deployer.backends import (
    health_check_backends,
    get_active_backends,
)

# ============================================================
#  UTILS
# ============================================================
def log(msg: str) -> None:
    print(f"[NGINX] {msg}")


def run(cmd: list[str], check: bool = True) -> None:
    """
    Wrapper quanh subprocess.run để:
    - log lệnh
    - cho phép cấu hình check=True/False
    """
    log(f"RUN: {' '.join(cmd)}")
    subprocess.run(cmd, check=check)


def atomic_write(path: Path, content: str) -> None:
    """
    Ghi file một cách an toàn:
    - ghi vào file .tmp
    - sau đó replace sang file chính
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(path)


# ============================================================
#  LOAD PROJECT CONFIG
# ============================================================
def load_project_config() -> dict:
    """
    Đọc file PROJECT_CONFIG_FILE dạng key=value, bỏ qua dòng trống và comment.
    """
    if not PROJECT_CONFIG_FILE.exists():
        raise RuntimeError(f"Project config not found: {PROJECT_CONFIG_FILE}")

    data: dict[str, str] = {}
    for line in PROJECT_CONFIG_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()

    return data


# ============================================================
#  GENERATE UPSTREAM BLOCK (UPDATED)
# ============================================================
def generate_upstream_block() -> None:
    """
    Tạo file upstream cho cụm Ollama:
    - chỉ dùng backend active (không bị draining)
    - dùng least_conn để load-balance
    - mỗi backend có max_fails/fail_timeout
    """
    backends = get_active_backends()

    if not backends:
        log("❌ No active backends available! Upstream will be empty.")
        content = (
            "upstream ollama_cluster {\n"
            "    least_conn;\n"
            "    # No active backends available\n"
            "}\n"
        )
        atomic_write(UPSTREAM_FILE, content)
        return

    lines = [
        "upstream ollama_cluster {",
        "    least_conn;",
    ]

    for be in backends:
        lines.append(f"    server {be} max_fails=3 fail_timeout=30s;")

    lines.append("}")

    content = "\n".join(lines) + "\n"
    atomic_write(UPSTREAM_FILE, content)

    log(f"Updated upstream with active backends: {', '.join(backends)}")


# ============================================================
#  CONFIGURE NGINX SITE
# ============================================================
def build_nginx_site_content(domain: str, api_key: str) -> str:
    """
    Tách riêng phần build nội dung config Nginx để:
    - dễ test
    - không phụ thuộc vào filesystem
    """
    return f"""
server {{
    listen 80;
    server_name {domain};
    return 301 https://$host$request_uri;
}}

server {{
    listen 443 ssl http2;
    server_name {domain};

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    client_max_body_size 100M;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    # CORS
    add_header Access-Control-Allow-Origin * always;
    add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
    add_header Access-Control-Allow-Headers "Authorization, Content-Type, x-api-key" always;

    if ($request_method = OPTIONS) {{
        return 204;
    }}

    # Default block
    location / {{
        return 404;
    }}

    # OLLAMA API GATEWAY
    location /ollama/ {{

        # API KEY CHECK
        if ($http_x_api_key = "") {{
            return 401;
        }}

        if ($http_x_api_key != "{api_key}") {{
            return 403;
        }}

        # Health endpoint at gateway level
        if ($request_uri ~* "^/ollama/api/health$") {{
            add_header Content-Type application/json;
            return 200 '{{"status":"ok"}}';
        }}

        # Strip /ollama/ prefix before proxying to Ollama
        rewrite ^/ollama/(.*)$ /$1 last;

        proxy_pass http://ollama_cluster/;
        proxy_http_version 1.1;

        # Streaming-friendly
        proxy_set_header Accept-Encoding "";

        # Forward headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Authorization $http_authorization;

        proxy_read_timeout 3600;
        proxy_send_timeout 3600;
        proxy_buffering off;
        proxy_request_buffering off;
    }}
}}
""".lstrip()


def configure_nginx_site_for_domain(domain: str) -> None:
    """
    Tạo config Nginx cho một domain:
    - đọc API_KEY từ project config
    - ghi file vào sites-available
    - tạo symlink sang sites-enabled
    """
    cfg = load_project_config()
    api_key = cfg.get("API_KEY", "")

    site_file = Path(f"/etc/nginx/sites-available/ollama-{domain}")
    content = build_nginx_site_content(domain, api_key)
    atomic_write(site_file, content)

    enabled = Path(f"/etc/nginx/sites-enabled/ollama-{domain}")
    enabled.parent.mkdir(parents=True, exist_ok=True)

    if enabled.exists() or enabled.is_symlink():
        enabled.unlink()

    enabled.symlink_to(site_file)

    log(f"Nginx site configured for {domain}")


# ============================================================
#  RELOAD NGINX
# ============================================================
def reload_nginx() -> None:
    """
    Kiểm tra config Nginx rồi reload:
    - nginx -t
    - nginx -s reload
    """
    log("Testing nginx config...")
    run(["nginx", "-t"], check=True)

    log("Reloading nginx...")
    run(["nginx", "-s", "reload"], check=True)


# ============================================================
#  ISSUE SSL
# ============================================================
def issue_ssl_for_domain(domain: str) -> None:
    """
    Cấp SSL cho domain bằng Certbot (standalone):
    - nếu đã có /etc/letsencrypt/live/<domain> thì bỏ qua
    - tạm dừng nginx để Certbot bind port 80
    """
    log(f"Requesting SSL for {domain}")

    live_dir = Path(f"/etc/letsencrypt/live/{domain}")
    if live_dir.exists():
        log(f"SSL for {domain} already exists, skipping.")
        return

    # stop nginx để tránh conflict port với certbot --standalone
    run(["systemctl", "stop", "nginx"], check=False)

    run([
        "certbot", "certonly", "--standalone",
        "-d", domain,
        "--non-interactive",
        "--agree-tos",
        "-m", "openaimanage@gmail.com",
    ])

    log(f"SSL obtained for {domain}")


# ============================================================
#  FULL DEPLOY PIPELINE
# ============================================================
def configure_all_domains() -> None:
    """
    Triển khai toàn bộ gateway cho tất cả domain trong DOMAINS:
    1. Health-check backend → auto-drain backend lỗi
    2. Generate upstream block từ backend active
    3. Issue SSL cho từng domain
    4. Configure nginx site cho từng domain
    5. Reload nginx một lần cuối
    """
    log("=== Starting full Nginx/Ollama gateway deployment ===")

    # 1. Health-check backend
    log("Step 1: Running backend health-check...")
    health_check_backends()

    # 2. Generate upstream từ backend active
    log("Step 2: Generating upstream block from active backends...")
    generate_upstream_block()

    # 3. SSL + site config cho từng domain
    for domain in DOMAINS:
        log(f"--- Processing domain: {domain} ---")

        log("Step 3: Checking/issuing SSL...")
        issue_ssl_for_domain(domain)

        log("Step 4: Configuring nginx site...")
        configure_nginx_site_for_domain(domain)

    # 4. Reload nginx
    log("Step 5: Reloading nginx...")
    reload_nginx()

    log("=== Deployment completed successfully ===")
