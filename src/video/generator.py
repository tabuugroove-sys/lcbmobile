"""Render a cinematic, source-traceable vertical music-news Short."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont
from moviepy.editor import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    VideoFileClip,
    concatenate_videoclips,
)

from ..config import settings
from ..editorial import find_known_music_act
from ..models import GeneratedAssets, NewsItem, RewrittenPost
from .commons_media import LicensedImage, fetch_licensed_artist_images
from .commons_video import LicensedVideo, fetch_licensed_artist_videos
from .tts import get_tts_provider

log = logging.getLogger(__name__)

WIDTH, HEIGHT = 1080, 1920
ACCENTS = ("#ff335c", "#ffd34d", "#29d3ff")
DEFAULT_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
CONDENSED_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialnb.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf",
]
MEAN_VOL_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _find_font(candidates: list[str]) -> str | None:
    return next((path for path in candidates if Path(path).exists()), None)


def _font(path: str | None, size: int) -> ImageFont.ImageFont:
    if path:
        return ImageFont.truetype(path, size=size)
    return ImageFont.load_default(size=size)


def _tts(text: str, lang: str, dest: Path) -> Path:
    provider = get_tts_provider()
    log.info("TTS provider: %s", provider.name)
    return provider.synthesize(text, dest, lang=lang)


def _mean_volume_db(path: str) -> float | None:
    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostats",
                "-i",
                path,
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        log.warning("volumedetect failed for %s: %s", path, exc)
        return None
    match = MEAN_VOL_RE.search(proc.stderr or "")
    return float(match.group(1)) if match else None


def _mix_voice_with_background(
    voice: AudioFileClip, duration: float, voice_path: str | None = None
) -> CompositeAudioClip | AudioFileClip:
    music_path = settings.background_music_path
    trim = max(0.0, settings.background_music_volume)
    if trim <= 0 or not music_path.exists():
        if trim > 0:
            log.warning("Background music not found: %s", music_path)
        return voice

    music = AudioFileClip(str(music_path))
    if music.duration < duration:
        from moviepy.audio.fx.audio_loop import audio_loop

        music = audio_loop(music, duration=duration)
    music = music.subclip(0, duration).set_duration(duration)
    voice_path = voice_path or getattr(voice, "filename", None)
    voice_db = _mean_volume_db(voice_path) if voice_path else None
    music_db = _mean_volume_db(str(music_path))
    if voice_db is not None and music_db is not None:
        gain_db = (voice_db - music_db) + settings.background_music_db_under_voice
        gain = (10 ** (gain_db / 20.0)) * trim
    else:
        gain = trim
        log.warning("Could not measure levels; using fallback music gain %.3f", gain)
    music = music.volumex(gain)
    log.info(
        "Background music: %s -> %.1f dB under voice (gain=%.3f)",
        music_path.name,
        settings.background_music_db_under_voice,
        gain,
    )
    return CompositeAudioClip([music, voice]).set_duration(duration)


def _fit_cover(image: Image.Image, size: tuple[int, int], focus_y: float = 0.5) -> Image.Image:
    image = image.convert("RGB")
    ratio = max(size[0] / image.width, size[1] / image.height)
    resized = image.resize(
        (round(image.width * ratio), round(image.height * ratio)),
        Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - size[0]) // 2)
    top = round(max(0, resized.height - size[1]) * max(0.0, min(1.0, focus_y)))
    return resized.crop((left, top, left + size[0], top + size[1]))


def _gradient(accent: str) -> Image.Image:
    rgb = tuple(int(accent[index : index + 2], 16) for index in (1, 3, 5))
    array = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for y in range(HEIGHT):
        factor = y / (HEIGHT - 1)
        array[y, :, 0] = int(12 + rgb[0] * 0.22 * (1 - factor))
        array[y, :, 1] = int(9 + rgb[1] * 0.12 * (1 - factor))
        array[y, :, 2] = int(20 + rgb[2] * 0.18 * (1 - factor))
    return Image.fromarray(array, "RGB").convert("RGBA")


def _add_filmstrip(image: Image.Image, accent: str) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    color = tuple(int(accent[index : index + 2], 16) for index in (1, 3, 5)) + (38,)
    for x in (-270, 830):
        draw.rounded_rectangle((x, -140, x + 410, 2070), 24, outline=color, width=25)
        for y in range(-100, 2020, 145):
            draw.rounded_rectangle((x + 18, y, x + 82, y + 98), 10, fill=color)
            draw.rounded_rectangle((x + 328, y, x + 392, y + 98), 10, fill=color)


def _wrap_text(
    text: str, draw: ImageDraw.ImageDraw, font: ImageFont.ImageFont, max_width: int
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and draw.textbbox((0, 0), candidate, font=font)[2] > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _fit_headline_font(
    lines: list[str], draw: ImageDraw.ImageDraw, font_path: str | None, max_width: int
) -> ImageFont.ImageFont:
    size = 86
    font = _font(font_path, size)
    while max(draw.textbbox((0, 0), line, font=font)[2] for line in lines) > max_width and size > 38:
        size -= 3
        font = _font(font_path, size)
    return font


def _headline_lines(text: str) -> list[str]:
    words = text.split()
    if len(words) <= 4:
        return [text]
    line_count = 2 if len(words) <= 9 else 3
    lines = []
    for index in range(line_count):
        start = round(index * len(words) / line_count)
        end = round((index + 1) * len(words) / line_count)
        lines.append(" ".join(words[start:end]))
    return lines


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    *,
    fill: str = "white",
    stroke: int = 4,
) -> None:
    draw.text(
        xy,
        text,
        font=font,
        fill=fill,
        anchor="mm",
        align="center",
        stroke_width=stroke,
        stroke_fill="#100b13",
    )


def _try_cutout(source: Path, target: Path) -> Image.Image | None:
    """Create a foreground alpha; return None when the mask is not credible."""
    try:
        import cv2
    except ImportError:
        log.warning("OpenCV unavailable; using framed-photo layouts only")
        return None
    bgr = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    height, width = bgr.shape[:2]
    if height < width * 1.2:
        log.info("Cutout skipped: source is not a portrait")
        return None
    border = np.concatenate(
        [
            bgr[: max(4, height // 40), :, :].reshape(-1, 3),
            bgr[-max(4, height // 40) :, :, :].reshape(-1, 3),
            bgr[:, : max(4, width // 40), :].reshape(-1, 3),
            bgr[:, -max(4, width // 40) :, :].reshape(-1, 3),
        ]
    )
    if float(border.std(axis=0).mean()) > 58.0:
        log.info("Cutout skipped: border is too visually complex")
        return None
    mask = np.zeros((height, width), np.uint8)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    margin_x = max(8, round(width * 0.025))
    margin_y = max(8, round(height * 0.012))
    rectangle = (margin_x, margin_y, width - 2 * margin_x, height - 2 * margin_y)
    try:
        cv2.grabCut(
            bgr,
            mask,
            rectangle,
            background,
            foreground,
            7,
            cv2.GC_INIT_WITH_RECT,
        )
    except cv2.error:
        return None
    alpha = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    foreground_ratio = float(np.count_nonzero(alpha)) / float(alpha.size)
    if not 0.10 <= foreground_ratio <= 0.82:
        log.warning("Cutout rejected: implausible foreground ratio %.3f", foreground_ratio)
        return None
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.7)
    rgba = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA)
    rgba[:, :, 3] = alpha
    result = Image.fromarray(rgba)
    if bbox := result.getbbox():
        result = result.crop(bbox)
    result.save(target)
    return result


def _subtitle_chunks(text: str, count: int) -> list[str]:
    sentences = [part.strip() for part in SENTENCE_RE.split(text) if part.strip()]
    if len(sentences) >= count:
        chunks = sentences[: count - 1]
        chunks.append(" ".join(sentences[count - 1 :]))
        return chunks
    words = text.split()
    chunks = []
    for index in range(count):
        start = round(index * len(words) / count)
        end = round((index + 1) * len(words) / count)
        chunks.append(" ".join(words[start:end]))
    return chunks


def _headline_chunks(post: RewrittenPost, count: int) -> list[str]:
    source = [*post.on_screen_text, post.headline]
    clean: list[str] = []
    for value in source:
        value = re.sub(r"\s+", " ", value or "").strip()
        if value and value.casefold() not in {item.casefold() for item in clean}:
            clean.append(value)
    if not clean:
        clean = ["NOTÍCIA DA MÚSICA"]
    return [clean[index % len(clean)] for index in range(count)]


def _creator_credit(media: list[LicensedImage]) -> str:
    creators: list[str] = []
    for asset in media:
        creator = re.sub(r"\s+", " ", asset.creator).strip()
        if creator and creator.casefold() not in {item.casefold() for item in creators}:
            creators.append(creator)
    joined = " • ".join(creators[:4])
    return f"FOTOS: {joined} / CC BY" if joined else ""


def _video_creator_credit(media: LicensedVideo) -> str:
    creator = re.sub(r"\s+", " ", media.creator).strip()
    return f"VÍDEO: {creator} / {media.license}".upper()


def _make_video_overlay(
    *,
    index: int,
    count: int,
    headline: str,
    subtitle: str,
    source_name: str,
    credits: str,
    output: Path,
) -> Path:
    """Render transparent editorial chrome around a live video window."""
    accent = ACCENTS[index % len(ACCENTS)]
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")
    bold_path = _find_font(DEFAULT_FONT_CANDIDATES)
    narrow_path = _find_font(CONDENSED_FONT_CANDIDATES) or bold_path

    draw.rectangle((0, 0, WIDTH, 472), fill=(5, 5, 9, 212))
    draw.rounded_rectangle(
        (60, 54, 392, 118), 20, fill=(10, 9, 14, 238), outline=accent, width=3
    )
    draw.text(
        (80, 86),
        "MÚSICA  •  AGORA",
        font=_font(bold_path, 27),
        fill="white",
        anchor="lm",
    )
    draw.rounded_rectangle((746, 54, 1020, 118), 20, fill=(10, 9, 14, 238))
    draw.text(
        (883, 86),
        "VÍDEO DE ARQUIVO",
        font=_font(bold_path, 19),
        fill=(232, 232, 232),
        anchor="mm",
    )

    headline_lines = _headline_lines(headline.upper())
    headline_font = _fit_headline_font(headline_lines, draw, narrow_path, 930)
    line_height = getattr(headline_font, "size", 60) + 8
    title_y = 245 - (len(headline_lines) - 1) * line_height // 2
    for line_no, line in enumerate(headline_lines[:3]):
        _draw_centered(
            draw,
            (WIDTH // 2, title_y + line_no * line_height),
            line,
            headline_font,
            stroke=6,
        )

    subtitle_font = _font(bold_path, 42)
    subtitle_lines = _wrap_text(subtitle, draw, subtitle_font, 900)
    while len(subtitle_lines) > 3 and getattr(subtitle_font, "size", 34) > 34:
        subtitle_font = _font(bold_path, getattr(subtitle_font, "size", 37) - 2)
        subtitle_lines = _wrap_text(subtitle, draw, subtitle_font, 900)
    sub_size = getattr(subtitle_font, "size", 40)
    box_height = 58 + len(subtitle_lines) * (sub_size + 12)
    box_top = 1585 - box_height // 2
    draw.rounded_rectangle(
        (60, box_top, 1020, box_top + box_height),
        22,
        fill=(5, 5, 8, 232),
        outline=(255, 255, 255, 70),
        width=2,
    )
    for line_no, line in enumerate(subtitle_lines):
        _draw_centered(
            draw,
            (WIDTH // 2, box_top + 46 + line_no * (sub_size + 12)),
            line,
            subtitle_font,
            stroke=2,
        )

    credit_font = _font(bold_path, 18)
    credit_lines = _wrap_text(credits, draw, credit_font, 900)
    for line_no, line in enumerate(credit_lines[:2]):
        _draw_centered(
            draw,
            (WIDTH // 2, 1772 + line_no * 26),
            line,
            credit_font,
            fill="#dedede",
            stroke=1,
        )

    draw.rectangle((0, 1888, WIDTH, HEIGHT), fill=(6, 5, 10, 242))
    draw.rectangle((0, 1888, round(WIDTH * (index + 1) / count), 1902), fill=accent)
    source_label = re.sub(r"\s+", " ", source_name).strip().upper()[:48]
    draw.text(
        (60, 1911),
        f"FONTE DA NOTÍCIA: {source_label}",
        font=_font(bold_path, 22),
        fill=(230, 230, 230),
        anchor="ls",
    )
    draw.text(
        (1020, 1911),
        f"{index + 1:02d}/{count:02d}",
        font=_font(bold_path, 22),
        fill=(230, 230, 230),
        anchor="rs",
    )
    canvas.save(output, "PNG")
    return output


def _build_video_scene(
    *,
    media: LicensedVideo,
    overlay_path: Path,
    duration: float,
) -> tuple[CompositeVideoClip, VideoFileClip]:
    """Present archive footage as a square editorial crop inside the Short."""
    source = VideoFileClip(media.path, audio=False)
    latest_start = max(0.0, source.duration - duration - 0.1)
    start = min(max(0.0, media.seek_seconds), latest_start)
    segment = source.subclip(start, min(source.duration, start + duration))
    segment = segment.set_duration(duration)

    background_scale = max(WIDTH / segment.w, HEIGHT / segment.h)
    background = (
        segment.resize(background_scale)
        .crop(
            x_center=segment.w * background_scale / 2,
            y_center=segment.h * background_scale / 2,
            width=WIDTH,
            height=HEIGHT,
        )
        .set_opacity(0.38)
    )
    crop_size = min(segment.w, segment.h)
    square = segment.crop(
        x_center=segment.w / 2,
        y_center=segment.h / 2,
        width=crop_size,
        height=crop_size,
    )
    foreground = square.resize((960, 960)).set_position(("center", 500))
    frame = (
        ColorClip((976, 976), color=(238, 238, 238))
        .set_opacity(0.82)
        .set_duration(duration)
        .set_position(("center", 492))
    )
    matte = ColorClip((WIDTH, HEIGHT), color=(4, 4, 8)).set_duration(duration)
    shade = (
        ColorClip((WIDTH, HEIGHT), color=(0, 0, 0))
        .set_opacity(0.24)
        .set_duration(duration)
    )
    overlay = ImageClip(str(overlay_path), transparent=True).set_duration(duration)
    clip = CompositeVideoClip(
        [matte, background, shade, frame, foreground, overlay], size=(WIDTH, HEIGHT)
    ).set_duration(duration)
    return clip, source


def _make_scene(
    *,
    index: int,
    count: int,
    headline: str,
    subtitle: str,
    source_name: str,
    media: LicensedImage | None,
    cutout: Image.Image | None,
    credits: str,
    output: Path,
) -> Path:
    accent = ACCENTS[index % len(ACCENTS)]
    canvas = _gradient(accent)
    _add_filmstrip(canvas, accent)
    draw = ImageDraw.Draw(canvas, "RGBA")

    source_image: Image.Image | None = None
    if media:
        try:
            source_image = Image.open(media.path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            log.warning("Cannot open licensed media %s: %s", media.path, exc)

    if source_image:
        background = _fit_cover(source_image, (WIDTH, HEIGHT), 0.4)
        background = ImageEnhance.Color(background).enhance(0.50)
        background = background.filter(ImageFilter.GaussianBlur(24)).convert("RGBA")
        background.putalpha(105)
        canvas.alpha_composite(background)
    draw.rectangle((0, 0, WIDTH, HEIGHT), fill=(4, 4, 9, 62))

    layout = "cutout" if cutout is not None and index == 1 else ("card" if index % 2 else "full")
    if layout == "cutout" and cutout is not None:
        person = cutout.copy()
        target_height = 1330
        ratio = target_height / person.height
        person = person.resize(
            (round(person.width * ratio), target_height), Image.Resampling.LANCZOS
        )
        if person.width > 1000:
            ratio = 1000 / person.width
            person = person.resize(
                (1000, round(person.height * ratio)), Image.Resampling.LANCZOS
            )
        alpha = person.getchannel("A")
        shadow = Image.new("RGBA", person.size, (0, 0, 0, 190))
        shadow.putalpha(alpha.filter(ImageFilter.GaussianBlur(14)))
        x = WIDTH - person.width + 70
        y = 270
        canvas.alpha_composite(shadow, (x + 20, y + 28))
        canvas.alpha_composite(person, (x, y))
    elif source_image and layout == "card":
        picture = _fit_cover(source_image, (760, 1050), 0.34)
        card = Image.new("RGBA", (820, 1110), (248, 246, 242, 255))
        card.alpha_composite(picture.convert("RGBA"), (30, 30))
        card = card.rotate(
            -2.0 if index % 4 == 1 else 2.0,
            expand=True,
            resample=Image.Resampling.BICUBIC,
        )
        shadow = Image.new("RGBA", card.size, (0, 0, 0, 170)).filter(
            ImageFilter.GaussianBlur(18)
        )
        canvas.alpha_composite(shadow, ((WIDTH - card.width) // 2 + 20, 330))
        canvas.alpha_composite(card, ((WIDTH - card.width) // 2, 300))
    elif source_image:
        picture = _fit_cover(source_image, (860, 1180), 0.34)
        x, y = 110, 245
        shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (x + 20, y + 28, x + 880, y + 1208), 22, fill=(0, 0, 0, 150)
        )
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(20)))
        canvas.alpha_composite(picture.convert("RGBA"), (x, y))
        draw.rounded_rectangle(
            (x, y, x + 860, y + 1180), 18, outline=(255, 255, 255, 185), width=5
        )
    else:
        draw.ellipse((180, 310, 900, 1030), outline=accent, width=18)
        draw.ellipse((250, 380, 830, 960), outline=(255, 255, 255, 34), width=3)

    bold_path = _find_font(DEFAULT_FONT_CANDIDATES)
    narrow_path = _find_font(CONDENSED_FONT_CANDIDATES) or bold_path
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.rounded_rectangle(
        (60, 66, 392, 130), 20, fill=(10, 9, 14, 225), outline=accent, width=3
    )
    draw.text(
        (80, 98),
        "MÚSICA  •  AGORA",
        font=_font(bold_path, 27),
        fill="white",
        anchor="lm",
    )
    badge = "FOTOS DE ARQUIVO" if source_image else "ARTE EDITORIAL"
    draw.rounded_rectangle((760, 66, 1020, 130), 20, fill=(10, 9, 14, 225))
    draw.text(
        (890, 98),
        badge,
        font=_font(bold_path, 20),
        fill=(232, 232, 232),
        anchor="mm",
    )

    headline = headline.upper()
    headline_lines = _headline_lines(headline)
    headline_font = _fit_headline_font(headline_lines, draw, narrow_path, 930)
    line_height = getattr(headline_font, "size", 60) + 10
    title_y = 820 - (len(headline_lines) - 1) * line_height // 2
    for line_no, line in enumerate(headline_lines[:3]):
        _draw_centered(
            draw,
            (WIDTH // 2, title_y + line_no * line_height),
            line,
            headline_font,
            stroke=6,
        )

    subtitle_font = _font(bold_path, 42)
    subtitle_lines = _wrap_text(subtitle, draw, subtitle_font, 900)
    while len(subtitle_lines) > 3 and getattr(subtitle_font, "size", 34) > 34:
        subtitle_font = _font(bold_path, getattr(subtitle_font, "size", 37) - 2)
        subtitle_lines = _wrap_text(subtitle, draw, subtitle_font, 900)
    sub_size = getattr(subtitle_font, "size", 40)
    box_height = 50 + len(subtitle_lines) * (sub_size + 12)
    box_top = 1645 - box_height // 2
    draw.rounded_rectangle(
        (60, box_top, 1020, box_top + box_height),
        22,
        fill=(5, 5, 8, 224),
        outline=(255, 255, 255, 55),
        width=2,
    )
    for line_no, line in enumerate(subtitle_lines):
        _draw_centered(
            draw,
            (WIDTH // 2, box_top + 42 + line_no * (sub_size + 12)),
            line,
            subtitle_font,
            stroke=2,
        )

    if index == count - 1 and credits:
        credit_font = _font(bold_path, 19)
        credit_lines = _wrap_text(credits.upper(), draw, credit_font, 900)
        for line_no, line in enumerate(credit_lines[:2]):
            _draw_centered(
                draw,
                (WIDTH // 2, 1780 + line_no * 29),
                line,
                credit_font,
                fill="#dedede",
                stroke=1,
            )

    draw.rectangle((0, 1888, WIDTH, HEIGHT), fill=(6, 5, 10, 238))
    draw.rectangle((0, 1888, round(WIDTH * (index + 1) / count), 1902), fill=accent)
    source_label = re.sub(r"\s+", " ", source_name).strip().upper()[:48]
    draw.text(
        (60, 1911),
        f"FONTE DA NOTÍCIA: {source_label}",
        font=_font(bold_path, 22),
        fill=(230, 230, 230),
        anchor="ls",
    )
    draw.text(
        (1020, 1911),
        f"{index + 1:02d}/{count:02d}",
        font=_font(bold_path, 22),
        fill=(230, 230, 230),
        anchor="rs",
    )
    canvas.convert("RGB").save(output, "JPEG", quality=92)
    return output


def _make_hook_scene(
    *,
    item: NewsItem,
    media: list[LicensedImage],
    credits: str,
    output: Path,
) -> Path:
    """Create a truthful curiosity-first opening frame and thumbnail."""
    if not media:
        return _make_scene(
            index=0,
            count=5,
            headline="O QUE ACONTECEU?",
            subtitle="ENTENDA O CASO",
            source_name=item.source_name,
            media=None,
            cutout=None,
            credits=credits,
            output=output,
        )

    images: list[Image.Image] = []
    for asset in media[:2]:
        try:
            images.append(Image.open(asset.path).convert("RGB"))
        except Exception as exc:  # noqa: BLE001
            log.warning("Cannot open hook media %s: %s", asset.path, exc)
    if not images:
        return _make_scene(
            index=0,
            count=5,
            headline="O QUE ACONTECEU?",
            subtitle="ENTENDA O CASO",
            source_name=item.source_name,
            media=None,
            cutout=None,
            credits=credits,
            output=output,
        )
    if len(images) == 1:
        images.append(images[0].copy())

    canvas = _fit_cover(images[0], (WIDTH, HEIGHT), 0.35).filter(
        ImageFilter.GaussianBlur(30)
    ).convert("RGBA")
    canvas = ImageEnhance.Brightness(canvas).enhance(0.42)
    draw = ImageDraw.Draw(canvas, "RGBA")
    bold_path = _find_font(DEFAULT_FONT_CANDIDATES)
    narrow_path = _find_font(CONDENSED_FONT_CANDIDATES) or bold_path

    card_x, card_y, card_w, card_h = 54, 300, 972, 1080
    draw.rounded_rectangle(
        (card_x - 8, card_y - 8, card_x + card_w + 8, card_y + card_h + 8),
        26,
        fill=(0, 0, 0, 155),
        outline=(255, 255, 255, 100),
        width=3,
    )
    left = _fit_cover(images[0], (card_w // 2, card_h), 0.30)
    right = _fit_cover(images[1], (card_w - card_w // 2, card_h), 0.30)
    canvas.alpha_composite(left.convert("RGBA"), (card_x, card_y))
    canvas.alpha_composite(right.convert("RGBA"), (card_x + card_w // 2, card_y))
    shade = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle(
        (card_x, card_y, card_x + card_w, card_y + card_h),
        fill=(0, 0, 0, 28),
    )
    canvas.alpha_composite(shade)
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.line(
        (WIDTH // 2, card_y, WIDTH // 2, card_y + card_h),
        fill=(255, 255, 255, 150),
        width=5,
    )

    artist = find_known_music_act(item.title)
    label = (artist or "MÚSICA AGORA").upper()
    draw.rounded_rectangle((60, 55, 1020, 150), 24, fill=(5, 5, 9, 225))
    _draw_centered(
        draw,
        (WIDTH // 2, 103),
        label,
        _font(bold_path, 43 if len(label) < 18 else 34),
        stroke=3,
    )

    radius = 145
    center = (WIDTH // 2, 855)
    draw.ellipse(
        (
            center[0] - radius,
            center[1] - radius,
            center[0] + radius,
            center[1] + radius,
        ),
        fill=(10, 10, 14, 242),
        outline=(255, 51, 92, 255),
        width=10,
    )
    _draw_centered(
        draw,
        center,
        "?",
        _font(narrow_path, 238),
        fill="#ffffff",
        stroke=5,
    )

    draw.rounded_rectangle(
        (72, 1430, 1008, 1698),
        28,
        fill=(5, 5, 9, 236),
        outline=(255, 51, 92, 220),
        width=5,
    )
    _draw_centered(
        draw,
        (WIDTH // 2, 1518),
        "O QUE ACONTECEU?",
        _font(narrow_path, 74),
        stroke=6,
    )
    _draw_centered(
        draw,
        (WIDTH // 2, 1632),
        "ENTENDA O CASO",
        _font(bold_path, 37),
        fill="#ffd34d",
        stroke=3,
    )

    source_label = re.sub(r"\s+", " ", item.source_name).strip().upper()[:48]
    draw.rectangle((0, 1888, WIDTH, HEIGHT), fill=(6, 5, 10, 242))
    draw.rectangle((0, 1888, round(WIDTH / 5), 1902), fill="#ff335c")
    draw.text(
        (60, 1911),
        f"FONTE DA NOTÍCIA: {source_label}",
        font=_font(bold_path, 22),
        fill=(230, 230, 230),
        anchor="ls",
    )
    canvas.convert("RGB").save(output, "JPEG", quality=93)
    return output


def _build_scene_images(
    item: NewsItem,
    post: RewrittenPost,
    media: list[LicensedImage],
    output_dir: Path,
) -> list[Path]:
    # Mixed-media Shorts have exactly two video beats and three photo beats.
    # Keeping five scenes prevents a third video slot from repeating one of the
    # two curated source files merely because Commons returned six photographs.
    scene_count = 5 if settings.require_video_media else min(7, max(5, len(media)))
    subtitles = _subtitle_chunks(post.script_voiceover, scene_count)
    headlines = _headline_chunks(post, scene_count)
    cutout = None
    auto_cutout = os.getenv("AUTO_CUTOUT_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if auto_cutout:
        for asset in sorted(
            media, key=lambda row: row.height / max(row.width, 1), reverse=True
        ):
            cutout = _try_cutout(Path(asset.path), output_dir / "subject-cutout.png")
            if cutout is not None:
                break
    credits = _creator_credit(media)
    scenes = []
    for index in range(scene_count):
        if index == 0:
            scenes.append(
                _make_hook_scene(
                    item=item,
                    media=media,
                    credits=credits,
                    output=output_dir / "scene-01.jpg",
                )
            )
            continue
        asset = media[index % len(media)] if media else None
        scenes.append(
            _make_scene(
                index=index,
                count=scene_count,
                headline=headlines[index],
                subtitle=subtitles[index],
                source_name=item.source_name,
                media=asset,
                cutout=cutout,
                credits=credits,
                output=output_dir / f"scene-{index + 1:02d}.jpg",
            )
        )
    return scenes


def _write_render_manifest(
    *,
    base: Path,
    item: NewsItem,
    artist_query: str | None,
    photos: list[LicensedImage],
    videos: list[LicensedVideo],
    scenes: list[Path],
    duration: float,
) -> None:
    (base / "render_manifest.json").write_text(
        json.dumps(
            {
                "style": "cinematic_mixed_media_v3_curiosity_hook",
                "language": settings.content_lang,
                "source_url": item.url,
                "artist_query": artist_query,
                "licensed_photo_count": len(photos),
                "licensed_video_count": len(videos),
                "rights_status": "verified" if photos and videos else "incomplete",
                "scene_count": len(scenes),
                "duration_seconds": round(duration, 3),
                "auto_publish_decision": "owned_by_pipeline_not_renderer",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def _write_media_credits(
    base: Path,
    photos: list[LicensedImage],
    videos: list[LicensedVideo],
) -> None:
    lines = [
        "CRÉDITOS DE MÍDIA",
        "Trechos editados, redimensionados e legendados por LCB Mobile.",
    ]
    for asset in videos:
        lines.extend(
            [
                f"Vídeo: {asset.title}",
                f"Autor: {asset.creator}",
                f"Licença: {asset.license} - {asset.license_url}",
                f"Origem: {asset.source_page}",
            ]
        )
    for asset in photos:
        lines.extend(
            [
                f"Foto: {asset.title}",
                f"Autor: {asset.creator}",
                f"Licença: {asset.license} - {asset.license_url}",
                f"Origem: {asset.source_page}",
            ]
        )
    (base / "media_credits.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _item_output_dir(item: NewsItem, output_dir: Path) -> Path:
    base = output_dir / item.fingerprint().replace("/", "_").replace(":", "_")[-80:]
    base.mkdir(parents=True, exist_ok=True)
    return base


def resolve_visual_media(
    item: NewsItem,
    output_dir: Path,
) -> tuple[str | None, list[LicensedImage], list[LicensedVideo]]:
    """Resolve reusable artist visuals into the item's persistent render cache."""
    base = _item_output_dir(item, output_dir)
    # The artist must be the explicit subject of the headline. A name buried in
    # a festival roundup cannot safely determine the visuals for the whole story.
    artist_query = find_known_music_act(item.title)
    photos = fetch_licensed_artist_images(
        artist_query,
        base / "licensed_media",
        limit=max(6, settings.min_visual_media_assets),
    )
    videos = fetch_licensed_artist_videos(
        artist_query,
        base / "licensed_video",
        limit=max(2, settings.min_video_media_assets),
    )
    return artist_query, photos, videos


