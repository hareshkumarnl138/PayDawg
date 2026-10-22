"""Environment-only application settings."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: str) -> int:
    """A whole number from the environment, with an error that names the setting (a typo in .env otherwise
    stops the server with a bare 'invalid literal for int()')."""
    raw = os.getenv(name, default).strip() or default
    try:
        return int(raw)
    except ValueError:
        raise RuntimeError(f"{name} in .env must be a whole number, got '{raw}'.") from None


def _float(name: str, default: str) -> float:
    raw = os.getenv(name, default).strip() or default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"{name} in .env must be a number, got '{raw}'.") from None


@dataclass(frozen=True)
class Settings:
    database_path: str = os.getenv("DATABASE_PATH", "paydawg.sqlite3")
    rail_provider: str = os.getenv("PAYPAL_MODE", "mock").strip().lower()
    paypal_client_id: str = os.getenv("PAYPAL_CLIENT_ID", "").strip()
    paypal_client_secret: str = os.getenv("PAYPAL_CLIENT_SECRET", "").strip()
    paypal_base_url: str = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com").strip().rstrip("/")
    paypal_webhook_id: str = os.getenv("PAYPAL_WEBHOOK_ID", "").strip()
    # Where this server is reachable by buyers (PayPal redirects them back here). Set it when deployed.
    # On Render, RENDER_EXTERNAL_URL (set by Render itself) is used when PUBLIC_BASE_URL is not given.
    public_base_url: str = (os.getenv("PUBLIC_BASE_URL", "").strip() or os.getenv("RENDER_EXTERNAL_URL", "").strip()
                            or "http://localhost:8000").rstrip("/")
    # Where the buyer pages after PayPal link back to ("Back to the shop"). Empty hides the link.
    shop_url: str = os.getenv("SHOP_URL", "/shop").strip()
    # When set, the merchant console endpoints (list, details, approve, void, demo reset) need this token.
    admin_token: str = os.getenv("ADMIN_TOKEN", "").strip()
    llm_provider: str = os.getenv("LLM_PROVIDER", "none").strip().lower()
    llm_timeout_seconds: float = _float("LLM_TIMEOUT_SECONDS", "10")
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate").strip()
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2").strip()
    http_api_url: str = os.getenv("LLM_HTTP_API_URL", "").strip()
    http_api_key: str = os.getenv("LLM_HTTP_API_KEY", "").strip()
    http_api_model: str = os.getenv("LLM_HTTP_API_MODEL", "").strip()
    # IANA name such as Asia/Kolkata. Empty means the server's local time.
    merchant_timezone: str = os.getenv("MERCHANT_TIMEZONE", "").strip()
    duplicate_window_seconds: int = _int("DUPLICATE_WINDOW_SECONDS", "120")
    velocity_limit: int = _int("VELOCITY_LIMIT", "5")
    velocity_window_minutes: int = _int("VELOCITY_WINDOW_MINUTES", "10")
    large_amount_multiple: float = _float("LARGE_AMOUNT_MULTIPLE", "5.0")
    rate_limit_attempts: int = _int("RATE_LIMIT_ATTEMPTS", "12")
    rate_limit_window_seconds: int = _int("RATE_LIMIT_WINDOW_SECONDS", "10")
    rate_limit_lock_seconds: int = _int("RATE_LIMIT_LOCK_SECONDS", "15")
    # Shop-wide ceiling, so a client rotating its apparent IP cannot create payments without limit. 0 disables.
    rate_limit_global_attempts: int = _int("RATE_LIMIT_GLOBAL_ATTEMPTS", "120")
    # Only true behind a proxy you control; otherwise a forged X-Forwarded-For would get its own quota.
    trust_proxy_headers: bool = _bool("TRUST_PROXY_HEADERS", False)
    merchant_surge_limit: int = _int("MERCHANT_SURGE_LIMIT", "15")
    # Any single payment above this is held for the shop to review (Growl), even for a brand-new shop. 0 disables.
    hard_review_amount: float = _float("HARD_REVIEW_AMOUNT", "500")
    # Demo shop only: refuse placeholder and throwaway email addresses (example.com, test domains, temporary-mail sites).
    block_fake_emails: bool = _bool("BLOCK_FAKE_EMAILS", True)
    # PayPal mode only. after_approval: a Bark buyer still sees PayPal's approve screen, then Dawg stops the payment
    # (no authorization or capture is ever made, so no money moves). before_paypal: Bark never reaches PayPal.
    bark_stage: str = os.getenv("BARK_STAGE", "after_approval").strip().lower().replace("-", "_")


settings = Settings()
