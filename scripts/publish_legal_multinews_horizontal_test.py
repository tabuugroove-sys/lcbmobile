"""Publish the legal multinews horizontal test video to YouTube."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from googleapiclient.errors import HttpError  # noqa: E402
from googleapiclient.http import MediaFileUpload  # noqa: E402

from scripts.build_legal_multinews_horizontal_test import NEWS_ITEMS, OUT  # noqa: E402
from src.config import settings  # noqa: E402
from src.publisher.youtube import YouTubePublisher  # noqa: E402


log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    video = OUT / "legal_star_horizontal.mp4"
    credits = OUT / "credits.txt"
    if not video.exists():
        raise FileNotFoundError(f"Video not found: {video}")

    title = "Shakira, Dua Lipa e Rock in Rio: radar pop com videos legais"
    news_lines = "\n".join(f"- {item['title']} ({item['source']}): {item['url']}" for item in NEWS_ITEMS)
    credits_text = credits.read_text(encoding="utf-8") if credits.exists() else ""
    description = (
        "Radar pop em formato editorial: Shakira, Dua Lipa, Calvin Harris e Maroon 5 no contexto das noticias.\n\n"
        "Video com narracao propria, texto na tela e imagens licenciadas/creditadas.\n\n"
        "Noticias:\n"
        f"{news_lines}\n\n"
        "Creditos de video:\n"
        f"{credits_text}\n\n"
        "#Shakira #DuaLipa #CalvinHarris #Maroon5 #RockInRio #PopNews"
    )[:4900]
    tags = [
        "Shakira",
        "Dua Lipa",
        "Calvin Harris",
        "Maroon 5",
        "Rock in Rio",
        "pop news",
        "celebridades",
        "Brasil",
    ]

    try:
        yt = YouTubePublisher()._service()
        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags,
                "categoryId": settings.youtube_category_id,
                "defaultLanguage": "pt-BR",
                "defaultAudioLanguage": "pt-BR",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(str(video), mimetype="video/mp4", resumable=True)
        request = yt.videos().insert(part="snippet,status", body=body, media_body=media)
        response = None
        while response is None:
            _, response = request.next_chunk()
        video_id = response["id"]
        print(f"youtube_video_id={video_id}")
        print(f"youtube_url=https://www.youtube.com/watch?v={video_id}")
    except HttpError as exc:
        log.error("YouTube upload failed: %s", exc)
        raise


if __name__ == "__main__":
    main()
