"""
FastAPI Main Application Server for Mud & Meadows AI Concierge.

Exposes REST APIs for:
1. /api/chat: Text conversational agent with session memory.
2. /api/voice/process: Multilingual voice audio ingestion (Hindi, Bhojpuri, Kannada, etc.)
   converted to text and answered directly in chat form.
3. /api/payment/create-order: Razorpay payment order initiation.
4. /api/payment/verify-and-book: Razorpay payment signature verification & booking submission.
5. /static: Static file hosting for the embeddable chat widget.
"""

import logging
import uuid
from typing import Any, Dict, Optional
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import settings
from resort_client import resort_client, ResortAPIError
from voice_service import voice_service
from agent import agent, AgentResponse

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("mudandmeadows.server")

app = FastAPI(
    title="Mud & Meadows Resort AI Concierge API",
    version="1.0.0",
    description="Conversational Multilingual AI Agent & Voice Booking Backend.",
)

# =============================================================================
# CORS MIDDLEWARE (Enables embedding on company website & mobile apps)
# =============================================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins if settings.cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static folder for the widget assets
import os
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# =============================================================================
# REQUEST & RESPONSE SCHEMAS
# =============================================================================

class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(default=None, description="Client session ID for conversation memory")
    message: str = Field(min_length=1, description="Guest message in text form")


class VoiceChatResponse(BaseModel):
    success: bool
    transcription: str
    engine_used: str
    agent_response: AgentResponse


class CreateOrderRequest(BaseModel):
    amount: float = Field(gt=0, description="Grand total amount in INR")
    receipt: Optional[str] = Field(default=None, description="Unique receipt/reference string")
    notes: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Metadata like guest name, room ID")


class VerifyAndBookRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    booking_data: Dict[str, Any]


# =============================================================================
# API ROUTES
# =============================================================================

@app.get("/", tags=["Website"])
async def serve_demo_page():
    """Serves the resort demo webpage with the embedded chat widget."""
    return FileResponse("static/index.html")


@app.get("/health", tags=["System"])
async def health_check():
    """Healthcheck endpoint for AWS Load Balancers and uptime monitoring."""
    return {
        "status": "healthy",
        "service": "Mud & Meadows AI Concierge",
        "environment": settings.ENVIRONMENT,
        "resort_api_target": settings.RESORT_API_BASE_URL,
    }


@app.post("/api/chat", response_model=AgentResponse, tags=["Conversational Agent"])
async def chat_endpoint(payload: ChatRequest):
    """
    Main text interaction endpoint.
    Maintains conversational memory and dispatches tools.
    """
    session_id = payload.session_id or str(uuid.uuid4())
    logger.info(f"Chat request received for session [{session_id}]: '{payload.message}'")

    response = await agent.chat(session_id=session_id, user_message=payload.message)
    return response


@app.post("/api/voice/process", response_model=VoiceChatResponse, tags=["Voice Processing"])
async def voice_process_endpoint(
    audio: UploadFile = File(..., description="Audio recording blob (WebM, WAV, MP3)"),
    session_id: Optional[str] = Form(None),
):
    """
    Voice-in, Chat-out processing endpoint.
    Ingests recorded audio from microphone, detects regional languages
    (Hindi, Bhojpuri, Kannada, etc.), translates to English, and returns
    the agent's response in chat card form.
    """
    active_session_id = session_id or str(uuid.uuid4())
    logger.info(f"Voice upload received for session [{active_session_id}], file: {audio.filename}, content-type: {audio.content_type}")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file uploaded.")

    # 1. Transcribe & translate using VoiceService
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
    logger.info(f"Audio translated successfully: '{transcribed_text}'")

    # 2. Pass transcribed message to the Conversational Agent
    agent_response = await agent.chat(session_id=active_session_id, user_message=transcribed_text)

    return VoiceChatResponse(
        success=True,
        transcription=transcribed_text,
        engine_used=transcription_result.get("engine", "unknown"),
        agent_response=agent_response,
    )


@app.post("/api/payment/create-order", tags=["Payment & Booking"])
async def create_payment_order(payload: CreateOrderRequest):
    """
    Generates a Razorpay Order ID for payment.
    Called before opening the Razorpay Checkout Modal in the chat widget.
    """
    receipt_id = payload.receipt or f"rcpt_{uuid.uuid4().hex[:8]}"
    logger.info(f"Initiating Razorpay order: Rs.{payload.amount}, Receipt: {receipt_id}")

    try:
        # Call resort backend's Razorpay order endpoint
        order_resp = await resort_client.create_razorpay_order(
            amount_in_rupees=payload.amount,
            receipt=receipt_id,
            notes=payload.notes,
        )
        return {
            "success": True,
            "order": order_resp,
            "key_id": settings.RAZORPAY_KEY_ID or "rzp_test_placeholder",
        }
    except ResortAPIError as err:
        logger.error(f"Failed to create order via Resort API: {err}")
        # Graceful fallback order response for development/testing if API keys are pending
        return {
            "success": True,
            "order": {
                "id": f"order_{uuid.uuid4().hex[:14]}",
                "amount": int(payload.amount * 100),
                "currency": "INR",
                "receipt": receipt_id,
                "status": "created",
            },
            "key_id": settings.RAZORPAY_KEY_ID or "rzp_test_placeholder",
            "is_mock": True,
        }


@app.post("/api/payment/verify-and-book", tags=["Payment & Booking"])
async def verify_and_book(payload: VerifyAndBookRequest):
    """
    Verifies Razorpay payment signature and submits public booking.
    Endpoint called when the guest completes the payment modal.
    """
    logger.info(f"Verifying payment: Order={payload.razorpay_order_id}, Payment={payload.razorpay_payment_id}")

    payment_data = {
        "razorpay_order_id": payload.razorpay_order_id,
        "razorpay_payment_id": payload.razorpay_payment_id,
        "razorpay_signature": payload.razorpay_signature,
    }

    try:
        # 1. Verify Payment Signature via Resort API
        await resort_client.verify_razorpay_payment(
            order_id=payload.razorpay_order_id,
            payment_id=payload.razorpay_payment_id,
            signature=payload.razorpay_signature,
        )

        # 2. Finalize Booking in Resort System
        booking_result = await resort_client.create_public_booking(
            booking_data=payload.booking_data,
            payment_data=payment_data,
        )
        return {
            "success": True,
            "status": "CONFIRMED",
            "booking": booking_result,
        }
    except ResortAPIError as err:
        logger.warning(f"Resort API verification note: {err}")
        if settings.ENVIRONMENT == "production":
            raise HTTPException(
                status_code=400,
                detail=f"Payment verification failed: {err}"
            )
        # Development / Sandbox fallback response
        return {
            "success": True,
            "status": "CONFIRMED",
            "booking_id": f"MM-{uuid.uuid4().hex[:6].upper()}",
            "note": "Payment simulated in development mode. Set ENVIRONMENT=production for strict gateway verification.",
            "payment_id": payload.razorpay_payment_id,
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.PORT, reload=True)
