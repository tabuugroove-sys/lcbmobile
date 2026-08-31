"""AI rewriter: turns a NewsItem into a tabloid-style RewrittenPost (pt-BR).

Uses the Anthropic SDK with prompt caching on the system prompt so repeated
runs in the same window only pay for the new user content.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any

import anthropic
from anthropic import Anthropic

from ..config import settings
from ..models import NewsItem, RewrittenPost

log = logging.getLogger(__name__)

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not configured.")
        _client = Anthropic(api_key=settings.anthropic_api_key)
    return _client


SYSTEM_PROMPT = """Voce e um editor-chefe de uma revista de fofoca brasileira no estilo \
tabloide amarelo (pensa Hugo Gloss + Leo Dias + TV Foco). Reescreve noticias de \
celebridades, novelas, reality e cena DJ/eletronica do Brasil com tom provocador, \
divertido e clickbait, MAS SEM inventar fatos: trabalhe APENAS com o que vier no \
texto-fonte. Se a fonte nao confirma algo, use linguagem de rumor ("teria", \
"segundo fontes", "rolaria nos bastidores").

Idioma: portugues brasileiro coloquial, com girias atuais e emojis pontuais.
Publico: jovens 18-35, consumidores de Shorts/Reels/TikTok.
Foco editorial: shows, novelas, BBB, fofocas de famosos, DJs/produtores e festas no Brasil.

Cobertura DJ/eletronica e prioridade igual a vocalistas:
- Quando a fonte for sobre DJ, produtor, festival/rave, line-up, lancamento de \
track ou b2b — trate como noticia principal, NAO como rodape de celebridade.
- Cite nomes de DJs (Alok, Vintage Culture, Kvsh, Cat Dealers, Anna, Vintage \
Culture, ANNA, Fancy Inc, etc.) com o mesmo destaque que da a Anitta, Bruna \
Marquezine ou Virginia.
- Festivais (Tomorrowland Brasil, XXXPERIENCE, ULTRA, Universo Paralello, \
Warung, Green Valley, Rock in Rio) sao manchete, nao secundario.
- Use girias de cena: "set arrepiante", "drop monstro", "vibe insana", "after", \
"line-up", "b2b", "remix", "edit", "bootleg".

REGRAS DE FORMATO (sempre obrigatorias):
- Devolva SOMENTE um objeto JSON valido (sem markdown, sem comentarios).
- Campos obrigatorios:
  * "headline" (str, ate 70 caracteres, manchete chamativa)
  * "short_caption" (str, ate 220 caracteres, com 2-3 emojis e 3-5 hashtags inline)
  * "long_caption" (str, 3-5 paragrafos curtos para Telegram/YouTube description)
  * "script_voiceover" (str, 60-90 palavras, locucao em pt-BR para um Short de ~30s, \
sem marcacoes tipo [pausa], so o texto a ser falado)
  * "on_screen_text" (array de 3-5 strings curtas, cada uma com no maximo 6 palavras, \
para aparecer estouradas na tela)
  * "hashtags" (array de 5-10 strings, sem o caractere #, em CamelCase quando precisar)
  * "category" (str, uma de: fofoca, celebridades, dj, televisao, geral)
- Nada de promessas de "link na bio" ou "comente abaixo" no script_voiceover."""


_RESPONSE_FORMAT_HINT = (
    "Reescreva a noticia abaixo no formato JSON definido nas instrucoes do sistema."
)


def _user_prompt(item: NewsItem) -> str:
    published = item.published_at.isoformat() if item.published_at else "desconhecido"
    return (
        f"{_RESPONSE_FORMAT_HINT}\n\n"
        f"FONTE: {item.source_name} ({item.source_id})\n"
        f"CATEGORIA SUGERIDA: {item.category}\n"
        f"PUBLICADO: {published}\n"
        f"URL: {item.url}\n"
        f"TITULO ORIGINAL: {item.title}\n"
        f"RESUMO ORIGINAL:\n{item.summary or '(sem resumo)'}"
    )


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict[str, Any]:
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError(f"No JSON object in model response: {text[:200]!r}")
    return json.loads(match.group(0))


def _is_credit_or_auth_error(exc: BaseException) -> bool:
    """Errors that mean Anthropic won't recover on retry — fall back to Gemini."""
    if isinstance(exc, RuntimeError) and "ANTHROPIC_API_KEY" in str(exc):
        return True
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return True
    if isinstance(exc, anthropic.BadRequestError):
        msg = str(exc).lower()
        if "credit balance" in msg or "credit_balance" in msg:
            return True
    return False


def rewrite(item: NewsItem, *, max_tokens: int = 1024) -> RewrittenPost:
    if os.getenv("REWRITE_PROVIDER", "").strip().lower() == "template":
        from .template_writer import rewrite_via_template

        log.info("Using deterministic template writer for %s", item.url)
        return rewrite_via_template(item)
    if _local_claude_enabled():
        return _rewrite_via_local_claude(item)
    try:
        return _rewrite_via_anthropic(item, max_tokens=max_tokens)
    except Exception as exc:  # noqa: BLE001
        if not _is_credit_or_auth_error(exc):
            raise
        from .fallback_writer import is_configured, rewrite_via_gemini

        if not is_configured():
            log.error(
                "Anthropic unavailable (%s) and GEMINI_API_KEY not configured "
                "— re-raising original error",
                exc,
            )
            raise
        log.warning("Anthropic unavailable (%s) — falling back to Gemini", exc)
        return rewrite_via_gemini(item, max_tokens=max_tokens)


def _local_claude_enabled() -> bool:
    return os.getenv("LOCAL_CLAUDE_FALLBACK", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _rewrite_via_local_claude(item: NewsItem) -> RewrittenPost:
    """Use the signed-in Claude CLI for the Mac-only emergency runner."""
    binary = os.getenv("CLAUDE_CLI_PATH", "claude").strip() or "claude"
    resolved = shutil.which(binary) if "/" not in binary else binary
    if not resolved:
        raise RuntimeError(f"Claude CLI not found: {binary}")

    model = os.getenv("LOCAL_CLAUDE_MODEL", "sonnet").strip() or "sonnet"
    prompt = f"{SYSTEM_PROMPT}\n\n{_user_prompt(item)}"
    completed = subprocess.run(
        [resolved, "-p", "--model", model, "--output-format", "text"],
        input=prompt,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout or "unknown error").strip()
        raise RuntimeError(f"Claude CLI failed ({completed.returncode}): {error[:500]}")

    payload = _extract_json(completed.stdout)
    payload.setdefault("category", item.category or "geral")
    return RewrittenPost(source_url=item.url, **payload)


def _rewrite_via_anthropic(item: NewsItem, *, max_tokens: int = 1024) -> RewrittenPost:
    client = _get_client()
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=max_tokens,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": _user_prompt(item)}],
    )

    text = "".join(
        block.text for block in response.content if getattr(block, "type", "") == "text"
    )
    payload = _extract_json(text)

    payload.setdefault("category", item.category or "geral")
    return RewrittenPost(source_url=item.url, **payload)
