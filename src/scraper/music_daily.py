"""Additional primary music coverage for the five-story daily bulletin."""
from __future__ import annotations

import json
import html
import logging
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from ..config import ROOT
from ..editorial.music_filter import find_music_act_query
from ..models import NewsItem
from .rss import USER_AGENT, collect_news
from .sources import load_sources

log = logging.getLogger(__name__)


def clean_title(title: str) -> str:
    words = html.unescape(title).split()
    half = len(words) // 2
    if len(words) % 2 == 0 and words[:half] == words[half:]:
        words = words[:half]
    return " ".join(words)


def _article_schema(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            types = node.get("@type", [])
            types = [types] if isinstance(types, str) else types
            if any(kind in {"Article", "NewsArticle", "BlogPosting"} for kind in types):
                return node
    return {}


def collect_daily_music_news() -> list[NewsItem]:
    sources = load_sources(ROOT / "config/sources.yaml") + load_sources(ROOT / "config/daily_music_sources.yaml")
    items = collect_news(sources, enrich=False)
    items = [item.model_copy(update={"title": clean_title(item.title)}) for item in items]
    # Billboard's /feed redirects to HTML. Read the publication's own article metadata instead.
    with httpx.Client(timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        try:
            home = client.get("https://billboard.com.br/")
            home.raise_for_status()
            soup = BeautifulSoup(home.text, "lxml")
            links = {}
            for heading in soup.find_all(["h3", "h4"]):
                anchor = heading.find_parent("a") or heading.find("a")
                url = anchor.get("href", "") if anchor else ""
                if url.startswith("https://billboard.com.br/") and find_music_act_query(heading.get_text(" ", strip=True)):
                    links.setdefault(url, heading.get_text(" ", strip=True))
            for url, title in list(links.items())[:30]:
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    article = BeautifulSoup(response.text, "lxml")
                    schema = _article_schema(article)
                    stamp = schema.get("datePublished")
                    if not stamp:
                        date_meta = article.find("meta", property="article:published_time")
                        stamp = date_meta.get("content") if date_meta else None
                    if not stamp:
                        continue
                    published = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                    desc = article.find("meta", property="og:description")
                    content = article.select_one(".entry-content") or article.find("article")
                    paragraphs = [p.get_text(" ", strip=True) for p in content.find_all("p")] if content else []
                    summary = " ".join(paragraphs[:3]) or str(schema.get("description") or (desc.get("content", "") if desc else ""))
                    items.append(NewsItem(source_id="billboard_br", source_name="Billboard Brasil", category="celebridades",
                                          url=url, title=title, summary=summary[:600], published_at=published))
                except (httpx.HTTPError, ValueError) as exc:
                    log.warning("Billboard article unavailable: %s: %s", url, exc)
        except httpx.HTTPError as exc:
            log.warning("Billboard music coverage unavailable: %s", exc)
    items.sort(key=lambda item: (item.published_at.replace(tzinfo=timezone.utc) if item.published_at.tzinfo is None
                               else item.published_at).timestamp() if item.published_at else 0, reverse=True)
    return items
