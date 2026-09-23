"""Download the editorial image supplied by the source article."""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from ..models import NewsItem
from .commons_media import LicensedImage

log = logging.getLogger(__name__)

USER_AGENT = "LCBMobileNews/1.1 (https://github.com/tabuugroove-sys/lcbmobile)"
SOURCE_ARTICLE_LICENSE = "Editorial source image; reuse rights not verified"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
BLOCKED_IMAGE_TERMS = {
    "advert",
    "author",
    "avatar",
    "banner",
    "gravatar",
    "icon",
    "leia-tambem",
    "logo",
    "recommended",
    "related",
    "share",
}


def _image_hash(image: Image.Image) -> tuple[int, tuple[int, int, int]]:
    rgb = image.convert("RGB")
    sample = rgb.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(sample.getdata())
    value = 0
    for row in range(8):
        for column in range(8):
            left = pixels[row * 9 + column]
            right = pixels[row * 9 + column + 1]
            value = (value << 1) | int(left > right)
    color = tuple(int(channel) for channel in rgb.resize((1, 1)).getpixel((0, 0)))
    return value, color


def _blocked_image_node(image) -> bool:
    values = [str(image.get("alt") or ""), str(image.get("class") or "")]
    parent = image.parent
    for _ in range(5):
        if parent is None:
            break
        values.extend(
            [
                str(parent.get("id") or ""),
                " ".join(parent.get("class") or []),
            ]
        )
        parent = parent.parent
    plain = " ".join(values).casefold()
    return any(term in plain for term in BLOCKED_IMAGE_TERMS)


def _node_url(image) -> str:
    for attribute in ("src", "data-src", "data-lazy-src", "data-original"):
        value = str(image.get(attribute) or "").strip()
        if value:
            return value
    srcset = str(image.get("srcset") or image.get("data-srcset") or "")
    if srcset:
        return srcset.split(",")[-1].strip().split()[0]
    return ""


def _article_image_candidates(item: NewsItem, html_text: str) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    if item.image_url:
        candidates.append((str(item.image_url), item.title))
    soup = BeautifulSoup(html_text or "", "lxml")
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        candidates.append((str(og_image["content"]), item.title))

    roots = [
        soup.find("article"),
        soup.select_one(".entry-content"),
        soup.select_one(".post-content"),
        soup.find("main"),
    ]
    seen_nodes: set[int] = set()
    for root in (node for node in roots if node is not None):
        for image in root.find_all("img"):
            if id(image) in seen_nodes or _blocked_image_node(image):
                continue
            seen_nodes.add(id(image))
            raw_url = _node_url(image)
            if not raw_url or raw_url.startswith("data:"):
                continue
            url = urljoin(item.url, raw_url)
            if urlparse(url).scheme not in {"http", "https"}:
                continue
            if urlparse(url).path.casefold().endswith(".svg"):
                continue
            candidates.append((url, str(image.get("alt") or item.title).strip()))

    unique: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for url, title in candidates:
        normalized = url.split("#", 1)[0]
        if normalized in seen_urls:
            continue
        seen_urls.add(normalized)
        unique.append((url, title))
    return unique


def fetch_source_article_images(
    item: NewsItem,
    output_dir: Path,
    *,
    limit: int = 4,
    client: httpx.Client | None = None,
) -> list[LicensedImage]:
    """Cache visually distinct editorial images from the source article."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "source_images_manifest.json"
    if manifest_path.exists():
        try:
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            assets = [LicensedImage(**row) for row in cached.get("assets", [])]
            if (
                cached.get("article_url") == item.url
                and assets
                and all(Path(asset.path).exists() for asset in assets)
            ):
                return assets[:limit]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            log.warning("Ignoring unusable source-image cache: %s", manifest_path)

    owns_client = client is None
    client = client or httpx.Client(
        timeout=25.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        html_text = ""
        if limit > 1:
            try:
                article_response = client.get(item.url)
                article_response.raise_for_status()
                html_text = article_response.text
            except httpx.HTTPError as exc:
                log.warning("Source article HTML unavailable for %s: %s", item.url, exc)

        candidates = _article_image_candidates(item, html_text)
        assets: list[LicensedImage] = []
        hashes: list[tuple[int, tuple[int, int, int]]] = []
        for image_url, title in candidates:
            if len(assets) >= max(1, limit):
                break
            try:
                response = client.get(image_url, headers={"Referer": item.url})
                response.raise_for_status()
                content = response.content
                if not content or len(content) > MAX_IMAGE_BYTES:
                    continue
                with Image.open(io.BytesIO(content)) as source:
                    source.load()
                    width, height = source.size
                    if min(width, height) < 300:
                        continue
                    signature = _image_hash(source)
                    if any(
                        (signature[0] ^ previous[0]).bit_count() <= 6
                        and sum(
                            abs(left - right)
                            for left, right in zip(signature[1], previous[1])
                        )
                        <= 45
                        for previous in hashes
                    ):
                        continue
                    hashes.append(signature)
                    if source.mode != "RGB":
                        source = source.convert("RGB")
                    suffix = "" if not assets else f"-{len(assets) + 1:02d}"
                    image_path = output_dir / f"source-article{suffix}.jpg"
                    source.save(image_path, format="JPEG", quality=92, optimize=True)
                assets.append(
                    LicensedImage(
                        path=str(image_path),
                        title=title or item.title,
                        creator=item.source_name,
                        license=SOURCE_ARTICLE_LICENSE,
                        license_url=item.url,
                        source_page=item.url,
                        source_url=image_url,
                        width=width,
                        height=height,
                    )
                )
            except (OSError, httpx.HTTPError, Image.UnidentifiedImageError) as exc:
                log.debug("Skipping source image %s: %s", image_url, exc)

        manifest_path.write_text(
            json.dumps(
                {
                    "article_url": item.url,
                    "assets": [asset.as_manifest() for asset in assets],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return assets
    finally:
        if owns_client:
            client.close()


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
    assets = fetch_source_article_images(item, output_dir, limit=1, client=client)
    return assets[0] if assets else None
