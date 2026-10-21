"""PayDawg FastAPI MVP."""
import hashlib
import json
import logging
import math
import secrets
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from app.config import settings
from app.db import init_db, db_session, add_event, update_status, payment_dict, mark_captured, reset_demo_data, seed_demo_history
from app import notebook as dawg_notebook
from app.models import PaymentCreate, utc_now
from app.pages import result_page
from app.shop import router as shop_router, SHOP_DIR
from app.engine import decide
from app.ratelimit import limiter, client_key
from app.rails.base import RailError
from app.rails.mock import MockRail
from app.rails.paypal import PayPalRail

logger = logging.getLogger("paydawg")
CLAIM_TIMEOUT_SECONDS = 120  # an "approved" capture older than this is treated as abandoned and may be retried


# Only these fields identify a payment request. Hashing an explicit list (instead of the whole model)
# keeps stored idempotency fingerprints stable when unrelated request fields are added or removed.
FINGERPRINT_FIELDS = ("merchant_id", "amount", "currency", "customer_id", "description", "order_ref")
FINGERPRINT_VERSION = "v2"
MAX_IDEMPOTENCY_KEY_LENGTH = 255
DEFAULT_MERCHANT = "demo-merchant"


def request_fingerprint(data: dict) -> str:
    payload = {field: data.get(field) for field in FINGERPRINT_FIELDS}
    return FINGERPRINT_VERSION + ":" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def validate_config():
    """Fail at startup, with a clear message, instead of failing on the first payment."""
    if settings.rail_provider not in {"mock", "paypal"}:
        raise RuntimeError(f"PAYPAL_MODE must be 'mock' or 'paypal', got '{settings.rail_provider}'.")
    if settings.llm_provider not in {"none", "ollama", "http_api"}:
        raise RuntimeError(f"LLM_PROVIDER must be 'none', 'ollama' or 'http_api', got '{settings.llm_provider}'.")
    if settings.merchant_timezone:
        try:
            ZoneInfo(settings.merchant_timezone)
        except Exception as exc:
            raise RuntimeError(f"MERCHANT_TIMEZONE '{settings.merchant_timezone}' is not a valid IANA timezone.") from exc
    if settings.rail_provider == "paypal" and not settings.admin_token:
        logger.warning("ADMIN_TOKEN is not set: anyone who can reach this server can approve or void payments.")
    if not settings.trust_proxy_headers:
        logger.info("Rate limit keys on the connecting address. uvicorn honours X-Forwarded-For from allowed peers "
                    "by default, so run it with --no-proxy-headers unless a proxy you control sits in front.")


def startup():
    validate_config()
    init_db()
    limiter.reset()


@asynccontextmanager
async def lifespan(_app):
    startup()
    yield


def require_admin(request: Request):
    """Protect the merchant console endpoints when ADMIN_TOKEN is set (header X-Admin-Token or Bearer)."""
    token = settings.admin_token
    if not token:
        return
    supplied = request.headers.get("x-admin-token", "")
    auth = request.headers.get("authorization", "")
    if not supplied and auth.lower().startswith("bearer "):
        supplied = auth[7:]
    if not secrets.compare_digest(supplied.encode(), token.encode()):
        raise HTTPException(401, "Admin token required.", headers={"WWW-Authenticate": "Bearer"})


app = FastAPI(title="PayDawg", version="1.0.0", description="Risk-aware payment orchestration MVP", lifespan=lifespan)


MAX_ECHO_DEPTH = 6        # how deep an echoed value may nest before it is summarised
MAX_ECHO_ITEMS = 20       # how many list items / dict keys of it are echoed
MAX_ECHO_CHARS = 200      # how much of an echoed string is kept


def _json_safe(value, depth: int = 0):
    """Bound and sanitise a value echoed back in a 422 body.

    FastAPI echoes the offending input. Unbounded, that lets a client choose the response: a NaN
    amount is not JSON-serialisable, and a deeply nested body overflows the encoder's recursion -
    either one would turn a clean 422 into a 500.
    """
    if depth > MAX_ECHO_DEPTH:
        return "<nested value omitted>"
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, str):
        return value if len(value) <= MAX_ECHO_CHARS else value[:MAX_ECHO_CHARS] + "..."
    if isinstance(value, dict):
        return {k: _json_safe(v, depth + 1) for k, v in list(value.items())[:MAX_ECHO_ITEMS]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v, depth + 1) for v in list(value)[:MAX_ECHO_ITEMS]]
    return value


