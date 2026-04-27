"""Generate a 1080x1920 vertical Short:

- Background = blurred Ken-Burns-zoomed source image (or solid color fallback).
- Overlay = bold on-screen text chunks rotating with the narration.
- Audio = gTTS narration of the script_voiceover (pt-BR).

Designed to run in a stock Python container without GPU. Requires `ffmpeg`
available on PATH (moviepy + gTTS handle the rest).
"""
from __future__ import annotations

import logging
import math
import tempfile
from pathlib import Path

import httpx
from gtts import gTTS
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    concatenate_videoclips,
)

from ..models import GeneratedAssets, NewsItem, RewrittenPost

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1920
DEFAULT_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _find_font() -> str | None:
    for path in DEFAULT_FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def _download_image(url: str, dest: Path) -> Path | None:
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            dest.write_bytes(resp.content)
            return dest
    except Exception as exc:  # noqa: BLE001
        log.warning("Image download failed (%s): %s", url, exc)
        return None


def _make_background(image_path: Path | None, out_path: Path) -> Path:
    """Build a 1080x1920 blurred-cover background image."""
    if image_path and image_path.exists():
        try:
            img = Image.open(image_path).convert("RGB")
        except Exception:  # noqa: BLE001
            img = None
    else:
        img = None

    if img is None:
        bg = Image.new("RGB", (WIDTH, HEIGHT), (18, 12, 28))
    else:
        # Cover-fit and blur for the background.
        ratio = max(WIDTH / img.width, HEIGHT / img.height)
        new_size = (int(img.width * ratio), int(img.height * ratio))
        cover = img.resize(new_size, Image.LANCZOS)
        left = (cover.width - WIDTH) // 2
        top = (cover.height - HEIGHT) // 2
        bg = cover.crop((left, top, left + WIDTH, top + HEIGHT))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=22))

        # Foreground: same image fitted into a centered card.
        card_w = int(WIDTH * 0.82)
        card_h = int(card_w * img.height / img.width)
        fg = img.resize((card_w, card_h), Image.LANCZOS)
        bg.paste(fg, ((WIDTH - card_w) // 2, int(HEIGHT * 0.18)))

    # Vignette / dark gradient at the bottom for legibility.
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for i in range(400):
        alpha = int(180 * (i / 400))
        draw.rectangle([0, HEIGHT - 400 + i, WIDTH, HEIGHT - 399 + i], fill=(0, 0, 0, alpha))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    bg.save(out_path, "JPEG", quality=88)
    return out_path


def _tts(text: str, lang: str, dest: Path) -> Path:
    tts = gTTS(text=text, lang=lang.split("-")[0] or "pt", tld="com.br", slow=False)
    tts.save(dest)
    return dest


def _text_clip(text: str, duration: float, font: str | None) -> CompositeVideoClip:
    kwargs = dict(
        txt=text.upper(),
        fontsize=92,
        color="white",
        stroke_color="black",
        stroke_width=4,
        method="caption",
        size=(int(WIDTH * 0.86), None),
        align="center",
    )
    if font:
        kwargs["font"] = font
    clip = TextClip(**kwargs).set_duration(duration).set_position(("center", int(HEIGHT * 0.66)))
    return clip


def build_short(
    item: NewsItem,
    post: RewrittenPost,
    output_dir: Path,
    *,
    lang: str = "pt-BR",
) -> GeneratedAssets:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / item.fingerprint().replace("/", "_").replace(":", "_")[-80:]
    base.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        image_path: Path | None = None
        if item.image_url:
            image_path = _download_image(item.image_url, tmp_path / "src.jpg")

        bg_path = _make_background(image_path, base / "bg.jpg")
        audio_path = _tts(post.script_voiceover, lang, base / "voice.mp3")

        audio = AudioFileClip(str(audio_path))
        duration = max(8.0, min(60.0, audio.duration + 0.4))

        bg_clip = ImageClip(str(bg_path)).set_duration(duration)
        # Subtle Ken-Burns zoom for life.
        bg_clip = bg_clip.resize(lambda t: 1 + 0.04 * math.sin(t / duration * math.pi))

        font = _find_font()
        chunks = post.on_screen_text or [post.headline]
        per_chunk = duration / max(1, len(chunks))
        text_clips = [
            _text_clip(chunk, per_chunk, font).set_start(i * per_chunk)
            for i, chunk in enumerate(chunks)
        ]

        # Source attribution badge in the corner.
        badge_kwargs = dict(
            txt=f"via {item.source_name}",
            fontsize=36,
            color="white",
            method="label",
        )
        if font:
            badge_kwargs["font"] = font
        badge = (
            TextClip(**badge_kwargs)
            .set_duration(duration)
            .margin(left=20, right=20, top=10, bottom=10, color=(0, 0, 0), opacity=0.6)
            .set_position(("center", int(HEIGHT * 0.06)))
        )

        composite = CompositeVideoClip(
            [bg_clip, badge, *text_clips], size=(WIDTH, HEIGHT)
        ).set_audio(audio).set_duration(duration)

        video_path = base / "short.mp4"
        composite.write_videofile(
            str(video_path),
            fps=30,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=2,
            verbose=False,
            logger=None,
        )

        # Thumbnail = first frame.
        thumb_path = base / "thumb.jpg"
        composite.save_frame(str(thumb_path), t=0.3)

    return GeneratedAssets(
        video_path=str(video_path),
        thumbnail_path=str(thumb_path),
        duration_seconds=float(duration),
    )
