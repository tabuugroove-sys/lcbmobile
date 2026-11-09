"""Explicit editorial facts anchored to narration, not inferred popularity charts."""
from __future__ import annotations

import math
from urllib.parse import urlparse

from PIL import ImageDraw, ImageFont

from .editorial_motion import EditorialMotion, HEIGHT, INK, WHITE, WIDTH, ease

INFOGRAPHIC_VERSION = "unit-grid-1"
TEAL = "#63d8c5"


def validate_fact(fact: dict, story: dict) -> dict:
    required = ("value", "unit", "block_value", "evidence_quote", "source_page")
    if any(key not in fact for key in required):
        raise ValueError("Incomplete infographic fact")
    value, block = fact["value"], fact["block_value"]
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0
           for n in (value, block)):
        raise ValueError("Infographic values must be finite positive numbers")
    if value % 1 or block % 1:
        raise ValueError("People, tracks and completed years use whole-number counts")
    if not 1 <= value/block <= 16 or fact["unit"] not in {"faixas", "anos", "pessoas"}:
        raise ValueError("Unsupported infographic scale or unit")
    evidence = fact["evidence_quote"]
    narration = story.get("narration", "")
    if not isinstance(evidence, str) or not evidence.strip() or narration.count(evidence) != 1:
        raise ValueError("Infographic evidence must occur once in the narration")
    if not fact["source_page"] or fact["source_page"] != story.get("item", {}).get("url"):
        raise ValueError("Infographic source does not match the story")
    source = urlparse(fact["source_page"])
    if source.scheme not in {"https", "http"} or not source.hostname:
        raise ValueError("Infographic needs an article source URL")
    approximate = fact.get("approximate", False)
    if not isinstance(approximate, bool):
        raise ValueError("Approximation flag must be boolean")
    if any(word in evidence.casefold() for word in ("cerca de", "aproximadamente")) and not approximate:
        raise ValueError("Do not turn an approximate audience figure into an exact count")
    return {**fact, "validation": "literal_narration_anchor_only",
            "semantic_validation": "not_performed", "skin": INFOGRAPHIC_VERSION}


def apply_infographics(story: dict, plan: dict, alignment: dict, voice_start: float) -> None:
    """Replace at most two existing shots, leaving source intervals and timing intact."""
    used, seen_quotes = set(), set()
    alignment_text = "".join(alignment.get("characters", []))
    report = []
    facts = story.get("infographics", [])
    if not isinstance(facts, list):
        plan["infographics"] = [{"status":"skipped", "reason":"Infographic facts must be a list"}]
        return
    for raw in facts[:2]:
        try:
            fact = validate_fact(raw, story)
            quote = fact["evidence_quote"]
            if quote in seen_quotes:
                raise ValueError("Duplicate infographic evidence")
            if alignment_text.count(quote) != 1:
                raise ValueError("Fact cannot be located in the voice alignment")
            begin = alignment_text.index(quote)
            start = float(alignment["character_start_times_seconds"][begin])-voice_start
            end = float(alignment["character_end_times_seconds"][begin+len(quote)-1])-voice_start
            if not all(math.isfinite(n) for n in (start, end)) or end <= start:
                raise ValueError("Invalid aligned fact interval")
            choices = []
            for index, shot in enumerate(plan["shots"]):
                overlap = min(end, shot["start"]+shot["duration"])-max(start, shot["start"])
                if index not in used and overlap > .2 and 2 <= shot["duration"] <= 4:
                    choices.append((overlap, index))
            if not choices:
                raise ValueError("No readable shot overlaps the spoken fact")
            _, index = max(choices)
            shot = plan["shots"][index]
            previous_role = shot["role"]
            # Do not retain a shared typography clock after replacing one fragment.
            for key in ("animation_text", "animation_offset", "animation_duration"):
                shot.pop(key, None)
            shot.update({"role": "infographic", "asset": None, "source_start": 0,
                         "source": fact["source_page"], "quality_score": None,
                         "match_basis": "explicit_fact_aligned_to_narration", "infographic": fact})
            used.add(index)
            seen_quotes.add(quote)
            report.append({"status": "placed", "shot_index": index, "previous_role": previous_role,
                           "spoken_interval": [start, end], "fact": fact})
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            report.append({"status": "skipped", "reason": str(exc)})
    plan["infographics"] = report
    plan["visual_seconds"] = {role: sum(s["duration"] for s in plan["shots"] if s["role"] == role)
                              for role in ("archive", "news_image", "narrative_card", "infographic")}


