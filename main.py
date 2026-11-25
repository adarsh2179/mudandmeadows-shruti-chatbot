"""
FastAPI Main Application Server for Mud & Meadows AI Concierge.

Provides REST endpoints for:
- /api/chat: Rate-limited conversational ReAct agent with SQLite WAL persistence.
- /api/voice/process: Multilingual speech-to-text processing pipeline.
- /api/payment/create-order: Server-authoritative, idempotent Razorpay order initiation.
- /api/payment/verify-and-book: Constant-time HMAC-SHA256 verification & booking commit.
- /api/payment/webhook: Asynchronous Razorpay webhook reconciliation for mobile drop-offs.
- /static: Shadow DOM embeddable widget assets.
"""

from contextlib import asynccontextmanager
import hashlib
import hmac
import json
import logging
import os
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import settings
from resort_client import resort_client, ResortAPIError
from pricing_engine import pricing_engine
from voice_service import voice_service
from agent import agent, AgentResponse
from session_store import session_store, rate_limiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mudandmeadows.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes persistent HTTP pools at startup and drains cleanly on shutdown."""
    await resort_client.startup()
    logger.info("Persistent ResortClient HTTP connection pool initialized.")
    try:
        yield
    finally:
        await resort_client.shutdown()
        logger.info("Persistent ResortClient HTTP connection pool closed.")


app = FastAPI(
    title="Mud & Meadows Resort AI Concierge API",
    version="1.1.0",
    description="Autonomous Resort Concierge with Server-Authoritative Checkout & Rate Limiting.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if settings.cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------

def _extract_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request, bucket: str, max_rpm: int) -> None:
    ip = _extract_client_ip(request)
    allowed, retry_after = rate_limiter.is_allowed(f"{bucket}:{ip}", max_rpm)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please pause briefly before sending another message.",
            headers={"Retry-After": str(retry_after)},
        )


def _verify_hmac_signature(message: str, signature: str, secret: str) -> bool:
    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=message.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# -----------------------------------------------------------------------------
# REQUEST & RESPONSE SCHEMAS
# -----------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, description="Client session ID")
    message: str = Field(min_length=1, max_length=2000, description="Guest text inquiry")


class VoiceChatResponse(BaseModel):
    success: bool
    transcription: str
    engine_used: str
    agent_response: AgentResponse


class CreateOrderRequest(BaseModel):
    cottage_id: Optional[str] = Field(default=None, description="Selected cottage ID for authoritative pricing")
    check_in: Optional[str] = Field(default=None, description="Check-in date YYYY-MM-DD")
    check_out: Optional[str] = Field(default=None, description="Check-out date YYYY-MM-DD")
    adults: int = Field(default=2, ge=1)
    children: int = Field(default=0, ge=0)
    extra_beds: int = Field(default=0, ge=0)
    coupon_code: Optional[str] = None
    session_id: Optional[str] = None
    booking_data: Optional[Dict[str, Any]] = Field(default=None, description="Staged guest details for webhook fallback")
    amount: Optional[float] = Field(default=None, gt=0, description="Accepted only in local sandbox tests when cottage details omitted")
    receipt: Optional[str] = None
    notes: Optional[Dict[str, Any]] = Field(default_factory=dict)


class VerifyAndBookRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    booking_data: Dict[str, Any]


class GuestIdentifyRequest(BaseModel):
    session_id: str = Field(min_length=1)
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


# -----------------------------------------------------------------------------
# API ROUTES
# -----------------------------------------------------------------------------

@app.get("/", tags=["Website"])
async def serve_demo_page():
    """Serves the resort demo test harness with the embedded widget."""
    return FileResponse("static/index.html")


@app.get("/health", tags=["System"])
async def health_check():
    """Healthcheck endpoint for load balancers and uptime checks."""
    return {
        "status": "healthy",
        "service": "Mud & Meadows AI Concierge",
        "environment": settings.ENVIRONMENT,
        "resort_api_target": settings.RESORT_API_BASE_URL,
    }


@app.post("/api/chat", response_model=AgentResponse, tags=["Conversational Agent"])
async def chat_endpoint(payload: ChatRequest, request: Request):
    """Rate-limited text interaction endpoint backed by persistent sessions."""
    _enforce_rate_limit(request, "chat", settings.RATE_LIMIT_CHAT_RPM)
    session_id = payload.session_id or str(uuid.uuid4())
    logger.info(f"Chat request received for session [{session_id}]")
    return await agent.chat(session_id=session_id, user_message=payload.message)


@app.get("/api/chat/history", tags=["Conversational Agent"])
async def chat_history_endpoint(session_id: str):
    """Hydrates past chat bubbles and non-sensitive profile defaults across page transitions."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id query parameter is required.")
    return {
        "session_id": session_id,
        "messages": session_store.get_display_history(session_id),
        "guest_profile": session_store.get_guest_profile(session_id),
    }