MAX_BODY_BYTES = 64 * 1024  # a payment request is a few hundred bytes; nothing legitimate comes close


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    """Reject an oversized body up front instead of buffering it into memory."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": f"Request body must be at most {MAX_BODY_BYTES} bytes."})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(_json_safe(exc.errors()))})
DASHBOARD = Path(__file__).resolve().parent.parent / "dashboard"
app.mount("/dashboard", StaticFiles(directory=str(DASHBOARD)), name="dashboard")
# The demo pet shop (app/shop.py): its page at /shop, its files at /shop/assets.
app.include_router(shop_router)
app.mount("/shop/assets", StaticFiles(directory=str(SHOP_DIR)), name="shop")


def buyer_page(outcome: str, payment: dict | None = None) -> str:
    """The Dawg page a buyer sees after PayPal, linking back to the shop when SHOP_URL is set."""
    return result_page(outcome, payment, back_url=settings.shop_url or None)

def get_rail():
    if settings.rail_provider == "mock":
        return MockRail()
    if settings.rail_provider == "paypal":
        return PayPalRail()
    raise HTTPException(500, "Unsupported PAYPAL_MODE. Choose mock or paypal.")

async def settle_buyer_approval(payment: dict, success_event: str, failure_event: str) -> str:
    """Run the rail step that follows buyer approval: Growl -> authorize (held), Wag -> capture.

    Used by the real PayPal return route and by the SIMULATED mock buyer approval.
    Returns the new status; marks the payment failed and re-raises if the rail errors.
    """
    try:
        rail = get_rail()
        if payment["verdict"] == "Growl":
            result = await rail.authorize(payment)
            if not result.get("authorization_id") and not result.get("simulated"):
                raise RailError("Provider did not return an authorization ID.")
            status = "held"
        else:
            result = await rail.capture(payment)
            status = "captured"
    except Exception as exc:
        with db_session() as db:
            update_status(db, payment["id"], "failed", failure_event, {"error": str(exc)[:200]})
        raise
    with db_session() as db:
        if result.get("authorization_id"):
            db.execute("UPDATE payments SET provider_authorization_id=? WHERE id=?", (result["authorization_id"], payment["id"]))
        if result.get("capture_id"):
            db.execute("UPDATE payments SET provider_capture_id=? WHERE id=?", (result["capture_id"], payment["id"]))
        details = {"rail": settings.rail_provider, "simulated": result.get("simulated", False)}
        if status == "captured":
            mark_captured(db, payment["id"], success_event, details)
        else:
            update_status(db, payment["id"], "held", success_event, details)
    return status

@app.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(DASHBOARD / "index.html")

SOUND_NAMES = {"bark": "bark", "growl": "growl", "wag": "happy", "tired": "whine", "sleep": "snore"}
SOUND_TYPES = ("ogg", "wav", "mp3", "m4a")

@app.get("/dog-sounds", include_in_schema=False)
def dog_sounds():
    """Which of Dawg's real recordings exist in dashboard/sounds/ (mood -> file name). The page loads only
    these, so a missing recording costs nothing and Dawg keeps his built-in sound for it."""
    found = {}
    for mood, name in SOUND_NAMES.items():
        for ext in SOUND_TYPES:
            if (DASHBOARD / "sounds" / f"{name}.{ext}").is_file():
                found[mood] = f"{name}.{ext}"
                break
    return found

@app.get("/v1/rate-limit")
def rate_limit_status(request: Request):
    """Is this client currently locked out? The dashboard polls this so the Dawg can sleep on cue."""
    return limiter.status(client_key(request))

@app.post("/v1/demo/reset", dependencies=[Depends(require_admin)])
def demo_reset():
    """Mock mode only: wipe demo payments and the Notebook (same as demo_shop/reset_demo.py)."""
    if settings.rail_provider != "mock":
        raise HTTPException(403, "Demo reset is only available when PAYPAL_MODE=mock.")
    reset_demo_data()
    limiter.reset()
    return {"ok": True}

@app.post("/v1/demo/seed", dependencies=[Depends(require_admin)])
def demo_seed(merchant_id: str = DEFAULT_MERCHANT):
    """Mock mode only, SIMULATED: give the shop's Notebook about two weeks of past trading, so a live
    simulation starts from a shop with a past instead of a brand-new one. Payments are not touched."""
    if settings.rail_provider != "mock":
        raise HTTPException(403, "Seeding a simulated history is only available when PAYPAL_MODE=mock.")
    with db_session() as db:
        if not db.execute("SELECT 1 FROM notebook WHERE merchant_id=?", (merchant_id,)).fetchone():
            raise HTTPException(404, "Merchant not found.")
    seed_demo_history(merchant_id)
    return notebook_summary(merchant_id)


def notebook_summary(merchant_id: str) -> dict:
    with db_session() as db:
        row = db.execute("SELECT * FROM notebook WHERE merchant_id=?", (merchant_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Merchant not found.")
        since = (datetime.now(timezone.utc) - timedelta(minutes=settings.velocity_window_minutes)).isoformat()
        recent_count = db.execute("SELECT COUNT(*) FROM payments WHERE merchant_id=? AND created_at >= ?",
                                  (merchant_id, since)).fetchone()[0]
    return dawg_notebook.summary(dict(row), dawg_notebook.to_local(datetime.now(timezone.utc)), recent_count)


@app.get("/v1/notebook", dependencies=[Depends(require_admin)])
def get_notebook(merchant_id: str = DEFAULT_MERCHANT):
    """What Dawg has learned about this shop, and the limits the rules apply right now."""
    return notebook_summary(merchant_id)

@app.get("/health")
def health():
    return {"ok": True, "rail": settings.rail_provider, "llm": settings.llm_provider,
            "simulated": settings.rail_provider == "mock"}

@app.post("/v1/payments")
async def create_payment(body: PaymentCreate, request: Request, response: Response,
                         idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    allowed, retry_after, remaining = limiter.hit(client_key(request))
    if not allowed:
        raise HTTPException(429, f"Too many requests. Dawg is resting, try again in {retry_after} seconds.",
                            headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(settings.rate_limit_attempts),
                                     "X-RateLimit-Remaining": "0"})
    if remaining >= 0:
        response.headers["X-RateLimit-Limit"] = str(settings.rate_limit_attempts)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
    if settings.rail_provider == "paypal" and (not settings.paypal_client_id or not settings.paypal_client_secret):
        raise HTTPException(503, "PayPal sandbox credentials are not configured.")
    request_data = body.model_dump()
    request_data["currency"] = body.currency.upper()
    request_hash = request_fingerprint(request_data)
    key = (idempotency_key or "").strip() or None
    if key and len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise HTTPException(400, f"Idempotency-Key must be at most {MAX_IDEMPOTENCY_KEY_LENGTH} characters.")
    with db_session() as db:
        merchant = db.execute("SELECT id FROM merchants WHERE id=?", (body.merchant_id,)).fetchone()
        if not merchant:
            raise HTTPException(404, "Merchant not found.")
        if key:
            existing = db.execute("SELECT * FROM payments WHERE merchant_id=? AND idempotency_key=?", (body.merchant_id, key)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    if not str(existing["request_hash"]).startswith(FINGERPRINT_VERSION + ":"):
                        raise HTTPException(409, "This Idempotency-Key was stored by an older build of PayDawg, so the "
                                                 "request cannot be compared. In mock mode run demo_shop/reset_demo.py, "
                                                 "or send a new key.")
                    raise HTTPException(409, "Idempotency key was already used for a different request.")
                return payment_dict(existing)
        notebook_row = db.execute("SELECT * FROM notebook WHERE merchant_id=?", (body.merchant_id,)).fetchone()
        notebook = dict(notebook_row) if notebook_row else {}
        cols = "id, merchant_id, amount, customer_id, order_ref, created_at, status"
        # Everything inside the rule windows (not a fixed number of rows), so the shop-wide count stays right
        # however busy the shop is. The cap only guards memory.
        since = (datetime.now(timezone.utc) - timedelta(
            seconds=max(settings.velocity_window_minutes * 60, settings.duplicate_window_seconds))).isoformat()
        recent = {row["id"]: dict(row) for row in db.execute(
            f"SELECT {cols} FROM payments WHERE merchant_id=? AND created_at >= ? ORDER BY created_at DESC LIMIT 5000",
            (body.merchant_id, since)).fetchall()}
        # A long-standing customer must not look "new" just because their last payment is older than the window.
        for row in db.execute(f"SELECT {cols} FROM payments WHERE merchant_id=? AND customer_id=? ORDER BY created_at DESC LIMIT 25",
                              (body.merchant_id, body.customer_id)).fetchall():
            recent.setdefault(row["id"], dict(row))
        recent = list(recent.values())
        pid = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        payment = {"id": pid, **request_data, "created_at": created_at}
        decision = await decide(payment, notebook, recent)
        status = "blocked" if decision["verdict"] == "Bark" else "screened"
        try:
            db.execute("""INSERT INTO payments
                (id,merchant_id,idempotency_key,request_hash,amount,currency,customer_id,description,order_ref,verdict,risk_level,reasons_json,flags_json,decision_source,status,rail,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (pid, body.merchant_id, key, request_hash, body.amount, body.currency.upper(), body.customer_id,
                 body.description, (body.order_ref or "").strip() or None, decision["verdict"], decision["risk_level"], json.dumps(decision["reasons"]),
                 json.dumps(decision["flags"]), decision["decision_source"], "created", settings.rail_provider, created_at, created_at))
        except sqlite3.IntegrityError:
            # Two requests with the same Idempotency-Key raced past the check above; the loser returns the winner's payment.
            existing = db.execute("SELECT * FROM payments WHERE merchant_id=? AND idempotency_key=?", (body.merchant_id, key)).fetchone() if key else None
            if not existing:
                raise
            if existing["request_hash"] != request_hash:
                raise HTTPException(409, "Idempotency key was already used for a different request.")
            return payment_dict(existing)
        add_event(db, pid, "payment.created", None, "created", {"amount": body.amount, "currency": body.currency.upper()})
        update_status(db, pid, status, "payment.screened",
                      {"verdict": decision["verdict"], "reasons": decision["reasons"], "decision_source": decision["decision_source"]})
        barked = status == "blocked"
        if barked and not (settings.rail_provider == "paypal" and settings.bark_stage == "after_approval"):
            return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())
        stored = dict(db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())
    # A Bark payment (BARK_STAGE=after_approval) still gets a PayPal order so the buyer sees the approve screen,
    # but it is only ever approved, never authorized or captured: when PayPal sends the buyer back, Dawg stops it
    # and no money moves. AUTHORIZE is used so that even a stray capture attempt has nothing to capture.
    intent = "AUTHORIZE" if decision["verdict"] in ("Growl", "Bark") else "CAPTURE"
    try:
        result = await get_rail().create({**stored, "return_url": settings.public_base_url + "/paypal/return",
                                          "cancel_url": settings.public_base_url + "/paypal/cancel"}, intent)
    except Exception as exc:
        if barked:
            # The payment is already blocked and nothing was sent to PayPal: simply decline it.
            with db_session() as db:
                add_event(db, pid, "rail.order_skipped", "blocked", "blocked", {"error": str(exc)[:200]})
                return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())
        with db_session() as db:
            update_status(db, pid, "failed", "rail.create_failed", {"error": str(exc)[:200]})
        raise HTTPException(502, "Payment rail could not create the order.") from exc
    with db_session() as db:
        db.execute("UPDATE payments SET provider_order_id=?, approval_url=?, updated_at=? WHERE id=?",
                   (result.get("order_id"), result.get("approval_url"), datetime.now(timezone.utc).isoformat(), pid))
        add_event(db, pid, "rail.order_created", status, status, {"rail": settings.rail_provider, "intent": intent, "simulated": result.get("simulated", False)})
        stored = dict(db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())
    if status == "blocked":
        return payment_dict(stored)
    if result.get("simulated") and not result.get("approval_url"):
        # SIMULATED: mock mode has no real buyer, so the buyer-approval step is simulated here.
        # Wag is captured and Growl is held, exactly as the PayPal return route would do.
        try:
            await settle_buyer_approval(stored, "mock.buyer_approved", "mock.buyer_approval_failed")
        except Exception as exc:
            raise HTTPException(502, "Simulated rail could not complete the payment.") from exc
    with db_session() as db:
        return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (pid,)).fetchone())

