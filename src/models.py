"""Shared data models passed between pipeline stages."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NewsItem(BaseModel):
    """Raw item collected from a source."""

    source_id: str
    source_name: str
    category: str
    url: str
    title: str
    summary: str = ""
    published_at: Optional[datetime] = None
    image_url: Optional[str] = None
    dedupe_key: Optional[str] = None

    def fingerprint(self) -> str:
        return (self.dedupe_key or self.url).strip().lower()


class RewrittenPost(BaseModel):
    """AI-rewritten content ready for distribution."""

    source_url: str
    headline: str = Field(..., description="Manchete curta, estilo tabloide")
    short_caption: str = Field(..., description="Post para X/IG, <= 220 caracteres")
    long_caption: str = Field(..., description="Texto longo para Telegram/YouTube")
    script_voiceover: str = Field(..., description="Roteiro narrado em pt-BR (~30s)")
    on_screen_text: list[str] = Field(default_factory=list, description="Texto na tela do Short")
    hashtags: list[str] = Field(default_factory=list)
    category: str = ""


class GeneratedAssets(BaseModel):
    """Files produced by the video stage."""

    video_path: str
    thumbnail_path: Optional[str] = None
    duration_seconds: float = 0.0