@app.post("/api/guest/identify", tags=["Conversational Agent"])
async def guest_identify_endpoint(payload: GuestIdentifyRequest):
    """Progressively binds guest contact preferences to their persistent visitor_id without login friction."""
    session_store.upsert_guest_profile(
        visitor_id=payload.session_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
    )
    return {"success": True}


@app.post("/api/voice/process", response_model=VoiceChatResponse, tags=["Voice Processing"])
async def voice_process_endpoint(
    request: Request,
    audio: UploadFile = File(..., description="Audio recording blob (WebM, WAV, MP3)"),
    session_id: Optional[str] = Form(None),
):
    """Rate-limited multilingual audio transcription routed into the concierge agent."""
    _enforce_rate_limit(request, "voice", settings.RATE_LIMIT_CHAT_RPM)
    active_session_id = session_id or str(uuid.uuid4())

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file uploaded.")

    transcription_result = await voice_service.process_audio(
        audio_bytes=audio_bytes,
        filename=audio.filename or "recording.webm",
        content_type=audio.content_type or "audio/webm",
    )

    if not transcription_result.get("success"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=transcription_result.get("error", "Failed to process audio recording."),
        )

    transcribed_text = transcription_result.get("text", "")
    agent_response = await agent.chat(session_id=active_session_id, user_message=transcribed_text)

    return VoiceChatResponse(
        success=True,
        transcription=transcribed_text,
        engine_used=transcription_result.get("engine", "unknown"),
        agent_response=agent_response,
    )


