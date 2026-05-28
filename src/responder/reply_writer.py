"""Generate a reply to a YouTube comment in the channel voice (pt-BR).

Mirrors the ai_writer -> fallback_writer pattern: try Anthropic first, fall
back to Gemini on credit/auth errors. The model also decides *whether* to
reply at all, so toxic/spam/unanswerable comments are filtered by the same
call that writes the answer (returns should_reply=false).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic
import httpx

from ..config import settings
from ..processor.ai_writer import _extract_json, _is_credit_or_auth_error

log = logging.getLogger(__name__)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

REPLY_SYSTEM_PROMPT = """Voce e o community manager de um canal brasileiro de \
fofoca/celebridades/DJ no YouTube (Shorts). Responde comentarios do publico no \
mesmo tom do canal: leve, simpatico, divertido e proximo, em portugues brasileiro \
coloquial com no maximo 1-2 emojis.

OBJETIVO: aumentar engajamento respondendo de forma humana e calorosa quem \
comentou. Agradeca, comente de volta, puxa papo. NUNCA revele que e um bot ou IA.

REGRAS:
- Resposta curta: 1-2 frases, ate ~25 palavras. Nada de textao.
- NAO invente fatos novos sobre celebridades. Se o comentario faz uma pergunta \
que voce nao tem como confirmar, responda de forma simpatica e generica sem afirmar \
nada falso ("boa pergunta!", "tambem fiquei curioso(a)", "fica ligado que a gente \
acompanha").
- NAO inclua links, nao peca "se inscreve"/"curte" de forma forcada (no maximo um \
convite leve e natural de vez em quando).
- Combine com o idioma do comentario (se for portugues, responde em portugues).

QUANDO NAO RESPONDER (should_reply=false):
- Comentario com odio, ataque pessoal, discurso de odio, assedio.
- Spam, propaganda, link de divulgacao, golpe.
- Conteudo que precisa de moderacao (ameaca, conteudo sexual explicito).
- Comentario vazio, so emoji solto sem nada para engajar, ou sem sentido.

FORMATO DE SAIDA (sempre obrigatorio):
Devolva SOMENTE um objeto JSON valido (sem markdown), com os campos:
  * "should_reply" (bool)
  * "reply" (str, a resposta pronta; "" se should_reply=false)
  * "reason" (str, curto, por que respondeu ou pulou)"""


def _user_prompt(video_title: str, comment_text: str, author: str) -> str:
    return (
        "Gere a resposta no formato JSON definido nas instrucoes do sistema.\n\n"
        f"VIDEO (titulo): {video_title}\n"
        f"AUTOR DO COMENTARIO: {author}\n"
        f"COMENTARIO:\n{comment_text}"
    )


def _coerce(payload: dict[str, Any]) -> dict[str, Any]:
    should = bool(payload.get("should_reply"))
    reply = str(payload.get("reply") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if should and not reply:
        should = False
        reason = reason or "empty reply text"
    return {"should_reply": should, "reply": reply, "reason": reason}


def generate_reply(video_title: str, comment_text: str, author: str = "") -> dict[str, Any]:
    """Return {should_reply, reply, reason}. Never raises for normal failures."""
    try:
        return _coerce(_via_anthropic(video_title, comment_text, author))
    except Exception as exc:  # noqa: BLE001
        if not _is_credit_or_auth_error(exc):
            log.warning("Anthropic reply failed (%s); skipping comment", exc)
            return {"should_reply": False, "reply": "", "reason": f"anthropic error: {exc}"}
        if not os.getenv("GEMINI_API_KEY", "").strip():
            log.error("Anthropic unavailable (%s) and no GEMINI_API_KEY", exc)
            return {"should_reply": False, "reply": "", "reason": "no llm available"}
        try:
            log.warning("Anthropic unavailable (%s) — falling back to Gemini", exc)
            return _coerce(_via_gemini(video_title, comment_text, author))
        except Exception as exc2:  # noqa: BLE001
            log.warning("Gemini reply failed (%s); skipping comment", exc2)
            return {"should_reply": False, "reply": "", "reason": f"gemini error: {exc2}"}


def _via_anthropic(video_title: str, comment_text: str, author: str) -> dict[str, Any]:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured.")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=300,
        system=[
            {
                "type": "text",
                "text": REPLY_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {"role": "user", "content": _user_prompt(video_title, comment_text, author)}
        ],
    )
    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )
    return _extract_json(text)


def _via_gemini(video_title: str, comment_text: str, author: str) -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    body = {
        "system_instruction": {"parts": [{"text": REPLY_SYSTEM_PROMPT}]},
        "contents": [
            {"role": "user", "parts": [{"text": _user_prompt(video_title, comment_text, author)}]}
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 300,
            "responseMimeType": "application/json",
        },
    }
    response = httpx.post(endpoint, params={"key": api_key}, json=body, timeout=60.0)
    response.raise_for_status()
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return _extract_json(text)