def visual_media_ready(
    item: NewsItem,
    output_dir: Path,
    *,
    enforce_requirements: bool = True,
) -> bool:
    """Return whether the story can reproduce the approved visual reference."""
    if not enforce_requirements:
        return True
    if not settings.require_visual_media and not settings.require_video_media:
        return True
    artist_query, photos, videos = resolve_visual_media(item, output_dir)
    photo_ready = (
        not settings.require_visual_media
        or len(photos) >= settings.min_visual_media_assets
    )
    video_ready = (
        not settings.require_video_media
        or len(videos) >= settings.min_video_media_assets
    )
    ready = bool(artist_query) and photo_ready and video_ready
    if not ready:
        log.info(
            "Skipping visual-poor candidate: artist=%r photos=%d/%d videos=%d/%d title=%s",
            artist_query,
            len(photos),
            settings.min_visual_media_assets,
            len(videos),
            settings.min_video_media_assets if settings.require_video_media else 0,
            item.title,
        )
    return ready


def video_media_ready(item: NewsItem, output_dir: Path) -> bool:
    """Return whether the story has enough media for a real mixed-media cut."""
    artist_query, photos, videos = resolve_visual_media(item, output_dir)
    ready = bool(artist_query) and len(photos) >= 1 and len(videos) >= 1
    if not ready:
        log.info(
            "Skipping video-poor candidate: artist=%r photos=%d/1 videos=%d/1 title=%s",
            artist_query,
            len(photos),
            len(videos),
            item.title,
        )
    return ready


