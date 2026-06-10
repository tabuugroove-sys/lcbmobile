"""Daily long-form legal multinews video: top RSS stories -> 16:9 YouTube upload."""
from __future__ import annotations

import logging
import re
import hashlib
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
from src.analytics.traffic_experiments import (  # noqa: E402
    TrafficProfile,
    choose_traffic_profile,
    experiment_reason,
    headline_angle,
    order_items_for_profile,
)
from src.config import ROOT, settings  # noqa: E402
from src.models import NewsItem  # noqa: E402
from src.storage import Store  # noqa: E402


OUT = ROOT / "out" / "daily_legal_multinews"
PLATFORM = "youtube_daily_multinews"
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
log = logging.getLogger(__name__)

_ENTERTAINMENT_TERMS = {
    "ator",
    "atriz",
    "artista",
    "banda",
    "bbb",
    "cantor",
    "cantora",
    "celebridade",
    "dj",
    "elenco",
    "famoso",
    "famosa",
    "festival",
    "forro",
    "influenciador",
    "musica",
    "novela",
    "palco",
    "rock",
    "sertanejo",
    "show",
    "vocalista",
}

_NON_ENTERTAINMENT_TERMS = {
    "aposentadoria",
    "banco",
    "cartao",
    "clt",
    "credito",
    "fgts",
    "financiamento",
    "inss",
    "itau",
    "lei",
    "nubank",
    "salario",
}

_TAG_STOPWORDS = {
    "acontece",
    "ainda",
    "antes",
    "apenas",
    "assim",
    "com",
    "como",
    "das",
    "depois",
    "dos",
    "esta",
    "este",
    "mais",
    "para",
    "pela",
    "pelo",
    "por",
    "que",
    "sao",
    "sem",
    "ser",
    "sobre",
    "sua",
    "suas",
    "tem",
    "uma",
}

_KNOWN_ENTITIES = (
    "Shakira",
    "Dua Lipa",
    "Calvin Harris",
    "Maroon 5",
    "Adam Levine",
    "Anitta",
    "Madonna",
    "Rock in Rio",
    "Caetano Veloso",
    "Gilberto Gil",
    "Djavan",
    "Ronaldinho",
    "Mexico",
)

_GENERIC_STAGE_ASSETS = [
    "rock_in_rio_crowd",
    "calvin_live_01",
    "calvin_live_02",
    "calvin_live_03",
    "calvin_live_04",
    "calvin_live_05",
    "calvin_longitude_gif",
]

_ENTITY_ASSETS = {
    "shakira": ["shakira_un_imagine", "shakira_davos", "rock_in_rio_crowd"],
    "dua": ["dua_radical", "dua_grammys", "rock_in_rio_crowd"],
    "calvin": ["calvin_longitude_gif", "calvin_live_05", "calvin_live_04"],
    "maroon": ["rock_in_rio_crowd", "calvin_live_01", "calvin_live_03"],
    "madonna": ["madonna_russia_speech", "rock_in_rio_crowd", "calvin_live_02"],
    "caetano": ["caetano_unicamp", "rock_in_rio_crowd", "calvin_live_01"],
    "gilberto": ["caetano_unicamp", "rock_in_rio_crowd", "calvin_live_02"],
    "djavan": ["caetano_unicamp", "rock_in_rio_crowd", "calvin_live_03"],
    "ronaldinho": ["ronaldinho_embratur", "mexico_olympic_stadium", "rock_in_rio_crowd"],
    "mexico": ["mexico_olympic_stadium", "rock_in_rio_crowd", "calvin_live_05"],
}


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return decomposed.encode("ascii", "ignore").decode("ascii").lower()


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _timestamp(seconds: int) -> str:
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _detected_entities(items: list[NewsItem]) -> list[str]:
    text = _plain(" ".join(f"{item.title} {item.summary}" for item in items))
    found: list[str] = []
    for entity in _KNOWN_ENTITIES:
        if _plain(entity) in text:
            found.append(entity)
    return found


def _keyword_tags(items: list[NewsItem]) -> list[str]:
    tags = [
        "pop news",
        "noticias dos famosos",
        "celebridades",
        "fofoca",
        "musica",
        "Brasil",
    ]
    tags.extend(_detected_entities(items))
    for item in items:
        for token in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]{4,}", item.title):
            plain = _plain(token)
            if plain in _TAG_STOPWORDS:
                continue
            tag = token[:30]
            if tag not in tags:
                tags.append(tag)
            if len(tags) >= 28:
                return tags
    return tags[:28]


