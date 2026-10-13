"""PayDawg FastAPI application entry point."""
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.api.payments import router as payments_router
from app.api.webhooks import router as webhooks_router
from app.config import get_settings
from app.db.database import init_db

BASE_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = BASE_DIR / "dashboard"

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield

settings = get_settings()
app = FastAPI(title=settings.app_name, description="AI-assisted payment risk screening for PayPal Sandbox", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Idempotency-Key", "PayPal-Auth-Algo", "PayPal-Cert-Url", "PayPal-Transmission-Id", "PayPal-Transmission-Sig", "PayPal-Transmission-Time"])
app.include_router(payments_router)
app.include_router(webhooks_router)

@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.app_env, "paypal_enabled": settings.paypal_enabled, "llm_enabled": settings.llm_provider.lower() == "openai" and bool(settings.openai_api_key)}

@app.get("/", include_in_schema=False, response_class=HTMLResponse)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_DIR / "index.html")

app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")

@app.post("/v1/demo/reset", tags=["demo"])
def reset_demo() -> dict:
    """Convenience reset for local demo only; disabled outside explicit demo mode."""
    if not settings.demo_mode or settings.app_env.lower() == "production":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    from app.db.database import SessionLocal
    from app.db.models import MerchantBaseline, Payment, PaymentEvent
    db = SessionLocal()
    try:
        db.query(PaymentEvent).delete()
        db.query(Payment).delete()
        db.query(MerchantBaseline).delete()
        db.commit()
        return {"reset": True}
    finally:
        db.close()
