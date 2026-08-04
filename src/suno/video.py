"""Render a full-length 16:9 LOOXX music video from Suno audio and cover art."""
from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .playlist import SunoTrack

log = logging.getLogger(__name__)

WIDTH = 1920
HEIGHT = 1080
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]


@dataclass(frozen=True)
class RenderedTrack:
    video_path: Path
    poster_path: Path
    audio_path: Path


def _download(url: str, destination: Path) -> Path:
    if not url.startswith("https://"):
        raise ValueError(f"Refusing non-HTTPS media URL: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with destination.open("wb") as output:
                for chunk in response.iter_bytes():
                    output.write(chunk)
    if destination.stat().st_size == 0:
        raise ValueError(f"Downloaded empty media file: {url}")
    return destination


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _cover_fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGB"), size, method=Image.Resampling.LANCZOS)


def _poster(cover_path: Path, destination: Path, title: str) -> Path:
    cover = Image.open(cover_path).convert("RGB")
    background = _cover_fit(cover, (WIDTH, HEIGHT)).filter(
        ImageFilter.GaussianBlur(radius=42)
    )
    dim = Image.new("RGBA", (WIDTH, HEIGHT), (3, 7, 10, 145))
    canvas = Image.alpha_composite(background.convert("RGBA"), dim)

    card_size = 760
    card = _cover_fit(cover, (card_size, card_size))
    shadow = Image.new("RGBA", (card_size + 60, card_size + 60), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (25, 25, card_size + 35, card_size + 35),
        radius=24,
        fill=(0, 0, 0, 185),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
    card_x = 150
    card_y = (HEIGHT - card_size) // 2
    canvas.alpha_composite(shadow, (card_x - 30, card_y - 30))
    canvas.paste(card, (card_x, card_y))

    draw = ImageDraw.Draw(canvas)
    brand_font = _font(82)
    label_font = _font(30)
    title_font = _font(66)
    text_x = 1040
    draw.text((text_x, 265), "LOOXX", font=brand_font, fill=(240, 245, 241, 255))
    draw.rectangle((text_x, 370, text_x + 120, 377), fill=(78, 231, 202, 255))
    draw.text(
        (text_x, 405),
        "NEW RELEASE  /  70s RADIO",
        font=label_font,
        fill=(137, 242, 221, 255),
    )

    words = title.split()
    lines: list[str] = []
    current = ""
    max_width = WIDTH - text_x - 110
    for word in words:
        trial = f"{current} {word}".strip()
        box = draw.textbbox((0, 0), trial, font=title_font)
        if current and box[2] - box[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    draw.multiline_text(
        (text_x, 505),
        "\n".join(lines[:4]),
        font=title_font,
        fill=(255, 255, 255, 255),
        spacing=20,
    )
    draw.text(
        (text_x, 885),
        "OFFICIAL AUDIO  •  TABUU",
        font=label_font,
        fill=(205, 214, 211, 255),
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(destination, "JPEG", quality=94, optimize=True)
    return destination


def _render_video(poster: Path, audio: Path, destination: Path) -> Path:
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-loop",
        "1",
        "-framerate",
        "1",
        "-i",
        str(poster),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-tune",
        "stillimage",
        "-r",
        "30",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "320k",
        "-ar",
        "48000",
        "-shortest",
        "-movflags",
        "+faststart",
        str(destination),
    ]
    log.info("Rendering full-length music video: %s", destination)
    subprocess.run(command, check=True, timeout=1200)
    if not destination.exists() or destination.stat().st_size == 0:
        raise RuntimeError("ffmpeg did not create a video")
    return destination


def render_track(track: SunoTrack, output_dir: Path) -> RenderedTrack:
    track_dir = output_dir / track.song_id
    track_dir.mkdir(parents=True, exist_ok=True)
    audio = _download(track.audio_url, track_dir / "track.mp3")
    cover = _download(track.image_url, track_dir / "cover.jpg")
    poster = _poster(cover, track_dir / "poster.jpg", track.title)
    video = _render_video(poster, audio, track_dir / "looxx_track.mp4")
    return RenderedTrack(video_path=video, poster_path=poster, audio_path=audio)
