"""
PinHire Webhook – FastAPI application entry point.

Endpoint:   POST /api/guard
Health:     GET  /health

Processing order for POST /api/guard:
    1. Read raw body bytes (needed for HMAC verification).
    2. Verify HMAC-SHA256 signature → 401 on failure.
    3. Parse JSON → 400 on malformed body.
    4. Extract event type and payload.
    5. Route to refund or FAQ handler.
    6. Return JSON response.

Security rules enforced here:
    - Signature check always runs first, before any JSON parsing.
    - Exceptions are caught globally; stack traces are never returned to clients.
    - Environment variables are never reflected in responses.
"""

import json
import logging
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.faq import answer_faq, parse_faq_payload
from app.idempotency import check_and_record
from app.refunds import RefundValidationError, validate_refund_amount
from app.security import verify_signature

# ── Logging setup (no secrets logged) ────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pinhire.webhook")

# ── FastAPI application ───────────────────────────────────────────────────────
app = FastAPI(
    title="PinHire Webhook",
    description="Secure webhook for processing refund and FAQ events.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    """
    Simple liveness probe.

    Railway and other platforms call this endpoint to confirm the process
    is running.  It does NOT authenticate.
    """
    return {"status": "ok"}


# ── Main webhook endpoint ─────────────────────────────────────────────────────
@app.post("/api/guard", tags=["Webhook"])
async def guard(request: Request) -> Response:
    """
    Primary webhook endpoint.

    Accepts signed JSON events and routes them to the appropriate handler.
    """
    settings = get_settings()

    # ── Step 1: Read raw body bytes ───────────────────────────────────────────
    raw_body: bytes = await request.body()

    # ── Step 2: HMAC signature verification ──────────────────────────────────
    supplied_sig = request.headers.get(settings.SIGNATURE_HEADER)
    if not verify_signature(raw_body, supplied_sig):
        logger.warning("Request rejected: invalid or missing HMAC signature.")
        return JSONResponse(
            status_code=401,
            content={"status": "error", "reason": "invalid_signature"},
        )

    # ── Step 3: Parse JSON ────────────────────────────────────────────────────
    try:
        body: dict[str, Any] = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError):
        logger.warning("Request rejected: malformed JSON body.")
        return JSONResponse(
            status_code=400,
            content={"status": "error", "reason": "malformed_json"},
        )

    if not isinstance(body, dict):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "reason": "malformed_json"},
        )

    # ── Step 4: Extract event type and payload ────────────────────────────────
    event: str = body.get("event", "")
    payload: Any = body.get("payload", {})

    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={"status": "error", "reason": "invalid_payload"},
        )

    # ── Step 5: Route event ───────────────────────────────────────────────────
    if event == settings.EVENT_REFUND:
        return await _handle_refund(payload, settings)

    if event == settings.EVENT_FAQ:
        return await _handle_faq(payload)

    # Unknown event type – accept but do nothing actionable.
    logger.info("Received unknown event type: %s", event)
    return JSONResponse(
        status_code=200,
        content={"status": "ignored", "reason": "unknown_event_type"},
    )


# ── Refund handler ────────────────────────────────────────────────────────────
async def _handle_refund(payload: dict[str, Any], settings: Any) -> JSONResponse:
    """Process a refund.requested event."""

    # ── Extract transaction reference ─────────────────────────────────────────
    tx_ref = payload.get(settings.TX_REF_FIELD)
    if not tx_ref or not isinstance(tx_ref, str) or not tx_ref.strip():
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "reason": "missing_tx_ref",
                "detail": f"The '{settings.TX_REF_FIELD}' field is required.",
            },
        )
    tx_ref = tx_ref.strip()

    # ── Validate refund amount (before idempotency check) ─────────────────────
    # Validation is done first so we don't record an invalid request as "seen".
    try:
        amount = validate_refund_amount(payload)
    except RefundValidationError as exc:
        if exc.reason == "refund_limit_exceeded":
            return JSONResponse(
                status_code=422,
                content={
                    "status": "rejected",
                    "reason": "refund_limit_exceeded",
                    "max_refund_aed": settings.MAX_REFUND_AED,
                },
            )
        return JSONResponse(
            status_code=422,
            content={"status": "error", "reason": exc.reason, "detail": exc.detail},
        )

    # ── Idempotency check ─────────────────────────────────────────────────────
    is_duplicate = await check_and_record(tx_ref)
    if is_duplicate:
        logger.info("Duplicate transaction detected: %s", tx_ref)
        return JSONResponse(
            status_code=200,
            content={"status": "duplicate"},
        )

    # ── Process the refund ────────────────────────────────────────────────────
    logger.info("Refund accepted: tx_ref=%s amount=%.2f AED", tx_ref, amount)
    return JSONResponse(
        status_code=200,
        content={"status": "processed"},
    )


# ── FAQ handler ───────────────────────────────────────────────────────────────
async def _handle_faq(payload: dict[str, Any]) -> JSONResponse:
    """Process a faq.query event."""
    try:
        question = parse_faq_payload(payload)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "reason": "invalid_faq_payload", "detail": str(exc)},
        )

    response_body = answer_faq(question)
    return JSONResponse(status_code=200, content=response_body)


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler that prevents stack traces from reaching clients.

    The real error is logged server-side; only a generic message is returned.
    """
    logger.exception("Unhandled exception processing request: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "reason": "internal_server_error"},
    )
