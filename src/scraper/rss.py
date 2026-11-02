"""RSS collector with HTML fallback for the largest image / longer summary."""
from __future__ import annotations

import html
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Iterable

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..models import NewsItem
from .sources import Source

# Editorial boost: DJ-scene sources publish ~1 item/day vs. dozens from celebrity
# tabloids, so a strict published_at sort would never pick them. We grant the
# "dj" category a virtual freshness bonus so it competes with same-day celeb
# news. Override via DJ_CATEGORY_BOOST_HOURS (default 12h).
_DJ_BOOST = timedelta(hours=int(os.getenv("DJ_CATEGORY_BOOST_HOURS", "12")))

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; LCBMobileBot/1.0; +https://github.com/tabuugroove-sys/lcbmobile)"
)
TIMEOUT = httpx.Timeout(15.0, connect=10.0)


def _to_dt(struct_time) -> datetime | None:
    if not struct_time:
        return None
    try:
        return datetime(*struct_time[:6])
    except (TypeError, ValueError):
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(text or "", "lxml").get_text(" ")).strip()


# Feed furniture that would otherwise be read aloud by the narrator or drawn on screen.
_WORDPRESS_FOOTER_RE = re.compile(
    r"(?:^|\s)(?:O post|The post) (?:(?!(?:O post|The post) ).)*?"
    r"(?:apareceu primeiro em|appeared first on) .{0,60}$",
    re.DOTALL,
)
_PHOTO_CREDIT_RE = re.compile(
    r"\(\s*(?:fotos?|imagens?|cr[eé]ditos?|reprodu[cç][aã]o)[\s:_/][^)]*(?:\)|$)", re.IGNORECASE
)
_TRAILING_CREDIT_RE = re.compile(r"\s(?:Fotos?|Imagens?|Cr[eé]ditos?): \S.*$")
_LEADING_CREDIT_RE = re.compile(r"^cr[eé]dito:\s+\S+\s+(?=[A-ZÀ-Ö])", re.IGNORECASE)
_COLUMN_LABEL_RE = re.compile(r"^.*?♫[^♬]{0,30}♬\s*", re.DOTALL)
_CUT_OFF_TAIL_RE = re.compile(r"\s*\[(?:…|\.\.\.)\]\s*$")
_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_SPACES_RE = re.compile(r"\s+")
# G1 opens a summary with the photo, then a caption line and a credit line.
_LEADING_PHOTO_RE = re.compile(r"^\s*<img\b[^>]*>\s*(?:<br\s*/?>\s*)*[^\n<]*\n([^\n<]*)\n", re.IGNORECASE)
_MAX_PHOTO_CREDIT_CHARS = 60
_MIN_FIRST_SENTENCE = 40
_SENTENCE_SEARCH_MARGIN = 250


def _clean_title(title: str) -> str:
    text = html.unescape(title or "")
    text = _SPACES_RE.sub(" ", text).strip()
    cleaned = _TRAILING_CREDIT_RE.sub("", _SPACES_RE.sub(" ", _PHOTO_CREDIT_RE.sub(" ", text))).strip()
    if cleaned != text:
        # A photo caption can carry its alt text too: "...aos 49 anos mulher banana (foto_...)".
        words = cleaned.split()
        while len(words) > 1 and words[-1].islower() and words[-1] in " ".join(words[:-1]).casefold():
            words.pop()
        cleaned = " ".join(words)
    words = cleaned.split()
    half = len(words) // 2
    if len(words) % 2 == 0 and words[:half] == words[half:]:
        cleaned = " ".join(words[:half])
    return cleaned.rstrip(" ;,:–—")


def _strip_leading_photo(raw_html: str) -> str:
    """Drop a photo's caption and credit so the narration starts on the actual story."""
    match = _LEADING_PHOTO_RE.match(raw_html or "")
    if not match:
        return raw_html or ""
    credit = match.group(1).strip()
    if len(credit) > _MAX_PHOTO_CREDIT_CHARS or credit[-1:] in {".", "!", "?"}:
        return raw_html
    return raw_html[match.end():]