def _youtube_metadata(
    items: list[NewsItem],
    profile: TrafficProfile,
) -> tuple[str, str, list[str]]:
    today = datetime.now(ZoneInfo(settings.timezone)).strftime("%d/%m/%Y")
    entities = _detected_entities(items)
    count = len(items)
    if profile.id == "conflict_first":
        title = f"{_clip(items[0].title, 62)} | Top {count} pop {today}"
    elif profile.id == "star_name_first" and entities:
        focus = ", ".join(entities[:3])
        title = f"{focus}: as {count} noticias pop de hoje | {today}"
    else:
        main_topic = _clip(items[0].title, 42)
        title = f"Top {count} noticias dos famosos hoje: {main_topic} | {today}"

    chapters = ["00:00 Abertura e noticia 1"]
    for index, item in enumerate(items[1:], start=2):
        chapters.append(f"{_timestamp((index - 1) * 21)} Noticia {index}: {_clip(item.title, 48)}")

    news_lines = "\n".join(
        f"{index}. {item.title}\n   Fonte: {item.source_name}\n   Link: {item.url}"
        for index, item in enumerate(items, start=1)
    )
    credits = (OUT / "credits.txt").read_text(encoding="utf-8")
    description = (
        f"Top {count} noticias pop do dia em formato editorial, com narracao propria, "
        "texto na tela e videos licenciados/creditados.\n\n"
        "O que tem no video:\n"
        f"{news_lines}\n\n"
        "Capitulos:\n"
        f"{chr(10).join(chapters)}\n\n"
        "Como o video foi feito:\n"
        "- Selecao por RSS + sinais de frescor, drama e historico de performance.\n"
        f"- Teste editorial ativo: {profile.label} ({profile.id}).\n"
        f"- Hipotese: {profile.hypothesis}\n"
        "- Audio original dos videos mutado.\n"
        "- Uso apenas de videos com licenca, press permission ou b-roll editorial permitido.\n\n"
        "Creditos e licencas:\n"
        f"{credits}\n\n"
        "#PopNews #Celebridades #Fofoca #NoticiasDosFamosos #Noticias"
    )[:4900]
    return title[:100], description, _keyword_tags(items)


def _is_entertainment_item(item: NewsItem) -> bool:
    text = _plain(f"{item.title} {item.summary} {item.category}")
    tokens = set(re.findall(r"[a-z0-9]+", text))
    if tokens & _NON_ENTERTAINMENT_TERMS:
        return False
    if item.category in {"celebridades", "fofoca", "dj"}:
        return True
    return bool(tokens & _ENTERTAINMENT_TERMS)


def _is_today_item(item: NewsItem, tz: ZoneInfo, today: str | None = None) -> bool:
    """Keep the daily package tied to the current local news date."""
    if not item.published_at:
        return False
    published = item.published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=ZoneInfo("UTC"))
    target_date = today or datetime.now(tz).date().isoformat()
    return published.astimezone(tz).date().isoformat() == target_date


def _visual_support_key(item: NewsItem) -> str | None:
    """Return the direct legal-video support bucket for a story, if available."""
    text = _plain(f"{item.title} {item.summary}")
    if "shakira" in text:
        return "shakira"
    if "waka waka" in text:
        return "shakira"
    if "dua lipa" in text or re.search(r"\bdua\b", text):
        return "dua"
    if "calvin" in text or "harris" in text:
        return "calvin"
    if "maroon" in text or "adam levine" in text or "rock in rio" in text:
        return "maroon"
    if "madonna" in text:
        return "madonna"
    if "caetano" in text:
        return "caetano"
    if "gilberto gil" in text or "gilberto" in text:
        return "gilberto"
    if "djavan" in text:
        return "djavan"
    if "ronaldinho" in text:
        return "ronaldinho"
    if "copa do mundo" in text or "world cup" in text:
        return "mexico"
    return None


def _stable_index(value: str, modulo: int) -> int:
    if modulo <= 0:
        return 0
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulo


def _pick_assets(
    candidates: list[str],
    *,
    key: str,
    recent_assets: list[str],
    count: int = 3,
    prefer_in_order: bool = False,
) -> list[str]:
    preferred: list[str] = []
    for asset_id in candidates:
        if asset_id not in preferred:
            preferred.append(asset_id)
    support_pool: list[str] = []
    for asset_id in preferred + _GENERIC_STAGE_ASSETS:
        if asset_id not in support_pool:
            support_pool.append(asset_id)
    if not support_pool:
        return []

    selected: list[str] = []
    if prefer_in_order:
        for asset_id in preferred:
            if not selected and recent_assets and asset_id == recent_assets[-1]:
                continue
            selected.append(asset_id)
            if len(selected) >= count:
                break

    offset = _stable_index(key, len(support_pool))
    ordered = support_pool[offset:] + support_pool[:offset]
    for asset_id in ordered:
        if asset_id in selected:
            continue
        if not selected and recent_assets and asset_id == recent_assets[-1]:
            continue
        selected.append(asset_id)
        if len(selected) >= count:
            break

    for asset_id in ordered:
        if len(selected) >= count:
            break
        if asset_id not in selected:
            selected.append(asset_id)

    return selected[:count]


def _asset_ids_for_item(item: NewsItem, recent_assets: list[str] | None = None) -> list[str]:
    recent_assets = recent_assets or []
    support_key = _visual_support_key(item)
    if support_key:
        return _pick_assets(
            _ENTITY_ASSETS[support_key],
            key=item.fingerprint(),
            recent_assets=recent_assets,
            prefer_in_order=True,
        )
    return _pick_assets(_GENERIC_STAGE_ASSETS, key=item.fingerprint(), recent_assets=recent_assets)


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


