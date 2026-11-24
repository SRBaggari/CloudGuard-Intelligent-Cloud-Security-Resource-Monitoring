"""Application configuration loaded from environment variables / .env file.

No secrets are hardcoded. In production (APP_ENV=production) a JWT secret MUST be
provided; in development an ephemeral random secret is generated with a warning.
"""
from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger("cloudguard.config")

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", BACKEND_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CloudGuard"
    app_env: Literal["development", "production", "test"] = "development"

    # Database: PostgreSQL recommended, e.g. postgresql+psycopg://user:pass@localhost:5432/cloudguard
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'cloudguard.db').as_posix()}"
    auto_migrate: bool = True

    # Auth
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # CORS (comma separated)
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Rate limiting (requests per minute per client IP)
    rate_limit_auth_per_minute: int = 20
    rate_limit_default_per_minute: int = 600

    # Integrations: "real" uses psutil/Docker/VirtualBox; "mock" uses labelled demo adapters
    integration_mode: Literal["real", "mock"] = "real"
    enable_background_tasks: bool = True
    docker_enabled: bool = True
    virtualbox_enabled: bool = True
    vboxmanage_path: str = ""

    # Monitoring defaults (admin can change at runtime via /api/settings)
    metrics_interval_seconds: int = Field(default=5, ge=1, le=3600)
    container_poll_interval_seconds: int = Field(default=15, ge=5, le=3600)
    metrics_retention_days: int = 30

    # Data / storage
    data_dir: Path = BACKEND_DIR / "data"

    # Prometheus /metrics endpoint (optional bearer token)
    prometheus_enabled: bool = True
    prometheus_token: str = ""

    @field_validator("data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, v):
        p = Path(v)
        return p if p.is_absolute() else (BACKEND_DIR / p)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


# True when no JWT secret was configured and an ephemeral one had to be generated
EPHEMERAL_JWT_SECRET = False


@lru_cache
def get_settings() -> Settings:
    global EPHEMERAL_JWT_SECRET
    s = Settings()
    if not s.jwt_secret_key:
        if s.app_env == "production":
            raise RuntimeError("JWT_SECRET_KEY must be set in production")
        s.jwt_secret_key = secrets.token_urlsafe(64)
        EPHEMERAL_JWT_SECRET = True
        log.warning(
            "JWT_SECRET_KEY not set - generated an ephemeral secret. "
            "Tokens will be invalidated on restart. Set JWT_SECRET_KEY in .env."
        )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    (s.data_dir / "reports").mkdir(exist_ok=True)
    (s.data_dir / "models").mkdir(exist_ok=True)
    return s
