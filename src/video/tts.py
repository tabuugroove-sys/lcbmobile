"""Text-to-speech providers. ElevenLabs (premium) with gTTS fallback."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from ..config import settings

log = logging.getLogger(__name__)


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, dest: Path, *, lang: str) -> Path: ...


class GTTSProvider:
    name = "gtts"

    def synthesize(self, text: str, dest: Path, *, lang: str) -> Path:
        from gtts import gTTS

        tts = gTTS(text=text, lang=lang.split("-")[0] or "pt", tld="com.br", slow=False)
        tts.save(str(dest))
        return dest


class ElevenLabsProvider:
    """ElevenLabs Text-to-Speech via the official SDK."""

    name = "elevenlabs"

    def __init__(self) -> None:
        if not settings.elevenlabs_api_key:
            raise RuntimeError("ELEVENLABS_API_KEY is not configured.")
        from elevenlabs.client import ElevenLabs

        self._client = ElevenLabs(api_key=settings.elevenlabs_api_key)

    def synthesize(self, text: str, dest: Path, *, lang: str) -> Path:
        # eleven_multilingual_v2 covers pt-BR; lang hint is informational here.
        del lang
        audio = self._client.text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model,
            text=text,
            output_format="mp3_44100_128",
            voice_settings={
                "stability": settings.elevenlabs_stability,
                "similarity_boost": settings.elevenlabs_similarity,
                "style": settings.elevenlabs_style,
                "speed": settings.elevenlabs_speed,
                "use_speaker_boost": True,
            },
        )
        with dest.open("wb") as fh:
            for chunk in audio:
                if chunk:
                    fh.write(chunk)
        return dest


def get_tts_provider() -> TTSProvider:
    """Pick a provider based on settings, with safe fallback."""
    choice = (settings.tts_provider or "gtts").lower()
    if choice == "elevenlabs":
        if settings.elevenlabs_api_key:
            try:
                return ElevenLabsProvider()
            except Exception as exc:  # noqa: BLE001
                log.warning("ElevenLabs init failed (%s); falling back to gTTS", exc)
        else:
            log.warning("TTS_PROVIDER=elevenlabs but ELEVENLABS_API_KEY empty; using gTTS")
    return GTTSProvider()
