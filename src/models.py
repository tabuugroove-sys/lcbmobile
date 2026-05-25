"""Shared data models passed between pipeline stages."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, Field


# Tracking params we strip from URLs before fingerprinting. Same article shared
# via different campaigns must hash to the same fingerprint.
_TRACKING_PARAMS_PREFIXES = ("utm_", "fbclid", "gclid", "yclid", "ref", "mc_")


def _normalize_url(url: str) -> str:
    """Canonicalize a URL so trivial variants collapse to one fingerprint.

    Handles: scheme (http→https), case, www prefix, query tracking params,
    fragment, trailing slash. Pure string ops — never touches the network.
    """
    if not url:
        return ""
    try:
        parts = urlparse(url.strip())
    except Exception:  # pragma: no cover — urlparse is very tolerant
        return url.strip().lower()

    scheme = "https" if parts.scheme in ("http", "https", "") else parts.scheme
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    path = parts.path.rstrip("/") or "/"

    # Drop tracking query params, keep everything else
    if parts.query:
        kept = [
            kv for kv in parts.query.split("&")
            if kv and not any(
                kv.lower().startswith(p) for p in _TRACKING_PARAMS_PREFIXES
            )
        ]
        query = "&".join(kept)
    else:
        query = ""

    return urlunparse((scheme, netloc, path, "", query, ""))


_WHITESPACE = re.compile(r"\s+")


def _normalize_title(title: str) -> str:
    """Strip accents, lowercase, collapse whitespace. For content-hash dedup."""
    if not title:
        return ""
    decomposed = unicodedata.normalize("NFKD", title)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    return _WHITESPACE.sub(" ", ascii_only.lower()).strip()


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
        """Primary dedupe key — normalized URL or explicit dedupe_key override."""
        if self.dedupe_key:
            return self.dedupe_key.strip().lower()
        return _normalize_url(self.url)

    def content_hash(self) -> str:
        """Secondary dedupe key based on the normalized headline.

        Catches the case where the same story appears at two different URLs
        (mirror domain, canonical redirect, RSS-feed dupe with different
        slug). Title-only because RSS sources often tweak the summary text
        but the headline stays stable — and so the hash collides as we want.
        """
        title = _normalize_title(self.title)
        if not title:
            return ""
        payload = f"{title}|"
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


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
