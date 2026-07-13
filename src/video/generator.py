"""Generate a 1080x1920 vertical Short:

- Background = blurred Ken-Burns-zoomed source image (or solid color fallback).
- Overlay = bold on-screen text chunks rotating with the narration.
- Audio = narration of the script_voiceover (pt-BR), provider-selectable
  (ElevenLabs premium or gTTS fallback - see src/video/tts.py).

Designed to run in a stock Python container without GPU. Requires `ffmpeg`
available on PATH.
"""
from __future__ import annotations

import logging
import math
import re
import subprocess
import tempfile
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from moviepy.editor import (
    AudioFileClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
)

from ..config import settings
from ..models import GeneratedAssets, NewsItem, RewrittenPost
from .tts import get_tts_provider

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
    provider = get_tts_provider()
    log.info("TTS provider: %s", provider.name)
    return provider.synthesize(text, dest, lang=lang)


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


_MEAN_VOL_RE = re.compile(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB")


def _mean_volume_db(path: str) -> float | None:
    """Average (RMS) level of an audio file in dBFS, via ffmpeg volumedetect.

    Returns None if ffmpeg fails or the value can't be parsed. Used as a
    loudness proxy to level the music bed relative to the narration without
    moviepy's to_soundarray (which breaks on newer numpy).
    """
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", path,
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        log.warning("volumedetect failed for %s: %s", path, exc)
        return None
    match = _MEAN_VOL_RE.search(proc.stderr or "")
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
    # Loop the bed to cover the full narration instead of truncating the video
    # (the track is a short loop; a longer voiceover must not cut the Short).
    if music.duration < duration:
        from moviepy.audio.fx.audio_loop import audio_loop

        music = audio_loop(music, duration=duration)
    music = music.subclip(0, duration).set_duration(duration)

    # Level the bed RELATIVE TO THE VOICE: target N dB below the narration, so
    # the mix is consistent regardless of how hot the TTS or the track is.
    voice_path = voice_path or getattr(voice, "filename", None)
    voice_db = _mean_volume_db(voice_path) if voice_path else None
    music_db = _mean_volume_db(str(music_path))
    if voice_db is not None and music_db is not None:
        gain_db = (voice_db - music_db) + settings.background_music_db_under_voice
        gain = (10 ** (gain_db / 20.0)) * trim
    else:
        # Fallback: honor BACKGROUND_MUSIC_VOLUME directly when RMS probing fails.
        gain = trim
        log.warning("Could not measure levels; using fallback music gain %.3f", gain)
    music = music.volumex(gain)
    log.info(
        "Background music: %s -> %.1f dB under voice (gain=%.3f, voice=%s dB, music=%s dB)",
        music_path.name,
        settings.background_music_db_under_voice,
        gain,
        voice_db,
        music_db,
    )
    return CompositeAudioClip([music, voice]).set_duration(duration)


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
        # Stay strictly within the audio file: moviepy 1.x raises IOError if
        # the composite duration runs even a hair past the actual audio frames.
        # We trim 0.05s off the reported duration as a safety margin against
        # mp3 frame-boundary off-by-ones.
        safe_audio_duration = max(0.5, audio.duration - 0.05)
        audio = audio.set_duration(safe_audio_duration)
        duration = max(8.0, min(60.0, safe_audio_duration))
        audio = _mix_voice_with_background(audio, duration, voice_path=str(audio_path))

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

        # Thumbnail = first frame (RGBA->RGB for JPEG compat).
        thumb_path = base / "thumb.jpg"
        frame = composite.get_frame(0.3)
        thumb_img = Image.fromarray(frame)
        if thumb_img.mode != "RGB":
            thumb_img = thumb_img.convert("RGB")
        thumb_img.save(str(thumb_path), "JPEG", quality=88)

    return GeneratedAssets(
        video_path=str(video_path),
        thumbnail_path=str(thumb_path),
        duration_seconds=float(duration),
    )