def _clean_summary(text: str, limit: int) -> str:
    """Remove feed furniture and end on a finished sentence whenever the text was cut."""
    without_footer = _WORDPRESS_FOOTER_RE.sub("", text or "")
    # What precedes a WordPress footer is an excerpt, usually stopped mid-sentence.
    cut_off = without_footer != (text or "")
    text = _COLUMN_LABEL_RE.sub("", without_footer)
    text = _SPACES_RE.sub(" ", _PHOTO_CREDIT_RE.sub(" ", text)).strip()
    text = _LEADING_CREDIT_RE.sub("", text)
    cut_off = cut_off or bool(_CUT_OFF_TAIL_RE.search(text))
    text = _CUT_OFF_TAIL_RE.sub("", text)
    if not cut_off and len(text) <= limit:
        return text
    ends = [m.end() for m in _SENTENCE_END_RE.finditer(text[:limit]) if m.end() >= _MIN_FIRST_SENTENCE]
    if ends:
        return text[: ends[-1]]
    longer = _SENTENCE_END_RE.search(text, limit, limit + _SENTENCE_SEARCH_MARGIN)
    if longer:
        return text[: longer.end()]
    return text[:limit].rsplit(" ", 1)[0] if len(text) > limit and " " in text[:limit] else text[:limit]


def _extract_image(entry) -> str | None:
    media = entry.get("media_content") or entry.get("media_thumbnail")
    if media and isinstance(media, list):
        url = media[0].get("url")
        if url:
            return url
    for link in entry.get("links", []) or []:
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image/"):
            return link.get("href")
    summary = entry.get("summary") or ""
    soup = BeautifulSoup(summary, "lxml")
    img = soup.find("img")
    if img and img.get("src"):
        return img["src"]
    return None


def _enrich_with_og(item: NewsItem, client: httpx.Client) -> NewsItem:
    """Best-effort: fetch the page and pull og:image / better description."""
    try:
        resp = client.get(item.url, headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return item
        soup = BeautifulSoup(resp.text, "lxml")
        og_image = soup.find("meta", property="og:image")
        og_desc = soup.find("meta", property="og:description")
        if og_image and og_image.get("content") and not item.image_url:
            item = item.model_copy(update={"image_url": og_image["content"]})
        if og_desc and og_desc.get("content") and len(item.summary) < 80:
            item = item.model_copy(update={"summary": _clean_summary(og_desc["content"].strip(), 600)})
    except httpx.HTTPError as exc:
        log.debug("og fetch failed for %s: %s", item.url, exc)
    return item


def collect_news(sources: Iterable[Source], enrich: bool = True) -> list[NewsItem]:
    items: list[NewsItem] = []
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        for src in sources:
            try:
                feed = feedparser.parse(src.url, agent=USER_AGENT)
            except Exception as exc:  # noqa: BLE001 - feedparser surfaces many
                log.warning("Failed to parse %s: %s", src.id, exc)
                continue

            for entry in feed.entries[: src.max_entries]:
                url = entry.get("link")
                title = _clean_title(entry.get("title") or "")
                if not url or not title:
                    continue
                summary = _strip_html(_strip_leading_photo(entry.get("summary") or entry.get("description") or ""))
                published = _to_dt(entry.get("published_parsed") or entry.get("updated_parsed"))
                image = _extract_image(entry)
                item = NewsItem(
                    source_id=src.id,
                    source_name=src.name,
                    category=src.category,
                    url=url,
                    title=title,
                    summary=_clean_summary(summary, src.summary_chars),
                    published_at=published,
                    image_url=image,
                )
                if enrich and (not item.image_url or len(item.summary) < 80):
                    item = _enrich_with_og(item, client)
                items.append(item)

    def _sort_key(item: NewsItem) -> datetime:
        ts = item.published_at or datetime.min
        if item.category == "dj":
            ts = ts + _DJ_BOOST
        return ts

    items.sort(key=_sort_key, reverse=True)
    return items
