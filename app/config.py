"""Application configuration loaded from environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PayDawg"
    app_env: str = "development"
    database_url: str = "sqlite:///./paydawg.db"
    demo_mode: bool = True
    cors_origins: str = "http://127.0.0.1:8000,http://localhost:8000"
    duplicate_window_seconds: int = 300
    velocity_window_seconds: int = 300
    velocity_max_payments: int = 5
    amount_outlier_multiplier: float = 4.0
    min_baseline_samples: int = 3
    llm_provider: str = "none"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    llm_timeout_seconds: float = 8.0
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_enabled: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
