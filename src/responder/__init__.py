"""YouTube comment auto-responder agent.

Self-contained: lists comments on the channel's own uploads, generates a
pt-BR reply in the channel voice (Anthropic with Gemini fallback) and posts
it back via the YouTube Data API. Dedup lives in its own SQLite file so it
never collides with the publish pipeline's state DB / GHA cache.
"""
from .agent import run_comment_responder

__all__ = ["run_comment_responder"]
