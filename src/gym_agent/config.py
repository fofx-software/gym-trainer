from __future__ import annotations

from dataclasses import dataclass
import os
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    openai_api_key: str
    allowed_user_id: int | None
    model: str
    google_cloud_project: str | None
    firestore_database: str
    webhook_url: str | None
    webhook_secret: str | None
    port: int

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not telegram_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
        if not openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required")
        raw_user_id = os.getenv("ALLOWED_TELEGRAM_USER_ID", "").strip()
        return cls(
            telegram_token=telegram_token,
            openai_api_key=openai_api_key,
            allowed_user_id=int(raw_user_id) if raw_user_id else None,
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
            google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT") or None,
            firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
            webhook_url=os.getenv("WEBHOOK_URL") or None,
            webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET") or None,
            port=int(os.getenv("PORT", "8080")),
        )
