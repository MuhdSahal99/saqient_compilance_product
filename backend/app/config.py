from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "change-me-in-production"  # noqa: S105 - sentinel, rejected in production

AIProviderName = Literal["disabled", "mock", "openai_compatible", "jais", "falcon"]


class ConfigError(RuntimeError):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    secret_key: str = INSECURE_SECRET
    demo_mode: bool = False

    database_url: str = "postgresql+psycopg://saqient:saqient@localhost:5432/saqient"
    redis_url: str = "redis://localhost:6379/0"
    celery_task_always_eager: bool = False

    cors_origins: str = "http://localhost:5173"
    session_idle_minutes: int = 60
    session_absolute_hours: int = 12
    cookie_secure: bool = False
    login_rate_limit: int = 10  # attempts per window per ip+email
    login_rate_window_seconds: int = 300

    storage_backend: Literal["local", "s3", "gcs"] = "local"
    storage_local_path: str = "./storage"
    s3_bucket: str = ""
    s3_endpoint_url: str = ""
    s3_region: str = ""
    gcs_bucket: str = ""

    max_upload_mb: int = 20
    max_pdf_pages: int = 300
    max_extracted_chars: int = 2_000_000
    processing_time_limit_seconds: int = 120
    job_max_attempts: int = 3

    ai_enabled: bool = False
    ai_provider: AIProviderName = "disabled"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = Field(default="", repr=False)
    ai_timeout_seconds: int = 30
    ai_max_input_chars: int = 12_000
    ai_max_output_tokens: int = 800
    ai_allowed_hosts: str = ""
    ai_serving_interface_verified: bool = False
    # Plain http to an allowlisted host, for a model server on a private network only
    # (for example the compose "inference" service). Never for a public endpoint.
    ai_allow_insecure_http: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_allowed_host_list(self) -> list[str]:
        return [h.strip().lower() for h in self.ai_allowed_hosts.split(",") if h.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_for_production(self) -> None:
        """Refuse to start with insecure defaults when APP_ENV=production."""
        if not self.is_production:
            return
        problems: list[str] = []
        if self.secret_key == INSECURE_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be set to a random value of at least 32 characters")
        if self.demo_mode:
            problems.append("DEMO_MODE must be false in production")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if self.celery_task_always_eager:
            problems.append("CELERY_TASK_ALWAYS_EAGER must be false in production")
        if self.ai_provider == "mock":
            problems.append("AI_PROVIDER=mock is not allowed in production")
        if problems:
            raise ConfigError("; ".join(problems))

    def validate_ai(self) -> None:
        if not self.ai_enabled:
            return
        if self.ai_provider == "disabled":
            raise ConfigError("AI_ENABLED=true requires an AI_PROVIDER")
        if self.ai_provider in ("jais", "falcon") and not self.ai_serving_interface_verified:
            raise ConfigError(
                f"AI_PROVIDER={self.ai_provider} requires AI_SERVING_INTERFACE_VERIFIED=true "
                "after the serving API has been verified (docs/MODEL_INTEGRATION.md)"
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
