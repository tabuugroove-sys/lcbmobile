"""Opt-in, source-aware editing. Provenance is not semantic/identity verification."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)
POLICY_VERSION = 3
TIMING_VERSION = 2
FPS = 30


def planner_mode() -> str:
    return "beats" if os.getenv("LONGFORM_PLANNER", "legacy").lower() == "beats" else "legacy"


def sensitive_triggers(story: dict) -> list[str]:
    item = story.get("item", {})
    text = " ".join(str(v or "") for v in (story.get("headline"), story.get("narration"), item.get("title"), item.get("summary")))
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    patterns = (r"morre\w*", r"morte\w*", r"luto", r"falec\w*", r"cancer", r"doenca\w*",
                r"hospital\w*", r"internad\w*", r"acidente\w*", r"tragedia\w*", r"agress\w*",
                r"abus\w*", r"judicial", r"justica", r"pres[oa]", r"prisao", r"denunci\w*", r"acusad\w*")
    return sorted({match.group() for pattern in patterns for match in re.finditer(r"\b" + pattern + r"\b", text)})


def sentence_beats(cues: list[tuple[float, float, str]], length: float) -> list[dict]:
    """Sentence boundaries snapped to frames; silence stays with the preceding beat."""
    frames = round(length * FPS)
    if frames <= 0 or not cues:
        raise ValueError("Missing aligned narration")
    beats, text, start = [], [], 0
    for index, (_, end, phrase) in enumerate(cues):
        if not math.isfinite(end):
            raise ValueError("Non-finite alignment")
        text.append(phrase)
        if phrase.rstrip().endswith((".", "!", "?")) or index == len(cues) - 1:
            stop = frames if index == len(cues) - 1 else max(start, min(frames, round(end * FPS)))
            if stop > start:
                beats.append({"start": start / FPS, "duration": (stop-start) / FPS, "text": " ".join(text)})
                start, text = stop, []
    if not beats or start != frames:
        raise ValueError("Alignment does not cover narration")
    return beats


def collect_news_images(stories: list[dict], folder: Path) -> None:
    from PIL import Image
    from ..models import NewsItem
    from .source_media import _image_hash, fetch_source_article_images

    # Repeated site-wide OG placeholders and visually identical photos are not variety.
    seen = []
    for story in stories:
        item = story.get("item", {})
        rows = story.get("news_images")
        if rows is None:
            try:
                rows = [a.as_manifest() for a in fetch_source_article_images(
                    NewsItem.model_validate(item), folder / "news_images" / story["id"], limit=4)]
            except Exception as exc:
                log.warning("Source photos unavailable for %s: %s", story.get("artist"), type(exc).__name__)
                rows = []
        accepted, rejected = [], []
        for row in rows:
            reason = None
            try:
                name = str(row.get("source_url", "")).lower()
                if row.get("source_page") != item.get("url"):
                    reason = "not_from_story_source"
                elif re.search(r"logo|placeholder|default[-_]?image|no[-_]?image|avatar|favicon|banner", name):
                    reason = "placeholder_url"
                with Image.open(row["path"]) as image:
                    if min(image.size) < 480 or max(image.size) < 800:
                        reason = reason or "low_resolution"
                    signature = _image_hash(image)
                    matches = [(owner, previous) for old, owner, previous in seen
                               if (signature[0] ^ old[0]).bit_count() <= 6 and
                               sum(abs(a-b) for a,b in zip(signature[1], old[1])) <= 45]
                    if matches:
                        reason = reason or "repeated_image"
                        for owner, previous in matches:
                            if owner is not story:
                                owner["news_images"] = [a for a in owner["news_images"] if a["path"] != previous["path"]]
                                owner["image_filter"]["rejected"].append({"source_url": previous.get("source_url"),
                                                                        "reason": "repeated_across_stories"})
                if not reason:
                    seen.append((signature, story, row))
                    accepted.append({**row, "sha256": hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest()})
            except (OSError, KeyError, ValueError):
                reason = "unreadable_image"
            if reason:
                rejected.append({"source_url": row.get("source_url"), "reason": reason})
        story["news_images"] = accepted
        story["image_filter"] = {"rejected": rejected, "identity_verified": False,
                                 "sitewide_placeholder_detection": "within_current_edition_only"}


def plan_story(story: dict, length: float, cues: list[tuple[float, float, str]]) -> dict:
    from .horizontal_news import plan_shots

    triggers = sensitive_triggers(story)
    fallback = None
    try:
        beats = sentence_beats(cues, length)
    except (ValueError, TypeError, KeyError) as exc:
        beats = [{"start": 0, "duration": length, "text": story.get("narration") or story["headline"]}]
        fallback = "alignment_" + type(exc).__name__
    images = list(story.get("news_images", []))
    shots = []
    for index, beat in enumerate(beats):
        start, stop = round(beat["start"]*FPS), round((beat["start"]+beat["duration"])*FPS)
        first = True
        while start < stop:
            end = min(stop, start+4*FPS)
            role, asset = "archive", None
            # The first sentence establishes the actual story, not unrelated action.
            if first and images and (index == 0 or triggers or index % 2 == 0):
                role, asset = "news_image", images.pop(0)
            elif triggers or fallback or index == 0:
                role = "narrative_card"
            if role == "archive":
                # Keep a whole sentence slot; the footage planner supplies 2-4s cuts.
                # Splitting it into 4s slots first would create tiny remainder cuts.
                end = stop
            text = beat["text"]
            if role == "narrative_card" and not fallback:
                text = " ".join(t for a,b,t in cues if b > start/FPS and a < end/FPS) or text
            shots.append({"start": start/FPS, "duration": (end-start)/FPS, "text": text,
                          "beat_index": index, "role": role, "asset": asset})
            start, first = end, False
    archive_length = sum(s["duration"] for s in shots if s["role"] == "archive")
    archive = []
    if archive_length:
        try:
            archive = plan_shots(story["assets"], round(archive_length*FPS)/FPS)
        except Exception as exc:
            # Safe for sensitive/unknown tone too: never reintroduce celebration footage.
            fallback = "archive_" + type(exc).__name__
            for shot in shots:
                if shot["role"] == "archive":
                    shot["role"] = "narrative_card"
    result, ai, consumed = [], 0, 0.0
    for shot in shots:
        if shot["role"] != "archive":
            result.append(shot)
            continue
        remaining, cursor = shot["duration"], shot["start"]
        while remaining > .5/FPS:
            source = archive[ai]
            take = min(remaining, source["duration"]-consumed)
            result.append({**shot, "start": cursor, "duration": take,
                           "asset": source["asset"], "source_start": source["source_start"]+consumed,
                           "quality_score": source["quality_score"]})
            remaining, cursor, consumed = remaining-take, cursor+take, consumed+take
            if consumed >= source["duration"]-.5/FPS:
                ai, consumed = ai+1, 0.0
    for shot in result:
        role, asset = shot["role"], shot.get("asset") or {}
        shot["match_basis"] = {"archive": "artist_name_only", "news_image": "source_article_image",
                               "narrative_card": "narration_text_not_a_quote"}[role]
        shot["source"] = asset.get("source_page") or story.get("item", {}).get("url", "")
        shot.setdefault("source_start", 0)
        shot.setdefault("quality_score", None)
    # Adjacent card fragments share a clock, including sub-second sentence tails.
    groups = []
    for shot in result:
        if shot["role"] == "narrative_card":
            if (groups and groups[-1][-1]["beat_index"] == shot["beat_index"]
                    and abs(groups[-1][-1]["start"]+groups[-1][-1]["duration"]-shot["start"]) < .5/FPS):
                groups[-1].append(shot)
            else:
                groups.append([shot])
    for group in groups:
        begin, end = group[0]["start"], group[-1]["start"]+group[-1]["duration"]
        text = " ".join(t for a,b,t in cues if b > begin and a < end) or group[0]["text"]
        for shot in group:
            shot.update({"animation_text": text, "animation_offset": shot["start"]-begin,
                         "animation_duration": end-begin})
    return {"policy_version": POLICY_VERSION, "planner": "beats", "semantic_validation": "not_performed",
            "sensitive_triggers": triggers, "tone_check": "keyword_heuristic", "fallback_reason": fallback,
            "beats": beats, "shots": result,
            "visual_seconds": {role: sum(s["duration"] for s in result if s["role"] == role)
                               for role in ("archive", "news_image", "narrative_card")}}


def input_digest(stories: list[dict], folder: Path) -> str:
    from .editorial_motion import SKIN_VERSION
    from .infographics import INFOGRAPHIC_VERSION
    rows = []
    for story in stories:
        rows.append({"story": story, "alignment": hashlib.sha256(
            (folder / f"alignment-{story['id']}.json").read_bytes()).hexdigest()})
    return hashlib.sha256(json.dumps([POLICY_VERSION, TIMING_VERSION, SKIN_VERSION, INFOGRAPHIC_VERSION, rows], sort_keys=True).encode()).hexdigest()


def still_frame(story: dict, shot: dict, folder: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    from .horizontal_news import WIDTH, HEIGHT, font_file

    key = hashlib.sha256(json.dumps([POLICY_VERSION, story["id"], shot], sort_keys=True).encode()).hexdigest()[:16]
    path = folder / f"editorial-{key}.png"
    if path.exists():
        return path
    image = Image.new("RGB", (WIDTH, HEIGHT), "#182222")
    if shot["role"] == "news_image":
        with Image.open(shot["asset"]["path"]) as photo:
            # Fit, not blind centre-crop: do not cut the person's face out of a portrait.
            photo = ImageOps.contain(photo.convert("RGB"), (WIDTH, HEIGHT-68))
            image.paste(photo, ((WIDTH-photo.width)//2, 68+(HEIGHT-68-photo.height)//2))
    draw = ImageDraw.Draw(image)
    small = ImageFont.truetype(font_file(), 28)
    label = "IMAGEM DA FONTE" if shot["role"] == "news_image" else "RESUMO EDITORIAL"
    draw.rectangle((0, 0, WIDTH, 68), fill="#08080a")
    draw.rectangle((0, 0, 12, 68), fill="#ef4564")
    draw.text((40, 18), label, font=small, fill="white")
    if shot["role"] == "narrative_card":
        draw.text((100, 140), story["artist"].upper(), font=small, fill="#f27d94")
        text = shot["text"]
        for size in range(66, 15, -2):
            font = ImageFont.truetype(font_file(True), size)
            lines, line = [], ""
            for word in text.split():
                if draw.textlength((line+" "+word).strip(), font=font) > WIDTH-200 and line:
                    lines.append(line)
                    line = word
                else:
                    line = (line+" "+word).strip()
            lines.append(line)
            if len(lines)*(size+15) <= 600 and max(draw.textlength(t, font=font) for t in lines) <= WIDTH-200:
                break
        else:
            raise ValueError("Editorial card cannot fit narration text")
        y = max(240, (HEIGHT-len(lines)*(size+15))//2)
        for line in lines:
            draw.text((100, y), line, font=font, fill="white")
            y += size+15
    source = urlparse(story.get("item", {}).get("url", "")).hostname or "Fonte nao informada"
    y = 88 if shot["role"] == "news_image" else 914
    draw.rectangle((80, y, WIDTH-80, y+70), fill="#08080a")
    draw.text((100, y+18), f"Fonte: {source}", font=small, fill="#dddddd")
    image.save(path)
    return path
