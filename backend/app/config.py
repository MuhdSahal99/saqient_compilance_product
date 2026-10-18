from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_SECRET = "change-me-in-production"  # noqa: S105 - sentinel, rejected in production

AIProviderName = Literal["disabled", "mock", "openai_compatible", "jais", "falcon"]


class ConfigError(RuntimeError):
    pass


def _is_32_byte_b64(value: str) -> bool:
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


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

    # 32 random bytes, base64. Required in production; dev/test derive one from SECRET_KEY.
    field_encryption_key: str = Field(default="", repr=False)

    # Public URL of the web app, used for links in emails (invitations, password reset).
    app_base_url: str = "http://localhost:5173"
    # file: writes .eml files to MAIL_FILE_DIR (development only); memory: tests only;
    # smtp: real delivery; disabled: nothing is sent.
    mail_backend: Literal["disabled", "file", "memory", "smtp"] = "file"
    mail_from: str = "Saqient <no-reply@localhost>"
    mail_file_dir: str = "./var/mail"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = Field(default="", repr=False)
    smtp_starttls: bool = True
    smtp_timeout_seconds: int = 10
    invitation_ttl_days: int = 7
    password_reset_ttl_minutes: int = 60
    password_reset_rate_limit: int = 5  # requests per window per ip+email
    password_reset_rate_window_seconds: int = 900
    reminder_days_ahead: int = 3

    # OCR for PDF pages without a text layer. "tesseract" runs the local binary.
    ocr_provider: Literal["disabled", "tesseract"] = "disabled"
    ocr_languages: str = "eng+ara"
    ocr_tesseract_cmd: str = "tesseract"
    ocr_dpi: int = 200
    ocr_max_pages: int = 50
    ocr_page_timeout_seconds: int = 60

    # Malware scanning of uploads through clamd (INSTREAM). Fails closed by default.
    malware_scan: Literal["disabled", "clamav"] = "disabled"
    clamav_host: str = "clamav"
    clamav_port: int = 3310
    clamav_timeout_seconds: int = 30
    malware_scan_fail_open: bool = False

    max_upload_mb: int = 20
    dataset_max_upload_mb: int = 100
    dataset_max_rows: int = 1_000_000
    max_pdf_pages: int = 300
    max_extracted_chars: int = 2_000_000
    processing_time_limit_seconds: int = 120
    job_max_attempts: int = 3

    ai_enabled: bool = False
    ai_provider: AIProviderName = "disabled"
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = Field(default="", repr=False)
    # "api_key": static bearer key (AI_API_KEY). "google": short-lived Google Cloud
    # tokens from the service account in GOOGLE_APPLICATION_CREDENTIALS (Vertex AI).
    # "google_api_key": a Google Cloud API key (AI_API_KEY) sent as x-goog-api-key.
    ai_auth: Literal["api_key", "google", "google_api_key"] = "api_key"
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
    def dataset_max_upload_bytes(self) -> int:
        return self.dataset_max_upload_mb * 1024 * 1024

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
        if not _is_32_byte_b64(self.field_encryption_key):
            problems.append("FIELD_ENCRYPTION_KEY must be set to 32 random bytes, base64")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true in production")
        if self.celery_task_always_eager:
            problems.append("CELERY_TASK_ALWAYS_EAGER must be false in production")
        if self.ai_provider == "mock":
            problems.append("AI_PROVIDER=mock is not allowed in production")
        if self.mail_backend in ("file", "memory"):
            problems.append("MAIL_BACKEND must be smtp or disabled in production")
        if self.mail_backend == "smtp" and not self.smtp_host:
            problems.append("MAIL_BACKEND=smtp requires SMTP_HOST")
        if not self.app_base_url.startswith("https://"):
            problems.append("APP_BASE_URL must be an https URL in production")
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