def _build_storyboard(
    items: list[NewsItem],
    profile: TrafficProfile,
) -> tuple[list[dict[str, object]], list[tuple[float, float, str]]]:
    scenes: list[dict[str, object]] = []
    narration: list[tuple[float, float, str]] = []
    recent_assets: list[str] = []
    t = 0.4
    for idx, item in enumerate(items, start=1):
        asset_ids = _asset_ids_for_item(item, recent_assets)
        title = _clip(item.title, 90)
        source = item.source_name
        summary = _clip(item.summary, 140) if item.summary else "A nota entra no radar pop de hoje."
        lead_line = headline_angle(item, profile) if idx == 1 else f"Destaque {idx}: {title}"
        lines = [
            lead_line,
            f"Segundo {source}, {summary}",
            "A edicao usa apenas video licenciado ou b-roll editorial permitido, com audio original mutado.",
        ]
        scene_titles = [
            _clip(lead_line, 34),
            "Contexto da noticia",
            "Radar pop do dia",
        ]
        scene_bodies = [
            profile.opening_body if idx == 1 else f"Fonte: {source}",
            f"Top {len(items)} escolhido por sinais de frescor, drama e historico.",
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
            recent_assets.append(asset_ids[sub_index])
            t = end
    return scenes, narration


def _select_top_items(limit: int, force: bool) -> tuple[Store, list[NewsItem], str]:
    from src.scraper import collect_news, load_sources

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
        if not _is_today_item(item, tz, today):
            log.info("Skipping item outside today's local date: %s", item.title)
            continue
        if not _is_entertainment_item(item):
            log.info("Skipping non-entertainment item: %s", item.title)
            continue
        if not _visual_support_key(item):
            log.info("Skipping item without direct legal video support: %s", item.title)
            continue
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

    if len(candidates) < 2:
        log.warning(
            "Daily multinews skipped: only %d visually supported candidate(s)",
            len(candidates),
        )
        return store, [], daily_fp
    selected = select_best_candidates(candidates, store, limit=limit, stage="daily_multinews")
    return store, selected, daily_fp


def _write_credits(
    items: list[NewsItem],
    scenes: list[dict[str, object]],
    profile: TrafficProfile,
) -> None:
    assets_by_id = {str(asset["id"]): asset for asset in ASSETS}
    used_asset_ids = []
    for scene in scenes:
        asset_id = str(scene["asset_id"])
        if asset_id not in used_asset_ids:
            used_asset_ids.append(asset_id)

    lines = ["News items:"]
    lines.extend(f"- {item.title} | {item.source_name} | {item.url}" for item in items)
    lines.append("")
    lines.append("Traffic experiment:")
    lines.append(f"- Profile: {profile.id} ({profile.label})")
    lines.append(f"- Hypothesis: {profile.hypothesis}")
    lines.append(f"- Lead reason: {experiment_reason(items, profile)}")
    lines.append("")
    lines.append("Video assets:")
    for asset_id in used_asset_ids:
        asset = assets_by_id[asset_id]
        lines.append(f"- {asset['credit']} | {asset['source']} | {asset['license']}")
    lines.append("")
    lines.append("Sourcing policy:")
    lines.append("- See docs/legal_video_sources.md for whitelist/search rules.")
    (OUT / "credits.txt").write_text("\n".join(lines), encoding="utf-8")


def _build_video(items: list[NewsItem], profile: TrafficProfile) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    scenes, narration = _build_storyboard(items, profile)
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
    _write_credits(items, scenes, profile)
    base.synthesize_voice()
    return base.build_video()


def _publish(video: Path, items: list[NewsItem], profile: TrafficProfile) -> tuple[str, str]:
    title, description, tags = _youtube_metadata(items, profile)
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
    return str(response["id"]), title


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
@click.option(
    "--traffic-profile",
    default="auto",
    show_default=True,
    help="auto, conflict_first, star_name_first, or fast_countdown",
)
@click.option("-v", "--verbose", is_flag=True, default=False)
def main(
    limit: int,
    publish: bool,
    force: bool,
    traffic_profile: str,
    verbose: bool,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    store, items, daily_fp = _select_top_items(limit, force)
    if not items:
        click.echo(f"daily_multinews=skipped fingerprint={daily_fp}")
        return
    profile = choose_traffic_profile(daily_fp, traffic_profile)
    items = order_items_for_profile(items, profile)
    click.echo(f"traffic_profile={profile.id} reason={experiment_reason(items, profile)}")
    video = _build_video(items, profile)
    click.echo(f"daily_multinews_video={video}")
    if not publish:
        click.echo("daily_multinews=dry_run")
        return

    try:
        video_id, youtube_title = _publish(video, items, profile)
    except HttpError as exc:
        log.error("Daily multinews YouTube upload failed: %s", exc)
        raise

    store.record_traffic_experiment(
        video_id=video_id,
        fingerprint=daily_fp,
        platform=PLATFORM,
        profile_id=profile.id,
        hypothesis=profile.hypothesis,
        title=youtube_title,
        item_count=len(items),
    )
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
