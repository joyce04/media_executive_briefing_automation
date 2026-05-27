import os
import re
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

_ENV_VAR_RE = re.compile(r"\$\{([^}]+)\}")


def _interpolate_env(obj):
    """Recursively replace ${VAR_NAME} placeholders with environment variable values."""
    if isinstance(obj, dict):
        return {k: _interpolate_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_env(v) for v in obj]
    if isinstance(obj, str):
        return _ENV_VAR_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), obj)
    return obj


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM backend selection (this variant runs against Claude subscription) ---
    # "auto"      : try agent_sdk -> cli -> api_key in order (default; recommended)
    # "agent_sdk" : force claude-agent-sdk (Pro/Max OAuth)
    # "cli"       : force raw `claude -p` subprocess
    # "api_key"   : force anthropic SDK with ANTHROPIC_API_KEY
    llm_backend: Literal["auto", "agent_sdk", "cli", "api_key"] = Field("auto", alias="LLM_BACKEND")
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")

    naver_client_id: str = Field("", alias="NAVER_CLIENT_ID")
    naver_client_secret: str = Field("", alias="NAVER_CLIENT_SECRET")

    smtp_host: str = Field("smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str = Field("", alias="SMTP_USER")
    smtp_password: str = Field("", alias="SMTP_PASSWORD")

    database_path: str = Field("./data/media_intel_local.db", alias="DATABASE_PATH")
    reports_output_dir: str = Field("./data/reports", alias="REPORTS_OUTPUT_DIR")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    # Auth & services (populated by env vars)
    jwt_secret: str = Field("change-me-in-production", alias="JWT_SECRET")
    google_client_id: str = Field("", alias="GOOGLE_CLIENT_ID")
    google_client_secret: str = Field("", alias="GOOGLE_CLIENT_SECRET")
    stripe_secret_key: str = Field("", alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field("", alias="STRIPE_WEBHOOK_SECRET")
    frontend_url: str = Field("http://localhost:3000", alias="FRONTEND_URL")

    # Model names -- Anthropic direct IDs (no OpenRouter prefix).
    # The agent_sdk and cli backends accept these short names; the api_key
    # backend forwards them to anthropic.messages.create() unchanged.
    haiku_model: str = "claude-haiku-4-5"
    sonnet_model: str = "claude-sonnet-4-6"
    opus_model: str = "claude-opus-4-7"

    # Pipeline thresholds
    novelty_lookback_days: int = 7
    dedup_title_overlap_threshold: float = 0.80
    short_article_char_threshold: int = 500
    collection_max_age_hours: int = Field(48, alias="COLLECTION_MAX_AGE_HOURS")


settings = Settings()