@app.get("/v1/payments", dependencies=[Depends(require_admin)])
def list_payments(limit: int = 100, merchant_id: str = DEFAULT_MERCHANT):
    """One merchant's payments. The console is single-tenant: ADMIN_TOKEN is one operator
    credential, not a per-merchant login, so scoping keeps shops from seeing each other by accident."""
    limit = max(1, min(limit, 500))
    with db_session() as db:
        rows = db.execute("SELECT * FROM payments WHERE merchant_id=? ORDER BY created_at DESC LIMIT ?",
                          (merchant_id, limit)).fetchall()
        return {"merchant_id": merchant_id, "payments": [payment_dict(row) for row in rows]}

@app.get("/v1/payments/{payment_id}", dependencies=[Depends(require_admin)])
def get_payment(payment_id: str, merchant_id: str = DEFAULT_MERCHANT):
    with db_session() as db:
        row = db.execute("SELECT * FROM payments WHERE id=? AND merchant_id=?", (payment_id, merchant_id)).fetchone()
        if not row:
            raise HTTPException(404, "Payment not found.")
        result = payment_dict(row)
        result["events"] = [dict(e) for e in db.execute("SELECT * FROM events WHERE payment_id=? ORDER BY id", (payment_id,)).fetchall()]
        return result

@app.post("/v1/payments/{payment_id}/approve", dependencies=[Depends(require_admin)])
async def approve_payment(payment_id: str, merchant_id: str = DEFAULT_MERCHANT):
    with db_session() as db:
        row = db.execute("SELECT * FROM payments WHERE id=? AND merchant_id=?", (payment_id, merchant_id)).fetchone()
        if not row:
            raise HTTPException(404, "Payment not found.")
        payment = dict(row)
        status = payment["status"]
        if status not in {"screened", "held", "approved"}:
            raise HTTPException(409, f"Payment cannot be approved from status {status}.")
        if status == "approved":
            # "approved" means a capture is in flight. Only an abandoned one (older than the timeout) may be retried.
            try:
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(payment["updated_at"])).total_seconds()
            except (ValueError, TypeError):
                age = CLAIM_TIMEOUT_SECONDS
            if age < CLAIM_TIMEOUT_SECONDS:
                raise HTTPException(409, "Capture is already in progress for this payment.")
        if settings.rail_provider == "paypal" and status == "screened":
            raise HTTPException(409, "Buyer must follow the PayPal approval_url first.")
        capture_authorization = payment["verdict"] == "Growl" and status in {"held", "approved"}
        if capture_authorization:
            # Compare-and-swap, so two clicks (or two browser tabs) cannot both capture the same authorization.
            claimed = db.execute("UPDATE payments SET status='approved', updated_at=? WHERE id=? AND status=? AND updated_at=?",
                                 (utc_now(), payment_id, status, payment["updated_at"]))
            if claimed.rowcount != 1:
                raise HTTPException(409, "Capture is already in progress for this payment.")
            add_event(db, payment_id, "payment.merchant_approved", status, "approved", {"rail": settings.rail_provider})
    try:
        rail = get_rail()
        if payment["verdict"] == "Growl" and not capture_authorization:
            result = await rail.authorize(payment)
            auth_id = result.get("authorization_id")
            if not auth_id and not result.get("simulated"):
                raise RailError("Provider did not return an authorization ID.")
            new_status = "held"
        else:
            result = await rail.capture(payment)
            new_status = "captured"
    except Exception as exc:
        logger.warning("Approve failed for payment %s (%s)", payment_id, type(exc).__name__)
        with db_session() as db:
            if capture_authorization:
                # The authorization is still open at the provider, so put the payment back to "held":
                # the merchant can retry the capture or void it instead of being stuck.
                update_status(db, payment_id, "held", "rail.capture_failed", {"error": str(exc)[:200]})
            else:
                update_status(db, payment_id, "failed", "rail.approve_failed", {"error": str(exc)[:200]})
        raise HTTPException(502, "Payment rail approval/capture failed. The payment was left in a state you can retry or void. Check server logs.") from exc
    with db_session() as db:
        if result.get("authorization_id"):
            db.execute("UPDATE payments SET provider_authorization_id=? WHERE id=?", (result["authorization_id"], payment_id))
        if result.get("capture_id"):
            db.execute("UPDATE payments SET provider_capture_id=? WHERE id=?", (result["capture_id"], payment_id))
        details = {"rail": settings.rail_provider, "simulated": result.get("simulated", False)}
        if new_status == "captured":
            mark_captured(db, payment_id, "payment.captured", details)
        else:
            update_status(db, payment_id, new_status, "payment.authorized", details)
        return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone())