def pt_number(value: float) -> str:
    return f"{value:,.1f}".rstrip("0").rstrip(".").replace(",", "_").replace(".", ",").replace("_", ".")


class InfographicMotion(EditorialMotion):
    def __init__(self, story: dict, shot: dict):
        from .horizontal_news import font_file

        super().__init__(story, shot)
        self.fact = validate_fact(shot["infographic"], story)
        value, block = self.fact["value"], self.fact["block_value"]
        self.units = value/block
        self.cells = math.ceil(self.units)
        self.entry = min(.7, self.duration*.28)
        self.settled_at = self.entry + .3
        draw = ImageDraw.Draw(self.base)
        # Infographics retain spoken subtitles; move the source above the artist.
        draw.rectangle((80, 899, WIDTH-80, HEIGHT-24), fill=INK)
        source_font = ImageFont.truetype(font_file(), 24)
        source = urlparse(self.fact["source_page"]).hostname
        draw.text((160, 120), f"Fonte: {source}", font=source_font, fill="#c1c2c6")
        draw.rectangle((WIDTH-450, 0, WIDTH, 91), fill=WHITE)
        draw.text((WIDTH-404, 31), "EM N\u00daMEROS", font=ImageFont.truetype(font_file(True), 29), fill=INK)
        display, unit = value, self.fact["unit"].upper()
        if value >= 1000 and value % 100 == 0:
            display, unit = value/1000, "MIL " + unit
        number = pt_number(display)
        for size in range(260, 79, -2):
            font = ImageFont.truetype(font_file(True), size)
            if draw.textlength(number, font=font) <= 760:
                break
        else:
            raise ValueError("Infographic value does not fit")
        draw.text((160, 385), number, font=font, fill=WHITE, anchor="lt")
        draw.text((170, 675), unit, font=ImageFont.truetype(font_file(True), 48), fill=TEAL)
        if self.fact.get("approximate"):
            draw.text((170, 320), "CERCA DE", font=ImageFont.truetype(font_file(True), 32), fill="#c1c2c6")
        scale = "1 mil" if block == 1000 else pt_number(block)
        unit = "pessoas" if block == 1000 else self.fact["unit"]
        if block == 1:
            unit = {"faixas":"faixa", "anos":"ano", "pessoas":"pessoa"}[unit]
        draw.text((1000, 798), f"Cada bloco = {scale} {unit}", font=source_font, fill="#c1c2c6")

    def frame(self, second: float):
        t = min(max(0, second), self.duration)
        image = self.base.copy()
        draw = ImageDraw.Draw(image)
        draw.rectangle((96, 176, 106, 242), fill=TEAL)
        draw.rectangle((160, 262, 160+round(380*ease((t+.05)/.5)), 266), fill=TEAL)
        rows = math.ceil(self.cells/4)
        top = 360+(4-rows)*48
        for index in range(self.cells):
            x, y = 1000+(index%4)*180, top+(index//4)*96
            draw.rounded_rectangle((x,y,x+152,y+72), radius=4, fill="#292b30")
            fraction = min(1, self.units-index)
            reveal = ease((t-index*.3/max(1,self.cells-1))/self.entry)
            if reveal > 0:
                draw.rectangle((x,y,x+round(152*fraction*reveal),y+72), fill=TEAL)
        draw.rectangle((0,HEIGHT-12,round(WIDTH*t/self.duration),HEIGHT), fill=TEAL)
        return image
