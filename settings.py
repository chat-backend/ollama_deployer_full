# ollama_deployer/settings.py

from pathlib import Path
from dataclasses import dataclass
from typing import List

# ============================================================
#  DOMAIN & EMAIL CONFIG
# ============================================================

# Domain mà Ollama Gateway sẽ quản lý
DOMAINS: List[str] = [
    "api.aiallplatform.com",
]

# Email dùng cho Certbot
EMAIL: str = "openaimanage@gmail.com"


# ============================================================
#  BASE DIRECTORIES
# ============================================================

CONFIG_DIR = Path("/etc/ollama")
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
#  PROJECT CONFIG FILES
# ============================================================

PROJECT_CONFIG_FILE = CONFIG_DIR / "project.conf"
API_KEY_FILE = CONFIG_DIR / "api_key"

BACKENDS_CONFIG = CONFIG_DIR / "backends.conf"
DRAIN_CONFIG = CONFIG_DIR / "backends.drain"

DEFAULT_BACKENDS = ["127.0.0.1:11434"]


# ============================================================
#  NGINX CONFIG PATHS
# ============================================================

UPSTREAM_FILE = Path("/etc/nginx/conf.d/ollama-upstream.conf")
LOG_FILE = Path("/var/log/ollama-deploy.log")


# ============================================================
#  PROJECT CONFIG STRUCTURE (Ollama Cloud Gateway)
# ============================================================

@dataclass
class ProjectConfig:
    """
    Cấu hình chuẩn cho Ollama Gateway.
    Dùng URL dạng https://domain/ollama/api/... đúng chuẩn Ollama.
    """

    config_version: str = "1.0"

    # Domain gốc
    base_url: str = "https://api.aiallplatform.com"

    # API endpoints (đúng chuẩn Ollama)
    api_generate: str = "/ollama/api/generate"
    api_pull: str = "/ollama/api/pull"
    api_health: str = "/ollama/api/health"

    # Security
    api_key: str = ""
    token_secret: str = ""

    @staticmethod
    def from_dict(data: dict) -> "ProjectConfig":
        return ProjectConfig(
            config_version=data.get("CONFIG_VERSION", "1.0"),
            base_url=data.get("BASE_URL", "https://api.aiallplatform.com"),

            api_generate=data.get("API_GENERATE", "/ollama/api/generate"),
            api_pull=data.get("API_PULL", "/ollama/api/pull"),
            api_health=data.get("API_HEALTH", "/ollama/api/health"),

            api_key=data.get("API_KEY", ""),
            token_secret=data.get("TOKEN_SECRET", ""),
        )
