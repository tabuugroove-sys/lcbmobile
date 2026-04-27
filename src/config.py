"""Centralized configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value else default
    except ValueError:
        return default


def _float(value: str | None, default: float) -> float:
    try:
        return float(value) if value else default
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    anthropic_model: str
    channel_name: str
    channel_handle: str
    content_lang: str
    timezone: str
    db_path: Path
    output_dir: Path
    max_items_per_run: int
    dry_run: bool

    tts_provider: str
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model: str
    elevenlabs_stability: float
    elevenlabs_similarity: float
    elevenlabs_style: float

    youtube_client_secret_file: Path
    youtube_token_file: Path
    youtube_category_id: str

    instagram_user_id: str
    instagram_access_token: str
    instagram_public_base_url: str

    tiktok_access_token: str
    tiktok_open_id: str

    twitter_consumer_key: str
    twitter_consumer_secret: str
    twitter_access_token: str
    twitter_access_secret: str
    twitter_bearer_token: str

    telegram_bot_token: str
    telegram_channel_id: str


def load_settings() -> Settings:
    db_path = Path(os.getenv("DB_PATH", "data/state.db"))
    output_dir = Path(os.getenv("OUTPUT_DIR", "out"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    db_path.parent.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        channel_name=os.getenv("CHANNEL_NAME", "LCB Mobile"),
        channel_handle=os.getenv("CHANNEL_HANDLE", "@lcbmobile"),
        content_lang=os.getenv("CONTENT_LANG", "pt-BR"),
        timezone=os.getenv("TIMEZONE", "America/Sao_Paulo"),
        db_path=db_path,
        output_dir=output_dir,
        max_items_per_run=_int(os.getenv("MAX_ITEMS_PER_RUN"), 3),
        dry_run=_bool(os.getenv("DRY_RUN"), False),
        tts_provider=os.getenv("TTS_PROVIDER", "gtts").strip().lower(),
        elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
        elevenlabs_voice_id=os.getenv(
            "ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"
        ),
        elevenlabs_model=os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        elevenlabs_stability=_float(os.getenv("ELEVENLABS_STABILITY"), 0.45),
        elevenlabs_similarity=_float(os.getenv("ELEVENLABS_SIMILARITY"), 0.8),
        elevenlabs_style=_float(os.getenv("ELEVENLABS_STYLE"), 0.35),
        youtube_client_secret_file=Path(
            os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
        ),
        youtube_token_file=Path(os.getenv("YOUTUBE_TOKEN_FILE", "youtube_token.json")),
        youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "24"),
        instagram_user_id=os.getenv("INSTAGRAM_USER_ID", ""),
        instagram_access_token=os.getenv("INSTAGRAM_ACCESS_TOKEN", ""),
        instagram_public_base_url=os.getenv("INSTAGRAM_PUBLIC_BASE_URL", ""),
        tiktok_access_token=os.getenv("TIKTOK_ACCESS_TOKEN", ""),
        tiktok_open_id=os.getenv("TIKTOK_OPEN_ID", ""),
        twitter_consumer_key=os.getenv("TWITTER_CONSUMER_KEY", ""),
        twitter_consumer_secret=os.getenv("TWITTER_CONSUMER_SECRET", ""),
        twitter_access_token=os.getenv("TWITTER_ACCESS_TOKEN", ""),
        twitter_access_secret=os.getenv("TWITTER_ACCESS_SECRET", ""),
        twitter_bearer_token=os.getenv("TWITTER_BEARER_TOKEN", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", ""),
    )


settings = load_settings()
