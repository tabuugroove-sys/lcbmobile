"""Verify the Anthropic API key with a 1-token ping.

Runs as a pre-flight step in the workflow so an invalid key fails fast
and visibly, instead of being silently swallowed inside the rewriter.
"""
from __future__ import annotations

import asyncio
import os
import sys


def _short(s: str) -> str:
    """Return a non-secret fingerprint of the key for verification.

    Includes:
      - the raw byte length BEFORE cleaning (so we can spot stray whitespace),
      - the byte length AFTER cleaning,
      - sha256[:10] of the cleaned value (enough to compare against the
        known-good key without exposing the key itself).
    """
    import hashlib

    raw = s or ""
    # Mirror the cleaning the SDK call uses below.
    cleaned = raw
    for ch in (" ", "​", "‌", "‍", " ", " ", " ", "﻿"):
        cleaned = cleaned.replace(ch, "")
    cleaned = cleaned.strip()
    digest = hashlib.sha256(cleaned.encode()).hexdigest()[:10]
    return f"raw_len={len(raw)} clean_len={len(cleaned)} sha256={digest}"


async def _notify(text: str) -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHANNEL_ID") or "").strip()
    if not token or not chat:
        return
    from telegram import Bot
    bot = Bot(token=token)
    try:
        await bot.send_message(chat_id=chat, text=text[:3900], disable_notification=True)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    raw = os.getenv("ANTHROPIC_API_KEY") or ""
    fp = _short(raw)
    # Use the same cleaner as the rest of the pipeline.
    key = raw
    for ch in (" ", "​", "‌", "‍", " ", " ", " ", "﻿"):
        key = key.replace(ch, "")
    key = key.strip()
    model = (os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-6").strip()
    if not key:
        print("[anthropic] ANTHROPIC_API_KEY is empty", file=sys.stderr)
        asyncio.run(_notify(f"❌ Anthropic key vazia. {fp}"))
        return 2

    print(f"[anthropic] checking key {fp} on model {model}")

    try:
        from anthropic import Anthropic, APIStatusError, AuthenticationError

        client = Anthropic(api_key=key)
        resp = client.messages.create(
            model=model,
            max_tokens=4,
            messages=[{"role": "user", "content": "ping"}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        print(f"[anthropic] ok: model={resp.model} reply={text!r}")
        return 0
    except AuthenticationError as exc:
        msg = (
            f"❌ Anthropic 401 (chave inválida).\n"
            f"key fingerprint: {fp}\n"
            f"Se isso não bate com a chave que você acredita ter colado, o "
            f"segredo no GitHub está com outro valor.\n\n{exc}"
        )
        print(f"[anthropic] {msg}", file=sys.stderr)
        asyncio.run(_notify(msg))
        return 1
    except APIStatusError as exc:
        msg = f"❌ Anthropic API error: {exc.status_code} {exc}"
        print(msg, file=sys.stderr)
        asyncio.run(_notify(msg))
        return 1
    except Exception as exc:  # noqa: BLE001
        msg = f"❌ Anthropic check crashed: {type(exc).__name__}: {exc}"
        print(msg, file=sys.stderr)
        asyncio.run(_notify(msg))
        return 1


if __name__ == "__main__":
    sys.exit(main())