@app.post("/v1/payments/{payment_id}/void", dependencies=[Depends(require_admin)])
async def void_payment(payment_id: str, merchant_id: str = DEFAULT_MERCHANT):
    with db_session() as db:
        row = db.execute("SELECT * FROM payments WHERE id=? AND merchant_id=?", (payment_id, merchant_id)).fetchone()
        if not row:
            raise HTTPException(404, "Payment not found.")
        payment = dict(row)
        if payment["verdict"] == "Growl" and payment["status"] == "approved":
            raise HTTPException(409, "A capture is in progress for this payment, so it cannot be voided right now.")
        if payment["verdict"] != "Growl" or payment["status"] != "held":
            raise HTTPException(409, "Only held Growl payments can be voided.")
    try:
        result = await get_rail().void(payment)
    except Exception as exc:
        logger.warning("Void failed for payment %s (%s)", payment_id, type(exc).__name__)
        raise HTTPException(502, "Payment rail could not void the authorization.") from exc
    with db_session() as db:
        update_status(db, payment_id, "voided", "payment.voided", {"rail": settings.rail_provider, "simulated": result.get("simulated", False)})
        return payment_dict(db.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone())

def wants_html(request: Request) -> bool:
    """A buyer's browser asks for text/html; API clients and tests get the JSON they always did."""
    return "text/html" in request.headers.get("accept", "")


