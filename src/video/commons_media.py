"""Find reusable artist photographs with explicit Wikimedia Commons rights."""
from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "LCBMobileNews/1.0 (editorial media resolver)"
ALLOWED_LICENSE_PREFIXES = ("CC BY ", "CC0", "Public domain")
BLOCKED_TITLE_TERMS = {
    "album",
    "cover",
    "gear",
    "logo",
    "poster",
    "signature",
    "single",
    "svg",
    "ticket",
}
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class LicensedImage:
    path: str
    title: str
    creator: str
    license: str
    license_url: str
    source_page: str
    source_url: str
    width: int
    height: int

    def as_manifest(self) -> dict[str, object]:
        return asdict(self)


def _plain(value: str) -> str:
    value = TAG_RE.sub(" ", html.unescape(value or ""))
    value = unicodedata.normalize("NFKD", value)
    return re.sub(r"\s+", " ", value.encode("ascii", "ignore").decode("ascii")).strip().lower()


def _meta(metadata: dict[str, object], name: str) -> str:
    node = metadata.get(name)
    if isinstance(node, dict):
        return str(node.get("value") or "")
    return ""


def _candidate(page: dict[str, object], query: str) -> dict[str, object] | None:
    info_rows = page.get("imageinfo")
    if not isinstance(info_rows, list) or not info_rows:
        return None
    info = info_rows[0]
    if not isinstance(info, dict):
        return None
    metadata = info.get("extmetadata")
    if not isinstance(metadata, dict):
        metadata = {}
    display_license = TAG_RE.sub("", html.unescape(_meta(metadata, "LicenseShortName"))).strip()
    if not any(display_license.startswith(prefix) for prefix in ALLOWED_LICENSE_PREFIXES):
        return None
    mime = str(info.get("mime") or "")
    if mime not in {"image/jpeg", "image/png"}:
        return None
    width = int(info.get("thumbwidth") or info.get("width") or 0)
    height = int(info.get("thumbheight") or info.get("height") or 0)
    if min(width, height) < 700:
        return None
    title = str(page.get("title") or "")
    plain_title = _plain(title.removeprefix("File:").replace("_", " "))
    compact_title = plain_title.replace(" ", "")
    plain_query = _plain(query)
    if not (
        plain_title.startswith(plain_query)
        or compact_title.startswith(plain_query.replace(" ", ""))
    ):
        return None
    if set(plain_title.split()) & BLOCKED_TITLE_TERMS:
        return None
    description = " ".join(
        [
            title,
            _meta(metadata, "ObjectName"),
            _meta(metadata, "ImageDescription"),
        ]
    )
    query_tokens = [token for token in _plain(query).split() if len(token) > 2]
    haystack = _plain(description)
    if query_tokens and not all(token in haystack for token in query_tokens):
        return None
    source_url = str(info.get("thumburl") or info.get("url") or "")
    if not source_url:
        return None
    creator = TAG_RE.sub(" ", html.unescape(_meta(metadata, "Artist"))).strip()
    creator = re.split(r"Camera location|View this", creator, maxsplit=1)[0].strip()
    return {
        "title": title.removeprefix("File:"),
        "creator": creator or "Wikimedia Commons contributor",
        "license": display_license,
        "license_url": TAG_RE.sub("", _meta(metadata, "LicenseUrl")).strip(),
        "source_page": str(info.get("descriptionurl") or ""),
        "source_url": source_url,
        "width": width,
        "height": height,
    }


def fetch_licensed_artist_images(
    query: str | None,
    output_dir: Path,
    *,
    limit: int = 6,
    client: httpx.Client | None = None,
) -> list[LicensedImage]:
    """Download photos whose metadata permits commercial adaptation.

    Share-alike files are deliberately excluded: the channel should not silently
    inherit a license obligation for the complete video.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "rights_manifest.json"
    if not query:
        manifest_path.write_text(
            json.dumps({"query": None, "status": "no_known_artist", "assets": []}, indent=2) + "\n"
        )
        return []

    if manifest_path.exists():
        try:
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            cached_assets = [LicensedImage(**row) for row in cached.get("assets", [])]
            if (
                cached.get("query") == query
                and cached.get("status") == "verified"
                and cached_assets
                and all(Path(asset.path).exists() for asset in cached_assets)
            ):
                log.info("Commons media resolver: reusing %d cached assets", len(cached_assets))
                return cached_assets[:limit]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            log.warning("Ignoring unusable cached rights manifest: %s", manifest_path)

    owns_client = client is None
    client = client or httpx.Client(
        timeout=25.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        response = client.get(
            API_URL,
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": f'"{query}" filetype:bitmap',
                "gsrnamespace": "6",
                "gsrlimit": "35",
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "iiurlwidth": "1600",
                "format": "json",
                "formatversion": "2",
            },
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", [])
        candidates = [row for page in pages if (row := _candidate(page, query))]
        candidates.sort(
            key=lambda row: (
                0 if str(row["license"]).startswith("Public domain") else 1,
                -int(row["height"]),
            )
        )

        assets: list[LicensedImage] = []
        seen_pages: set[str] = set()
        for candidate in candidates:
            source_page = str(candidate["source_page"])
            if source_page in seen_pages:
                continue
            seen_pages.add(source_page)
            suffix = Path(urlparse(str(candidate["source_url"])).path).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png"}:
                suffix = ".jpg"
            path = output_dir / f"artist-{len(assets) + 1:02d}{suffix}"
            media_response = client.get(str(candidate["source_url"]))
            media_response.raise_for_status()
            path.write_bytes(media_response.content)
            try:
                asset = LicensedImage(path=str(path), **candidate)
            except TypeError:
                path.unlink(missing_ok=True)
                raise
            assets.append(asset)
            if len(assets) >= limit:
                break

        status = "verified" if assets else "no_verified_media"
        manifest_path.write_text(
            json.dumps(
                {"query": query, "status": status, "assets": [asset.as_manifest() for asset in assets]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        log.info("Commons media resolver: query=%r verified=%d", query, len(assets))
        return assets
    except Exception as exc:  # noqa: BLE001
        log.warning("Commons media resolver failed for %r: %s", query, exc)
        manifest_path.write_text(
            json.dumps(
                {"query": query, "status": "resolver_error", "error": str(exc), "assets": []},
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        return []
    finally:
        if owns_client:
            client.close()
