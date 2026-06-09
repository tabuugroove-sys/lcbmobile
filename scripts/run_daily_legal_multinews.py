"""Daily long-form legal multinews video: top RSS stories -> 16:9 YouTube upload."""
from __future__ import annotations

import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import build_legal_star_horizontal_test as base  # noqa: E402
from scripts.build_legal_multinews_horizontal_test import ASSETS  # noqa: E402
from src.analytics import refresh_youtube_metrics, select_best_candidates  # noqa: E402
from src.config import ROOT, settings  # noqa: E402
from src.models import NewsItem  # noqa: E402
from src.scraper import collect_news, load_sources  # noqa: E402
from src.storage import Store  # noqa: E402


OUT = ROOT / "out" / "daily_legal_multinews"
PLATFORM = "youtube_daily_multinews"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
log = logging.getLogger(__name__)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _asset_ids_for_item(item: NewsItem) -> list[str]:
    text = _plain(f"{item.title} {item.summary}")
    if "shakira" in text:
        return ["shakira_un_imagine", "shakira_davos", "shakira_un_imagine"]
    if "dua lipa" in text or re.search(r"\bdua\b", text):
        return ["dua_radical", "dua_grammys", "dua_grammys"]
    if "calvin" in text or "harris" in text:
        return ["calvin_longitude_gif", "calvin_live_05", "calvin_live_04"]
    if "maroon" in text or "adam levine" in text or "rock in rio" in text:
        return ["rock_in_rio_crowd", "rock_in_rio_crowd", "calvin_live_04"]
    if "anitta" in text:
        return ["shakira_un_imagine", "rock_in_rio_crowd", "shakira_davos"]
    return ["rock_in_rio_crowd", "shakira_davos", "dua_grammys"]


def _scene_for(
    item: NewsItem,
    asset_id: str,
    *,
    news_index: int,
    scene_index: int,
    seek_start: float,
    title: str,
    body: str,
) -> dict[str, object]:
    crop_y = 900 if asset_id == "calvin_longitude_gif" else 0
    return {
        "asset_id": asset_id,
        "seek_start": seek_start,
        "duration": 7.0,
        "eyebrow": f"NEWS {news_index}  |  {item.source_name.upper()[:22]}",
        "title": _clip(title, 32),
        "body": _clip(body, 62),
        "crop_x": 30 + ((news_index + scene_index) % 4) * 30,
        "crop_y": crop_y,
        "loop_source": True,
    }


def _build_storyboard(items: list[NewsItem]) -> tuple[list[dict[str, object]], list[tuple[float, float, str]]]:
    scenes: list[dict[str, object]] = []
    narration: list[tuple[float, float, str]] = []
    t = 0.4
    for idx, item in enumerate(items, start=1):
        asset_ids = _asset_ids_for_item(item)
        title = _clip(item.title, 90)
        source = item.source_name
        summary = _clip(item.summary, 140) if item.summary else "A nota entra no radar pop de hoje."
        lines = [
            f"Destaque {idx}: {title}",
            f"Segundo {source}, {summary}",
            "A edicao usa apenas video licenciado ou b-roll editorial permitido, com audio original mutado.",
        ]
        scene_titles = [
            _clip(title, 34),
            "Contexto da noticia",
            "Radar pop do dia",
        ]
        scene_bodies = [
            f"Fonte: {source}",
            "Top 5 escolhido por sinais de frescor, drama e historico.",
            "Texto proprio, narracao propria e creditos no arquivo.",
        ]
        seeks = [0.0, 6.0, 12.0]
        for sub_index in range(3):
            start = t
            end = t + 7.0
            narration.append((start, end, lines[sub_index]))
            scenes.append(
                _scene_for(
                    item,
                    asset_ids[sub_index],
                    news_index=idx,
                    scene_index=sub_index,
                    seek_start=seeks[sub_index],
                    title=scene_titles[sub_index],
                    body=scene_bodies[sub_index],
                )
            )
            t = end
    return scenes, narration


def _select_top_items(limit: int, force: bool) -> tuple[Store, list[NewsItem], str]:
    store = Store(settings.db_path)
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date().isoformat()
    daily_fp = f"daily-legal-multinews:{today}"
    if store.is_seen(daily_fp) and not force:
        log.info("Daily multinews already posted today: %s", daily_fp)
        return store, [], daily_fp

    refresh_youtube_metrics(store)
    items = collect_news(load_sources(ROOT / "config" / "sources.yaml"))
    candidates: list[NewsItem] = []
    seen_hashes: set[str] = set()
    for item in items:
        fp = item.fingerprint()
        ch = item.content_hash()
        if store.is_seen(fp) or store.already_published(fp, PLATFORM):
            continue
        if ch and (store.is_seen_by_content(ch) or ch in seen_hashes):
            continue
        seen_hashes.add(ch)
        candidates.append(item)
        if len(candidates) >= max(settings.analytics_candidate_pool, limit):
            break

    selected = select_best_candidates(candidates, store, limit=limit, stage="daily_multinews")
    return store, selected, daily_fp


