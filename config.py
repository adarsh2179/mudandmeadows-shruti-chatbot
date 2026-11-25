"""
Configuration Module for Mud & Meadows AI Concierge Backend.

Loads and validates environment variables from `.env` using Pydantic Settings.
Guarantees fail-fast behavior if critical settings are misconfigured.
"""

from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Server runtime settings
    PORT: int = Field(default=8000, description="Port on which the FastAPI application will listen")
    ENVIRONMENT: str = Field(default="development", description="Environment: 'development' or 'production'")

    # Company / Brand Name
    COMPANY_NAME: str = Field(default="Luxury Resort", description="Name of the company / resort")

    # Target Resort External API
    RESORT_API_BASE_URL: str = Field(
        default="https://mudandmeadows-api-742259178550.asia-south1.run.app",
        description="Base URL for Mud & Meadows Resort backend REST API"
    )

    # Free GenAI Provider Keys
    GEMINI_API_KEY: str = Field(
        default="",
        description="Google Gemini API Key from Google AI Studio (Free Tier)"
    )
    GROQ_API_KEY: str = Field(
        default="",
        description="Groq API Key for Whisper-Large-v3 multilingual audio translation (Free Tier)"
    )

    # Payment Gateway Credentials (Razorpay)
    RAZORPAY_KEY_ID: str = Field(
        default="",
        description="Razorpay Key ID (Test key starts with rzp_test_)"
    )
    RAZORPAY_KEY_SECRET: str = Field(
        default="",
        description="Razorpay Secret Key used for server-side HMAC-SHA256 signature verification"
    )

    # Security & CORS (Cross-Origin Resource Sharing)
    ALLOWED_ORIGINS: str = Field(
        default="http://localhost:3000,http://localhost:8000,https://mudandmeadows.in,https://www.mudandmeadows.in,https://mudandmeadows.com,https://www.mudandmeadows.com",
        description="Comma-separated list of allowed origins for the embeddable chat widget"
    )

    # Free Notification Services (Email & WhatsApp)
    SMTP_HOST: str = Field(default="smtp.gmail.com", description="SMTP Server Host (e.g. smtp.gmail.com)")
    SMTP_PORT: int = Field(default=587, description="SMTP Port (587 for TLS)")
    SMTP_USER: str = Field(default="", description="SMTP Username or Gmail address")
    SMTP_PASSWORD: str = Field(default="", description="SMTP App Password")
    SMTP_FROM_EMAIL: str = Field(default="concierge@mudandmeadows.in", description="From email address")
    RESORT_WHATSAPP_NUMBER: str = Field(default="919876543210", description="Resort WhatsApp Contact Number")

    @property
    def cors_origins(self) -> List[str]:
        """Parses the comma-separated ALLOWED_ORIGINS string into a clean list for FastAPI CORSMiddleware."""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Singleton instance to be imported across the application
settings = Settings()