@app.post("/api/payment/create-order", tags=["Payment & Booking"])
async def create_payment_order(payload: CreateOrderRequest, request: Request):
    """
    Creates an idempotent, server-authoritative Razorpay order.
    Always recomputes total from live cottage rates and statutory GST rather than
    trusting browser-submitted monetary totals.
    """
    _enforce_rate_limit(request, "payment", settings.RATE_LIMIT_PAYMENT_RPM)

    if payload.session_id and payload.booking_data:
        session_store.upsert_guest_profile(
            visitor_id=payload.session_id,
            name=payload.booking_data.get("guest_name"),
            email=payload.booking_data.get("guest_email"),
            phone=payload.booking_data.get("guest_phone"),
        )

    if payload.cottage_id and payload.check_in and payload.check_out:
        try:
            cottage = await resort_client.get_cottage_details(payload.cottage_id)
            quote = await pricing_engine.calculate_quote(
                cottage=cottage,
                check_in_str=payload.check_in,
                check_out_str=payload.check_out,
                adults=payload.adults,
                children=payload.children,
                extra_beds=payload.extra_beds,
                coupon_code=payload.coupon_code,
            )
            authoritative_amount = quote.grand_total
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))
        except ResortAPIError as err:
            raise HTTPException(status_code=502, detail=f"Unable to fetch authoritative rate: {err.detail}")
    else:
        if settings.ENVIRONMENT == "production" or payload.amount is None:
            raise HTTPException(
                status_code=400,
                detail="cottage_id, check_in, and check_out are required for server-authoritative order creation.",
            )
        authoritative_amount = float(payload.amount)

    idem_raw = (
        f"{payload.session_id or _extract_client_ip(request)}:"
        f"{payload.cottage_id}:{payload.check_in}:{payload.check_out}:"
        f"{payload.adults}:{payload.extra_beds}:{payload.coupon_code or ''}:{authoritative_amount}"
    )
    idempotency_key = hashlib.sha256(idem_raw.encode("utf-8")).hexdigest()

    configured_key = (settings.RAZORPAY_KEY_ID or "").strip()

    existing = session_store.get_idempotent_order(idempotency_key)
    if existing:
        logger.info(f"Returning idempotent cached Razorpay order [{existing.get('id')}]")
        effective_key = (
            configured_key
            if configured_key and "placeholder" not in configured_key
            else (existing.get("key") or existing.get("razorpayKey") or configured_key or "rzp_test_placeholder")
        )
        return {
            "success": True,
            "order": existing,
            "key_id": effective_key,
            "authoritative_amount": authoritative_amount,
            "idempotent_hit": True,
        }

    receipt_id = payload.receipt or f"rcpt_{idempotency_key[:10]}"
    logger.info(f"Initiating Razorpay order: INR {authoritative_amount}, Receipt: {receipt_id}")

    try:
        order_resp = await resort_client.create_razorpay_order(
            amount_in_rupees=authoritative_amount,
            receipt=receipt_id,
            notes=payload.notes,
        )
        order_id = str(order_resp.get("id") or f"order_{uuid.uuid4().hex[:14]}")
        session_store.save_payment_order(
            idempotency_key=idempotency_key,
            order_id=order_id,
            order_data=order_resp,
            booking_payload=payload.booking_data,
        )
        effective_key = (
            configured_key
            if configured_key and "placeholder" not in configured_key
            else (order_resp.get("key") or order_resp.get("razorpayKey") or configured_key or "rzp_test_placeholder")
        )
        return {
            "success": True,
            "order": order_resp,
            "key_id": effective_key,
            "authoritative_amount": authoritative_amount,
        }
    except ResortAPIError as err:
        logger.error(f"Upstream Razorpay order failure: {err}")
        if settings.ENVIRONMENT == "production":
            raise HTTPException(status_code=502, detail="Payment gateway temporarily unavailable.")
        mock_order = {
            "id": f"order_{uuid.uuid4().hex[:14]}",
            "amount": int(round(authoritative_amount * 100)),
            "currency": "INR",
            "receipt": receipt_id,
            "status": "created",
        }
        session_store.save_payment_order(
            idempotency_key=idempotency_key,
            order_id=mock_order["id"],
            order_data=mock_order,
            booking_payload=payload.booking_data,
        )
        return {
            "success": True,
            "order": mock_order,
            "key_id": settings.RAZORPAY_KEY_ID or "rzp_test_placeholder",
            "authoritative_amount": authoritative_amount,
            "is_mock": True,
        }


