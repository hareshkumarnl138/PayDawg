"""Environment-only application settings."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "paydawg.sqlite3")
    app_env: str = os.getenv("APP_ENV", "development")
    rail_provider: str = os.getenv("PAYPAL_MODE", "mock").strip().lower()
    paypal_client_id: str = os.getenv("PAYPAL_CLIENT_ID", "")
    paypal_client_secret: str = os.getenv("PAYPAL_CLIENT_SECRET", "")
    paypal_base_url: str = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
    paypal_webhook_id: str = os.getenv("PAYPAL_WEBHOOK_ID", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "none").strip().lower()
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    http_api_url: str = os.getenv("LLM_HTTP_API_URL", "")
    http_api_key: str = os.getenv("LLM_HTTP_API_KEY", "")
    http_api_model: str = os.getenv("LLM_HTTP_API_MODEL", "")
    duplicate_window_seconds: int = int(os.getenv("DUPLICATE_WINDOW_SECONDS", "120"))
    velocity_limit: int = int(os.getenv("VELOCITY_LIMIT", "5"))
    velocity_window_minutes: int = int(os.getenv("VELOCITY_WINDOW_MINUTES", "10"))
    large_amount_multiple: float = float(os.getenv("LARGE_AMOUNT_MULTIPLE", "5.0"))
    rate_limit_attempts: int = int(os.getenv("RATE_LIMIT_ATTEMPTS", "12"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "10"))
    rate_limit_lock_seconds: int = int(os.getenv("RATE_LIMIT_LOCK_SECONDS", "15"))
    merchant_surge_limit: int = int(os.getenv("MERCHANT_SURGE_LIMIT", "15"))
    odd_hour_start: int = int(os.getenv("ODD_HOUR_START", "1"))
    odd_hour_end: int = int(os.getenv("ODD_HOUR_END", "5"))
    demo_seed: bool = _bool("DEMO_SEED", True)

settings = Settings()