@app.get("/paypal/return")
async def paypal_return(request: Request, token: str):
    """Handle PayPal's buyer redirect after approval of a sandbox order.
    Browsers get a small Dawg page; everything else gets JSON."""
    html = wants_html(request)
    with db_session() as db:
        row = db.execute("SELECT * FROM payments WHERE provider_order_id=?", (token,)).fetchone()
        if not row:
            if html:
                return HTMLResponse(buyer_page("notfound"), status_code=404)
            raise HTTPException(404, "PayPal order was not found.")
        payment = dict(row)
        if payment["status"] == "blocked":
            # Dawg barked at this payment before PayPal: the buyer approved an order that is never authorized or
            # captured, so nothing is charged. Record that once and tell the buyer.
            if not db.execute("SELECT 1 FROM events WHERE payment_id=? AND event_type='paypal.buyer_returned_blocked'",
                              (payment["id"],)).fetchone():
                add_event(db, payment["id"], "paypal.buyer_returned_blocked", "blocked", "blocked", {"order_id": token})
            if html:
                return HTMLResponse(buyer_page("barked", payment))
            return {"payment_id": payment["id"], "status": "blocked", "verdict": payment["verdict"],
                    "message": "Dawg stopped this payment. Nothing was charged."}
        if payment["status"] != "screened":
            if html:
                outcome = payment["status"] if payment["status"] in {"captured", "held"} else "processed"
                return HTMLResponse(buyer_page(outcome, payment))
            return {"payment_id": payment["id"], "status": payment["status"], "message": "Payment already processed."}
        # Claim the payment before touching the rail, so a refresh or a second tab on this page cannot
        # capture or authorize the same order twice. The loser sees "already processed".
        claimed = db.execute("UPDATE payments SET status='approved', updated_at=? WHERE id=? AND status='screened'",
                             (utc_now(), payment["id"]))
        if claimed.rowcount != 1:
            if html:
                return HTMLResponse(buyer_page("processed", payment))
            return {"payment_id": payment["id"], "status": "approved", "message": "Payment already processed."}
        add_event(db, payment["id"], "paypal.buyer_returned", "screened", "approved", {"order_id": token})
    try:
        status = await settle_buyer_approval(payment, "paypal.buyer_approved", "paypal.return_failed")
    except Exception as exc:
        if html:
            return HTMLResponse(buyer_page("error", payment), status_code=502)
        raise HTTPException(502, "PayPal buyer approval was received, but the payment operation failed.") from exc
    if html:
        return HTMLResponse(buyer_page("held" if status == "held" else "captured", payment))
    return {"payment_id": payment["id"], "status": status, "verdict": payment["verdict"],
            "message": "Authorization held for merchant review." if status == "held" else "Payment captured."}

