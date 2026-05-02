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
    max_attempts_per_item: int
    retry_delay_seconds: int
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


_INVISIBLE = "".join(
    chr(c)
    for c in (0x00A0, 0x200B, 0x200C, 0x200D, 0x2028, 0x2029, 0x202F, 0xFEFF)
)


def _str(name: str, default: str = "") -> str:
    """Read an env var and aggressively clean it.

    Mobile copy/paste of GitHub secrets often leaves a trailing newline
    OR an invisible unicode character (zero-width space, NBSP, BOM...)
    that turns valid API keys into 401s. Standard .strip() doesn't help
    against U+200B and friends, so we filter them explicitly and then
    drop the leftover surrounding ASCII whitespace.
    """
    raw = os.getenv(name)
    value = raw if raw is not None else default
    for ch in _INVISIBLE:
        value = value.replace(ch, "")
    return value.strip()


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
        anthropic_api_key=_str("ANTHROPIC_API_KEY"),
        anthropic_model=_str("ANTHROPIC_MODEL", "claude-haiku-4-5"),
        channel_name=_str("CHANNEL_NAME", "LCB Mobile"),
        channel_handle=_str("CHANNEL_HANDLE", "@lcbmobile"),
        content_lang=_str("CONTENT_LANG", "pt-BR"),
        timezone=_str("TIMEZONE", "America/Sao_Paulo"),
        db_path=db_path,
        output_dir=output_dir,
        max_items_per_run=_int(os.getenv("MAX_ITEMS_PER_RUN"), 3),
        max_attempts_per_item=_int(os.getenv("MAX_ATTEMPTS_PER_ITEM"), 5),
        retry_delay_seconds=_int(os.getenv("RETRY_DELAY_SECONDS"), 200),
        dry_run=_bool(os.getenv("DRY_RUN"), False),
        tts_provider=_str("TTS_PROVIDER", "gtts").lower(),
        elevenlabs_api_key=_str("ELEVENLABS_API_KEY"),
        elevenlabs_voice_id=_str("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
        elevenlabs_model=_str("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
        elevenlabs_stability=_float(os.getenv("ELEVENLABS_STABILITY"), 0.45),
        elevenlabs_similarity=_float(os.getenv("ELEVENLABS_SIMILARITY"), 0.8),
        elevenlabs_style=_float(os.getenv("ELEVENLABS_STYLE"), 0.35),
        youtube_client_secret_file=Path(
            _str("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
        ),
        youtube_token_file=Path(_str("YOUTUBE_TOKEN_FILE", "youtube_token.json")),
        youtube_category_id=_str("YOUTUBE_CATEGORY_ID", "24"),
        instagram_user_id=_str("INSTAGRAM_USER_ID"),
        instagram_access_token=_str("INSTAGRAM_ACCESS_TOKEN"),
        instagram_public_base_url=_str("INSTAGRAM_PUBLIC_BASE_URL"),
        tiktok_access_token=_str("TIKTOK_ACCESS_TOKEN"),
        tiktok_open_id=_str("TIKTOK_OPEN_ID"),
        twitter_consumer_key=_str("TWITTER_CONSUMER_KEY"),
        twitter_consumer_secret=_str("TWITTER_CONSUMER_SECRET"),
        twitter_access_token=_str("TWITTER_ACCESS_TOKEN"),
        twitter_access_secret=_str("TWITTER_ACCESS_SECRET"),
        twitter_bearer_token=_str("TWITTER_BEARER_TOKEN"),
        telegram_bot_token=_str("TELEGRAM_BOT_TOKEN"),
        telegram_channel_id=_str("TELEGRAM_CHANNEL_ID"),
    )


settings = load_settings()
