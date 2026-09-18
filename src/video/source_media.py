"""Download the editorial image supplied by the source article."""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image

from ..models import NewsItem
from .commons_media import LicensedImage

log = logging.getLogger(__name__)

USER_AGENT = "LCBMobileNews/1.1 (https://github.com/tabuugroove-sys/lcbmobile)"
SOURCE_ARTICLE_LICENSE = "Editorial source image; reuse rights not verified"
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def fetch_source_article_image(
    item: NewsItem,
    output_dir: Path,
    *,
    client: httpx.Client | None = None,
) -> LicensedImage | None:
    """Cache the RSS/OpenGraph image when no reusable Commons photo exists."""
    image_url = str(getattr(item, "image_url", None) or "").strip()
    if urlparse(image_url).scheme not in {"http", "https"}:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    image_path = output_dir / "source-article.jpg"
    manifest_path = output_dir / "source_image_manifest.json"
    if image_path.exists() and manifest_path.exists():
        try:
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            if cached.get("source_url") == image_url:
                return LicensedImage(**cached)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            log.warning("Ignoring unusable source-image cache: %s", manifest_path)

    owns_client = client is None
    client = client or httpx.Client(
        timeout=25.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        response = client.get(image_url, headers={"Referer": item.url})
        response.raise_for_status()
        content = response.content
        if not content or len(content) > MAX_IMAGE_BYTES:
            return None
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            width, height = source.size
            if min(width, height) < 300:
                return None
            if source.mode != "RGB":
                source = source.convert("RGB")
            source.save(image_path, format="JPEG", quality=92, optimize=True)

        asset = LicensedImage(
            path=str(image_path),
            title=item.title,
            creator=item.source_name,
            license=SOURCE_ARTICLE_LICENSE,
            license_url=item.url,
            source_page=item.url,
            source_url=image_url,
            width=width,
            height=height,
        )
        manifest_path.write_text(
            json.dumps(asset.as_manifest(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return asset
    except (OSError, httpx.HTTPError, Image.UnidentifiedImageError) as exc:
        log.warning("Source article image unavailable for %s: %s", item.url, exc)
        return None
    finally:
        if owns_client:
            client.close()
