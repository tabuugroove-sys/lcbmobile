"""Free-tier fallback rewriter via Google Gemini API.

Activated only when Anthropic returns credit-balance / auth errors. Gemini 2.5
Flash has a generous free tier (1500 req/day) and produces structured JSON
output of comparable quality for short tabloid rewrites. Uses httpx directly
so we do not pull in another SDK.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from ..models import NewsItem, RewrittenPost
from .ai_writer import SYSTEM_PROMPT, _user_prompt

log = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def is_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def rewrite_via_gemini(item: NewsItem, *, max_tokens: int = 1024) -> RewrittenPost:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    body: dict[str, Any] = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": _user_prompt(item)}]}],
        "generationConfig": {
            "temperature": 0.8,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
        },
    }
    response = httpx.post(
        endpoint,
        params={"key": api_key},
        json=body,
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        finish = (
            data.get("candidates", [{}])[0].get("finishReason", "?")
            if data.get("candidates") else "?"
        )
        raise RuntimeError(
            f"Gemini returned no text (finishReason={finish}): {data}"
        ) from exc

    payload = json.loads(text)
    payload.setdefault("category", item.category or "geral")
    return RewrittenPost(source_url=item.url, **payload)