def build_short(
    item: NewsItem,
    post: RewrittenPost,
    output_dir: Path,
    *,
    lang: str = "pt-BR",
    enforce_media_requirements: bool = True,
) -> GeneratedAssets:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = _item_output_dir(item, output_dir)
    artist_query, photos, videos = resolve_visual_media(item, output_dir)
    if (
        enforce_media_requirements
        and settings.require_visual_media
        and len(photos) < settings.min_visual_media_assets
    ):
        raise RuntimeError(
            "Reference-style render blocked: "
            f"artist={artist_query!r} has {len(photos)} verified photo(s), "
            f"requires {settings.min_visual_media_assets}"
        )
    if (
        enforce_media_requirements
        and settings.require_video_media
        and len(videos) < settings.min_video_media_assets
    ):
        raise RuntimeError(
            "Mixed-media render blocked: "
            f"artist={artist_query!r} has {len(videos)} verified video(s), "
            f"requires {settings.min_video_media_assets}"
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        audio_path = _tts(post.script_voiceover, lang, base / "voice.mp3")
        voice = AudioFileClip(str(audio_path))
        safe_audio_duration = max(0.5, voice.duration - 0.05)
        duration = max(8.0, min(60.0, safe_audio_duration))
        if 29.9 <= duration < 30.0:
            duration = 30.0
        voice = voice.set_duration(duration)
        audio = _mix_voice_with_background(voice, duration, voice_path=str(audio_path))

        scene_paths = _build_scene_images(item, post, photos, base)
        hook_duration = min(2.2, max(1.2, duration * 0.08))
        content_scene_duration = (duration - hook_duration) / max(
            1, len(scene_paths) - 1
        )
        clips = []
        source_clips: list[VideoFileClip] = []
        subtitles = _subtitle_chunks(post.script_voiceover, len(scene_paths))
        headlines = _headline_chunks(post, len(scene_paths))
        for index, scene_path in enumerate(scene_paths):
            scene_duration = hook_duration if index == 0 else content_scene_duration
            if index % 2 == 1 and videos:
                video_asset = videos[(index // 2) % len(videos)]
                overlay_path = _make_video_overlay(
                    index=index,
                    count=len(scene_paths),
                    headline=headlines[index],
                    subtitle=subtitles[index],
                    source_name=item.source_name,
                    credits=_video_creator_credit(video_asset),
                    output=base / f"scene-{index + 1:02d}-video-overlay.png",
                )
                clip, source_clip = _build_video_scene(
                    media=video_asset,
                    overlay_path=overlay_path,
                    duration=scene_duration,
                )
                clips.append(clip)
                source_clips.append(source_clip)
                continue
            still = ImageClip(str(scene_path)).set_duration(scene_duration)
            direction = 1 if index % 2 else -1
            animated = still.resize(
                lambda time, d=scene_duration: 1.0
                + 0.025 * min(1.0, time / max(d, 0.1))
            ).set_position(
                lambda time, d=scene_duration, sign=direction: (
                    "center",
                    int(-8 + sign * 6 * math.sin(time / max(d, 0.1) * math.pi)),
                )
            )
            clips.append(
                CompositeVideoClip([animated], size=(WIDTH, HEIGHT)).set_duration(
                    scene_duration
                )
            )
        composite = concatenate_videoclips(clips, method="compose")
        composite = composite.set_audio(audio).set_duration(duration)

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
        thumb_path = base / "thumb.jpg"
        Image.open(scene_paths[0]).convert("RGB").save(thumb_path, "JPEG", quality=90)
        _write_render_manifest(
            base=base,
            item=item,
            artist_query=artist_query,
            photos=photos,
            videos=videos,
            scenes=scene_paths,
            duration=duration,
        )
        _write_media_credits(base, photos, videos)
        composite.close()
        for clip in clips:
            clip.close()
        for clip in source_clips:
            clip.close()

    return GeneratedAssets(
        video_path=str(video_path),
        thumbnail_path=str(thumb_path),
        duration_seconds=float(duration),
    )