@app.get("/paypal/cancel")
def paypal_cancel(request: Request, token: str | None = None):
    """Record a buyer-cancelled PayPal checkout without attempting capture."""
    if token:
        with db_session() as db:
            row = db.execute("SELECT id, status FROM payments WHERE provider_order_id=?", (token,)).fetchone()
            # Only a checkout still waiting for the buyer can be cancelled. A captured, held or blocked payment
            # keeps its status, so a stale or replayed cancel link cannot overwrite a real result.
            if row and row["status"] == "screened":
                update_status(db, row["id"], "failed", "paypal.buyer_cancelled", {"order_id": token})
    if wants_html(request):
        return HTMLResponse(buyer_page("cancelled"))
    return {"status": "cancelled", "message": "Buyer cancelled PayPal checkout."}

@app.post("/webhooks/paypal")
async def paypal_webhook(request: Request):
    # TODO: Verify the header set and verification endpoint against current PayPal webhook docs before production use.
    if settings.rail_provider != "paypal" or not settings.paypal_webhook_id:
        raise HTTPException(503, "PayPal webhook verification is not configured.")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "Webhook body must be JSON.")
    if not isinstance(payload, dict):
        raise HTTPException(400, "Webhook body must be a JSON object.")
    headers = {
        "auth_algo": request.headers.get("paypal-auth-algo", ""),
        "cert_url": request.headers.get("paypal-cert-url", ""),
        "transmission_id": request.headers.get("paypal-transmission-id", ""),
        "transmission_sig": request.headers.get("paypal-transmission-sig", ""),
        "transmission_time": request.headers.get("paypal-transmission-time", ""),
        "webhook_id": settings.paypal_webhook_id,
        "webhook_event": payload,
    }
    try:
        verified = await get_rail()._request("POST", "/v1/notifications/verify-webhook-signature", json_body=headers)
    except Exception as exc:
        raise HTTPException(502, "Could not verify PayPal webhook.") from exc
    if verified.get("verification_status") != "SUCCESS":
        raise HTTPException(400, "Invalid PayPal webhook signature.")
    event_id = payload.get("id")
    if not event_id:
        raise HTTPException(400, "Webhook event ID is required.")
    resource = payload.get("resource") or {}
    related = (resource.get("supplementary_data") or {}).get("related_ids") or {}
    # A webhook can name the order, the authorization or the capture; match a payment on any of them.
    ids = [i for i in {related.get("order_id"), related.get("authorization_id"), resource.get("id")} if i]
    with db_session() as db:
        try:
            db.execute("INSERT INTO webhook_events(event_id, received_at) VALUES(?,datetime('now'))", (event_id,))
        except sqlite3.IntegrityError:
            return {"received": True, "duplicate": True}
        row = None
        if ids:
            marks = ",".join("?" * len(ids))
            row = db.execute(f"SELECT * FROM payments WHERE provider_order_id IN ({marks}) OR provider_capture_id IN ({marks}) "
                             f"OR provider_authorization_id IN ({marks})", ids * 3).fetchone()
        if not row:
            return {"received": True, "matched": False}
        payment_id, old_status = row["id"], row["status"]
        event_type = payload.get("event_type", "")
        if event_type == "PAYMENT.CAPTURE.COMPLETED":
            mark_captured(db, payment_id, "webhook.paypal.capture_completed", {"event_id": event_id})
        elif event_type in {"PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"}:
            update_status(db, payment_id, "refunded", "webhook.paypal.refund_or_reversal", {"event_id": event_id})
        elif event_type in {"PAYMENT.AUTHORIZATION.VOIDED", "CHECKOUT.ORDER.VOIDED"}:
            update_status(db, payment_id, "voided", "webhook.paypal.voided", {"event_id": event_id})
        else:
            add_event(db, payment_id, "webhook.paypal.received", old_status, old_status, {"event_id": event_id, "event_type": event_type})
    return {"received": True, "matched": True}
