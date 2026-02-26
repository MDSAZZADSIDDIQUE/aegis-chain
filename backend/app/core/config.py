"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Elastic
    elastic_cloud_id: str = ""
    elastic_api_key: str = ""
    elastic_url: str = "http://localhost:9200"
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://172.16.0.1:3000",
    ]

    # NOAA
    noaa_user_agent: str = "AegisChain/1.0 (contact@aegischain.dev)"

    # NASA FIRMS
    nasa_firms_map_key: str = ""

    # Mapbox
    mapbox_access_token: str = ""
    mapbox_secret_token: str = ""

    # Slack
    slack_webhook_url: str = ""
    slack_signing_secret: str = ""

    # Anthropic
    anthropic_api_key: str = ""

    # AegisChain API authentication
    # Set to a non-empty secret to enable X-AegisChain-Key header validation.
    # Leave empty to disable auth (development / local mode).
    aegis_api_key: str = ""

    # App
    hitl_cost_threshold_usd: float = 50_000.0
    poll_interval_seconds: int = 300
    rl_penalty_factor: float = 0.05
    rl_reward_factor: float = 0.02
    log_level: str = "INFO"


settings = Settings()
