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
    rail_provider: str = os.getenv("PAYPAL_MODE", "mock").strip().lower()
    paypal_client_id: str = os.getenv("PAYPAL_CLIENT_ID", "")
    paypal_client_secret: str = os.getenv("PAYPAL_CLIENT_SECRET", "")
    paypal_base_url: str = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").rstrip("/")
    paypal_webhook_id: str = os.getenv("PAYPAL_WEBHOOK_ID", "")
    # Where this server is reachable by buyers (PayPal redirects them back here). Set it when deployed.
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
    # When set, the merchant console endpoints (list, details, approve, void, demo reset) need this token.
    admin_token: str = os.getenv("ADMIN_TOKEN", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "none").strip().lower()
    llm_timeout_seconds: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "10"))
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2")
    http_api_url: str = os.getenv("LLM_HTTP_API_URL", "")
    http_api_key: str = os.getenv("LLM_HTTP_API_KEY", "")
    http_api_model: str = os.getenv("LLM_HTTP_API_MODEL", "")
    # IANA name such as Asia/Kolkata. Empty means the server's local time.
    merchant_timezone: str = os.getenv("MERCHANT_TIMEZONE", "").strip()
    duplicate_window_seconds: int = int(os.getenv("DUPLICATE_WINDOW_SECONDS", "120"))
    velocity_limit: int = int(os.getenv("VELOCITY_LIMIT", "5"))
    velocity_window_minutes: int = int(os.getenv("VELOCITY_WINDOW_MINUTES", "10"))
    large_amount_multiple: float = float(os.getenv("LARGE_AMOUNT_MULTIPLE", "5.0"))
    rate_limit_attempts: int = int(os.getenv("RATE_LIMIT_ATTEMPTS", "12"))
    rate_limit_window_seconds: int = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "10"))
    rate_limit_lock_seconds: int = int(os.getenv("RATE_LIMIT_LOCK_SECONDS", "15"))
    # Shop-wide ceiling, so a client rotating its apparent IP cannot create payments without limit. 0 disables.
    rate_limit_global_attempts: int = int(os.getenv("RATE_LIMIT_GLOBAL_ATTEMPTS", "120"))
    # Only true behind a proxy you control; otherwise a forged X-Forwarded-For would get its own quota.
    trust_proxy_headers: bool = _bool("TRUST_PROXY_HEADERS", False)
    merchant_surge_limit: int = int(os.getenv("MERCHANT_SURGE_LIMIT", "15"))


settings = Settings()
