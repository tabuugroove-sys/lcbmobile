"""Mask-reveal typography for opt-in editorial cards, rendered without an NLE."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

SKIN_VERSION = "editorial-mask-3"
WIDTH, HEIGHT, FPS = 1920, 1080, 30
INK, WHITE, ACCENT = "#121316", "#f6f6f2", "#ef4564"
TEXT_BOX = (160, 300, 1760, 816)


def ease(value: float) -> float:
    return 1 - (1 - min(1, max(0, value))) ** 3


def layout(text: str, font_path: str) -> dict:
    """Fit whole words, including accented glyphs, into the fixed title safe area."""
    text = " ".join(text.split())
    if not text:
        raise ValueError("An editorial card needs text")
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    width, height = TEXT_BOX[2]-TEXT_BOX[0]-48, TEXT_BOX[3]-TEXT_BOX[1]
    for size in range(112, 31, -2):
        font = ImageFont.truetype(font_path, size)
        lines, line = [], ""
        for word in text.split():
            proposed = (line + " " + word).strip()
            if line and draw.textlength(proposed, font=font) > width:
                lines.append(line)
                line = word
            else:
                line = proposed
        lines.append(line)
        line_height = math.ceil(size * 1.34)
        if (len(lines)*line_height <= height
                and all(draw.textlength(line, font=font) <= width for line in lines)):
            # Balance neighbouring rows rather than leaving a single trailing word.
            for index in range(len(lines)-1, 0, -1):
                while len(lines[index-1].split()) > 1:
                    previous, word = lines[index-1].rsplit(" ", 1)
                    following = word + " " + lines[index]
                    old_gap = abs(draw.textlength(lines[index-1], font=font)-draw.textlength(lines[index], font=font))
                    new_gap = abs(draw.textlength(previous, font=font)-draw.textlength(following, font=font))
                    if draw.textlength(following, font=font) > width or new_gap >= old_gap:
                        break
                    lines[index-1], lines[index] = previous, following
            return {"lines": lines, "font": font, "line_height": line_height,
                    "top": TEXT_BOX[1] + (height-len(lines)*line_height)//2}
    raise ValueError("Editorial text is too long for a readable animated card")


class EditorialMotion:
    def __init__(self, story: dict, shot: dict):
        from .horizontal_news import font_file

        self.duration = float(shot.get("animation_duration", shot["duration"]))
        if not math.isfinite(self.duration) or self.duration <= 0:
            raise ValueError("Invalid editorial card duration")
        self.layout = layout(shot.get("animation_text", shot["text"]), font_file(True))
        self.base = Image.new("RGB", (WIDTH, HEIGHT), INK)
        draw = ImageDraw.Draw(self.base)
        small = ImageFont.truetype(font_file(), 27)
        label = ImageFont.truetype(font_file(True), 29)
        # The explicit editorial label prevents the graphic being mistaken for a source quote.
        draw.rectangle((0, 0, WIDTH, 92), fill=WHITE)
        draw.text((104, 29), "RADAR MUSICAL", font=label, fill=INK)
        draw.text((WIDTH-404, 31), "RESUMO EDITORIAL", font=small, fill=INK)
        artist = story["artist"].upper()
        for size in range(44, 15, -2):
            name_font = ImageFont.truetype(font_file(True), size)
            if draw.textlength(artist, font=name_font) <= 1550:
                break
        else:
            raise ValueError("Artist name is too long for the editorial header")
        draw.text((160, 186), artist, font=name_font, fill=WHITE)
        draw.line((160, 264, 1760, 264), fill="#3a3b40", width=2)
        draw.line((160, 899, 1760, 899), fill="#3a3b40", width=2)
        source = urlparse(story.get("item", {}).get("url", "")).hostname or "Fonte nao informada"
        source_text = f"Fonte: {source}"
        for size in range(27, 13, -1):
            source_font = ImageFont.truetype(font_file(), size)
            if draw.textlength(source_text, font=source_font) <= 1560:
                break
        else:
            raise ValueError("Source label is too long for the editorial footer")
        draw.text((160, 932), source_text, font=source_font, fill="#c1c2c6")
        draw.rectangle((0, HEIGHT-12, WIDTH, HEIGHT), fill="#292a2e")
        self.layers = []
        font, row_height = self.layout["font"], self.layout["line_height"]
        for line in self.layout["lines"]:
            layer = Image.new("RGBA", (TEXT_BOX[2]-TEXT_BOX[0], row_height))
            ld = ImageDraw.Draw(layer)
            ld.text((24, 12), line, font=font, fill=WHITE, anchor="lt")
            self.layers.append(layer)
        self.highlight_width = math.ceil(draw.textlength(self.layout["lines"][-1], font=font))+48
        self.entry = min(.48, self.duration*.22)
        self.stagger = min(.065, self.duration*.025)
        self.settled_at = self.entry + self.stagger*(len(self.layers)-1)

    def frame(self, second: float) -> Image.Image:
        t = min(max(0, second), self.duration)
        image = self.base.copy()
        draw = ImageDraw.Draw(image)
        progress = t / self.duration
        # Only the accent clears at the end; the words remain readable until the cut.
        exit_progress = ease((t-(self.duration-.16))/.16) if self.duration >= 1 else 0
        draw.rectangle((96, 176, 106, 176+round(66*ease((t+.06)/.34))), fill=ACCENT)
        draw.rectangle((160, 262, 160+round(380*ease((t+.05)/.5)), 266), fill=ACCENT)
        draw.rectangle((0, HEIGHT-12, round(WIDTH*progress), HEIGHT), fill=ACCENT)
        row_height = self.layout["line_height"]
        for index, layer in enumerate(self.layers):
            y = self.layout["top"] + index*row_height
            reveal = 1 if self.duration < 1 else ease((t+.055-index*self.stagger)/self.entry)
            if index == len(self.layers)-1:
                width = round(self.highlight_width*reveal*(1-exit_progress*.12))
                draw.rectangle((TEXT_BOX[0], y, TEXT_BOX[0]+width, y+row_height-10), fill=ACCENT)
            offset = round((1-reveal)*row_height*.65)
            # A per-line mask stops moving glyphs from colliding with the next line.
            mask = Image.new("RGBA", layer.size)
            mask.alpha_composite(layer, (0, offset))
            if reveal < 1:
                mask.putalpha(mask.getchannel("A").point(lambda alpha: round(alpha*(.35+.65*reveal))))
            image.paste(mask, (TEXT_BOX[0], y), mask)
        return image


def render_card(story: dict, shot: dict, folder: Path) -> Path:
    """Write exact frame counts atomically; a failed encode cannot become a cache hit."""
    import numpy as np
    from imageio_ffmpeg import write_frames
    from .horizontal_news import font_file

    frames = round(float(shot["duration"])*FPS)
    offset = round(float(shot.get("animation_offset", 0))*FPS)
    if frames < 1 or offset < 0:
        raise ValueError("Invalid card frame interval")
    if shot.get("role") == "infographic":
        from .infographics import InfographicMotion
        motion = InfographicMotion(story, shot)
    else:
        motion = EditorialMotion(story, shot)
    if offset+frames > round(motion.duration*FPS):
        raise ValueError("Card interval exceeds its animation")
    fonts = [hashlib.sha256(Path(font_file(bold)).read_bytes()).hexdigest() for bold in (False, True)]
    key = hashlib.sha256(json.dumps([SKIN_VERSION, story["artist"], story.get("item", {}).get("url"),
                                   shot, fonts, getattr(motion, "fact", None)], sort_keys=True).encode()).hexdigest()[:20]
    path = folder / f"motion-{key}.mp4"
    if path.exists():
        return path
    temporary = path.with_suffix(".partial.mp4")
    writer = write_frames(str(temporary), (WIDTH, HEIGHT), fps=FPS, codec="libx264",
                          pix_fmt_in="rgb24", pix_fmt_out="yuv420p", macro_block_size=1,
                          ffmpeg_log_level="error", output_params=["-preset", "veryfast", "-crf", "20",
                          "-threads", "4", "-video_track_timescale", "15360", "-movflags", "+faststart"])
    try:
        writer.send(None)
        for index in range(frames):
            writer.send(np.asarray(motion.frame((index+offset)/FPS)))
        writer.close()
        # Closing the pipe alone does not prove a complete encode.
        from .horizontal_news import probe
        stream = next(s for s in probe(temporary)["streams"] if s["codec_type"] == "video")
        if int(stream.get("nb_frames", 0)) != frames:
            raise RuntimeError("Animated editorial card lost frames")
        temporary.replace(path)
    finally:
        writer.close()
        temporary.unlink(missing_ok=True)
    return path
