"""Verify the Anthropic API key with a 1-token ping.

Runs as a pre-flight step in the workflow so an invalid key fails fast
and visibly, instead of being silently swallowed inside the rewriter.
"""
from __future__ import annotations

import asyncio
import os
import sys


def _short(s: str, n: int = 6) -> str:
    s = (s or "").strip()
    if len(s) <= 2 * n:
        return f"len={len(s)}"
    return f"{s[:n]}...{s[-n:]} (len={len(s)})"


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
    key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    model = (os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-6").strip()
    if not key:
        print("[anthropic] ANTHROPIC_API_KEY is empty", file=sys.stderr)
        asyncio.run(_notify("❌ Anthropic key vazia (segredo ANTHROPIC_API_KEY)."))
        return 2

    print(f"[anthropic] checking key {_short(key)} on model {model}")

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
            f"❌ Anthropic 401 (chave inválida). "
            f"Recrie em console.anthropic.com → Settings → API Keys e atualize "
            f"o secret ANTHROPIC_API_KEY no GitHub.\n\n{exc}"
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