@app.post("/api/payment/verify-and-book", tags=["Payment & Booking"])
async def verify_and_book(payload: VerifyAndBookRequest):
    """
    Validates Razorpay cryptographic signature (constant-time HMAC-SHA256)
    and commits confirmed reservations idempotently.
    """
    logger.info(f"Verifying payment: Order={payload.razorpay_order_id}, Payment={payload.razorpay_payment_id}")

    stored_order = session_store.get_order_by_razorpay_id(payload.razorpay_order_id)
    if stored_order and stored_order.get("status") == "confirmed":
        return {
            "success": True,
            "status": "CONFIRMED",
            "note": "Booking already confirmed idempotently.",
            "payment_id": payload.razorpay_payment_id,
        }

    # Local cryptographic check when merchant secret is configured
    secret = (settings.RAZORPAY_KEY_SECRET or "").strip()
    if secret and "placeholder" not in secret:
        sig_msg = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
        if not _verify_hmac_signature(sig_msg, payload.razorpay_signature, secret):
            raise HTTPException(status_code=400, detail="Cryptographic signature verification failed.")

    payment_data = {
        "razorpay_order_id": payload.razorpay_order_id,
        "razorpay_payment_id": payload.razorpay_payment_id,
        "razorpay_signature": payload.razorpay_signature,
    }

    try:
        await resort_client.verify_razorpay_payment(
            order_id=payload.razorpay_order_id,
            payment_id=payload.razorpay_payment_id,
            signature=payload.razorpay_signature,
        )

        booking_result = await resort_client.create_public_booking(
            booking_data=payload.booking_data,
            payment_data=payment_data,
        )
        session_store.mark_order_confirmed(payload.razorpay_order_id)
        return {
            "success": True,
            "status": "CONFIRMED",
            "booking": booking_result,
        }
    except ResortAPIError as err:
        logger.warning(f"Upstream verification note: {err}")
        if settings.ENVIRONMENT == "production":
            raise HTTPException(status_code=400, detail=f"Payment verification failed: {err}")

        session_store.mark_order_confirmed(payload.razorpay_order_id)
        return {
            "success": True,
            "status": "CONFIRMED",
            "booking_id": f"MM-{uuid.uuid4().hex[:6].upper()}",
            "note": "Payment simulated in development mode. Set ENVIRONMENT=production for strict gateway verification.",
            "payment_id": payload.razorpay_payment_id,
        }


@app.post("/api/payment/webhook", tags=["Payment & Booking"])
async def razorpay_webhook(request: Request):
    """
    Server-to-server Razorpay Webhook handler.
    Reconciles `payment.captured` and `order.paid` events when a mobile guest drops off
    before browser callbacks complete.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    webhook_secret = (settings.RAZORPAY_WEBHOOK_SECRET or "").strip()

    if webhook_secret:
        if not signature or not _verify_hmac_signature(raw_body.decode("utf-8"), signature, webhook_secret):
            raise HTTPException(status_code=400, detail="Invalid Razorpay webhook signature.")
    elif settings.ENVIRONMENT == "production":
        raise HTTPException(status_code=500, detail="RAZORPAY_WEBHOOK_SECRET is not configured in production.")

    try:
        event_payload = json.loads(raw_body.decode("utf-8"))
    except ValueError as err:
        raise HTTPException(status_code=400, detail="Malformed webhook JSON.") from err

    event_type = event_payload.get("event", "")
    if event_type not in ("payment.captured", "order.paid"):
        return {"status": "ignored", "event": event_type}

    entity = event_payload.get("payload", {}).get("payment", {}).get("entity", {})
    order_id = entity.get("order_id") or event_payload.get("payload", {}).get("order", {}).get("entity", {}).get("id")
    payment_id = entity.get("id")

    if not order_id:
        return {"status": "ignored", "reason": "missing_order_id"}

    record = session_store.get_order_by_razorpay_id(order_id)
    if not record:
        logger.warning(f"Webhook received for untracked order_id={order_id}")
        return {"status": "untracked_order"}

    if record.get("status") == "confirmed":
        return {"status": "already_confirmed", "order_id": order_id}

    booking_payload = record.get("booking_payload")
    if booking_payload:
        try:
            await resort_client.create_public_booking(
                booking_data=booking_payload,
                payment_data={
                    "razorpay_order_id": order_id,
                    "razorpay_payment_id": payment_id or "webhook_captured",
                    "razorpay_signature": signature or "webhook_verified",
                },
            )
            session_store.mark_order_confirmed(order_id)
            logger.info(f"Webhook recovered and confirmed reservation for order_id={order_id}")
            return {"status": "reconciled", "order_id": order_id}
        except ResortAPIError as err:
            logger.error(f"Webhook failed committing reservation for order_id={order_id}: {err}")
            raise HTTPException(status_code=502, detail="Failed committing booking from webhook.")

    return {"status": "recorded_no_booking_payload", "order_id": order_id}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