def _write_credits(items: list[NewsItem], scenes: list[dict[str, object]]) -> None:
    assets_by_id = {str(asset["id"]): asset for asset in ASSETS}
    used_asset_ids = []
    for scene in scenes:
        asset_id = str(scene["asset_id"])
        if asset_id not in used_asset_ids:
            used_asset_ids.append(asset_id)

    lines = ["News items:"]
    lines.extend(f"- {item.title} | {item.source_name} | {item.url}" for item in items)
    lines.append("")
    lines.append("Video assets:")
    for asset_id in used_asset_ids:
        asset = assets_by_id[asset_id]
        lines.append(f"- {asset['credit']} | {asset['source']} | {asset['license']}")
    lines.append("")
    lines.append("Sourcing policy:")
    lines.append("- See docs/legal_video_sources.md for whitelist/search rules.")
    (OUT / "credits.txt").write_text("\n".join(lines), encoding="utf-8")


def _build_video(items: list[NewsItem]) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    scenes, narration = _build_storyboard(items)
    package_news = {
        "title": f"Top {len(items)} noticias pop do dia",
        "source": "RSS + analytics scorer",
        "url": items[0].url if items else "",
    }
    base.OUT = OUT
    base.NEWS = package_news
    base.ASSETS = ASSETS
    base.SCENES = scenes
    base.NARRATION_SEGMENTS = narration
    base.download_assets()
    _write_credits(items, scenes)
    base.synthesize_voice()
    return base.build_video()


def _publish(video: Path, items: list[NewsItem]) -> str:
    today = datetime.now(ZoneInfo(settings.timezone)).strftime("%d/%m/%Y")
    title = f"Top 5 noticias pop de hoje | {today}"
    news_lines = "\n".join(f"- {item.title} ({item.source_name}): {item.url}" for item in items)
    credits = (OUT / "credits.txt").read_text(encoding="utf-8")
    description = (
        "Top 5 noticias pop selecionadas por sinais de frescor, drama e historico de performance.\n\n"
        "Noticias:\n"
        f"{news_lines}\n\n"
        "Creditos e licencas:\n"
        f"{credits}\n\n"
        "#PopNews #Celebridades #Fofoca #RockInRio #Noticias"
    )[:4900]
    tags = ["pop news", "celebridades", "fofoca", "Brasil", "Rock in Rio"]
    yt = _youtube_service()
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": tags,
            "categoryId": settings.youtube_category_id,
            "defaultLanguage": "pt-BR",
            "defaultAudioLanguage": "pt-BR",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(video), mimetype="video/mp4", resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    return str(response["id"])


def _youtube_service():
    token_file = Path(settings.youtube_token_file)
    creds: Credentials | None = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), YOUTUBE_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.youtube_client_secret_file), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_file.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


@click.command()
@click.option("--limit", type=int, default=5, show_default=True)
@click.option("--publish/--no-publish", default=True, show_default=True)
@click.option("--force", is_flag=True, default=False)
@click.option("-v", "--verbose", is_flag=True, default=False)
def main(limit: int, publish: bool, force: bool, verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    store, items, daily_fp = _select_top_items(limit, force)
    if not items:
        click.echo(f"daily_multinews=skipped fingerprint={daily_fp}")
        return
    video = _build_video(items)
    click.echo(f"daily_multinews_video={video}")
    if not publish:
        click.echo("daily_multinews=dry_run")
        return

    try:
        video_id = _publish(video, items)
    except HttpError as exc:
        log.error("Daily multinews YouTube upload failed: %s", exc)
        raise

    store.mark_seen(daily_fp, "daily_multinews", "", f"Daily legal multinews {daily_fp}")
    for item in items:
        store.record_item_features(item)
        store.mark_seen(
            item.fingerprint(),
            item.source_id,
            item.url,
            item.title,
            content_hash=item.content_hash(),
        )
        store.record_publication(
            item.fingerprint(),
            PLATFORM,
            video_id,
            "ok",
            content_hash=item.content_hash(),
        )
    click.echo(f"youtube_video_id={video_id}")
    click.echo(f"youtube_url=https://www.youtube.com/watch?v={video_id}")


if __name__ == "__main__":
    main()
