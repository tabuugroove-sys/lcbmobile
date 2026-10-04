"""Dynamic 16:9 music bulletin with aligned narration and reviewed source ranges."""
from __future__ import annotations

import base64
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

from ..config import settings

WIDTH, HEIGHT = 1920, 1080


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(args: list[str], folder: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    result = subprocess.run(args, cwd=folder, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr[-2000:])
    return result


def probe(path: Path) -> dict:
    return json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path),
    ], text=True))


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def font_file(bold: bool = False) -> str:
    candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    return str(next(p for p in candidates if p.exists()))


def reviewed_ranges(asset: dict, folder: Path) -> list[list[float]]:
    """Sample every four seconds. Face detection is a quality check, not identity recognition."""
    import cv2

    cache = folder / f"review-{asset['sha256'][:16]}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))["ranges"]
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    capture = cv2.VideoCapture(asset["path"])
    ranges, samples = [], []
    try:
        for begin in range(0, int(float(asset["duration"]) - 4), 4):
            acceptable = 0
            for second in (begin + .8, begin + 2.8):
                capture.set(cv2.CAP_PROP_POS_MSEC, second * 1000)
                ok, frame = capture.read()
                if not ok:
                    continue
                small = cv2.resize(frame, (640, 360))
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
                faces = detector.detectMultiScale(gray, 1.08, 4, minSize=(26, 26))
                good = 0 < len(faces) <= 6 and gray.mean() > 12 and gray.std() > 12
                acceptable += int(good)
                samples.append({"second": second, "faces": len(faces), "brightness": float(gray.mean())})
            if acceptable == 2:
                if ranges and ranges[-1][1] == begin:
                    ranges[-1][1] = float(begin + 4)
                else:
                    ranges.append([float(begin), float(begin + 4)])
    finally:
        capture.release()
    save(cache, {"ranges": ranges, "samples": samples, "identity_verified": False})
    return ranges


def plan_shots(assets: list[dict], length: float) -> list[dict]:
    ranges = [[list(pair) for pair in a["reviewed_ranges"]] for a in assets]
    shots, cursor, next_index = [], 0.0, 0
    while cursor < length - .01:
        for _ in assets:
            index = next_index % len(assets)
            next_index += 1
            while ranges[index] and ranges[index][0][1] - ranges[index][0][0] < .25:
                ranges[index].pop(0)
            if ranges[index]:
                break
        else:
            raise RuntimeError("Not enough reviewed footage; no looping is allowed")
        start, end = ranges[index][0]
        shot = min(7.0, end - start, length - cursor)
        shots.append({"asset": assets[index], "source_start": start, "duration": shot, "start": cursor})
        ranges[index][0][0] += shot
        cursor += shot
    if len({s["asset"]["source_page"] for s in shots}) < 2:
        raise RuntimeError("A chapter needs at least two different video sources")
    return shots


def prepare_voice(stories: list[dict], folder: Path) -> None:
    from elevenlabs.client import ElevenLabs

    if not settings.elevenlabs_api_key:
        raise RuntimeError("Daily music bulletin requires the configured ElevenLabs voice")
    client = ElevenLabs(api_key=settings.elevenlabs_api_key)
    for story in stories:
        key = hashlib.sha256(json.dumps([
            story["narration"], settings.elevenlabs_voice_id, settings.elevenlabs_model,
            settings.elevenlabs_speed, settings.elevenlabs_stability,
            settings.elevenlabs_similarity, settings.elevenlabs_style,
        ]).encode()).hexdigest()
        audio, alignment = folder / f"voice-{story['id']}.mp3", folder / f"alignment-{story['id']}.json"
        if audio.exists() and alignment.exists() and json.loads(alignment.read_text())["key"] == key:
            continue
        response = client.text_to_speech.convert_with_timestamps(
            settings.elevenlabs_voice_id, text=story["narration"],
            model_id=settings.elevenlabs_model, output_format="mp3_44100_128",
            voice_settings={"stability": settings.elevenlabs_stability,
                            "similarity_boost": settings.elevenlabs_similarity,
                            "style": settings.elevenlabs_style, "speed": settings.elevenlabs_speed,
                            "use_speaker_boost": True},
            request_options={"timeout_in_seconds": 120, "max_retries": 1},
        )
        data = (response.normalized_alignment or response.alignment).model_dump()
        data["key"] = key
        data["voice_id"] = settings.elevenlabs_voice_id
        audio.write_bytes(base64.b64decode(response.audio_base_64))
        save(alignment, data)


def subtitle_cues(data: dict, offset: float) -> list[tuple[float, float, str]]:
    text = "".join(data["characters"])
    words = list(re.finditer(r"\S+", text))
    cues, start = [], 0
    for index, word in enumerate(words):
        phrase = text[words[start].start():word.end()].strip()
        if index == len(words) - 1 or len(phrase) >= 64 or index - start >= 10 or (
            word.group().endswith((".", "!", "?")) and index > start
        ):
            begin = data["character_start_times_seconds"][words[start].start()] + offset
            end = data["character_end_times_seconds"][word.end() - 1] + offset
            cues.append((begin, max(begin + .15, end), phrase))
            start = index + 1
    return cues


def _ass_time(seconds: float) -> str:
    centis = round(seconds * 100)
    hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, centis = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", " ").replace("{", "(").replace("}", ")").replace("\n", " ")


def overlay(story: dict, index: int, edition: str, folder: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGBA", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    small, bold = ImageFont.truetype(font_file(), 25), ImageFont.truetype(font_file(True), 42)
    draw.rectangle((0, 0, WIDTH, 68), fill=(8, 8, 10, 210))
    draw.rectangle((0, 0, 10, 68), fill="#ef4564")
    draw.text((36, 19), f"RADAR MUSICAL  /  {edition}  /  {index + 1:02d}", font=small, fill="white")
    draw.text((WIDTH - 318, 19), "IMAGENS DE ARQUIVO", font=small, fill="#dddddd")
    draw.rectangle((32, 784, 1280, 934), fill=(8, 8, 10, 210))
    draw.rectangle((32, 784, 40, 934), fill="#ef4564")
    artist_font = bold
    while draw.textlength(story["artist"].upper(), font=artist_font) > 1180:
        artist_font = ImageFont.truetype(font_file(True), artist_font.size - 2)
    draw.text((62, 801), story["artist"].upper(), font=artist_font, fill="white")
    lines, line = [], ""
    for word in story["headline"].split():
        proposed = f"{line} {word}".strip()
        if draw.textlength(proposed, font=small) > 1180 and line:
            lines.append(line)
            line = word
        else:
            line = proposed
    lines.append(line)
    for i, line in enumerate(lines[:2]):
        draw.text((62, 859 + i * 31), line, font=small, fill="white")
    path = folder / f"overlay-{story['id']}.png"
    image.save(path)
    return path


def render(stories: list[dict], edition: str, folder: Path) -> Path:
    from imageio_ffmpeg import get_ffmpeg_exe

    folder = folder.resolve()
    parts, chapters, timeline, cues = [], [], [], []
    cursor = 0.0
    for index, story in enumerate(stories):
        audio = folder / f"voice-{story['id']}.mp3"
        length = duration(audio) + .35
        try:
            shots = plan_shots(story["assets"], length)
        except RuntimeError as exc:
            raise RuntimeError(f"{story['artist']}: {exc}") from exc
        cover = overlay(story, index, edition, folder)
        cover_hash = hashlib.sha256(cover.read_bytes()).hexdigest()
        chapter_parts = []
        for n, shot in enumerate(shots):
            asset = shot["asset"]
            key = hashlib.sha256(json.dumps([
                asset["sha256"], shot["source_start"], shot["duration"], cover_hash,
            ]).encode()).hexdigest()[:12]
            path = folder / f"shot-{story['id']}-{n}-{key}.mp4"
            if not path.exists():
                run(["ffmpeg", "-v", "error", "-y", "-ss", str(shot["source_start"]), "-i", asset["path"],
                     "-loop", "1", "-i", str(cover), "-t", str(shot["duration"]),
                     "-filter_complex", "[0:v]fps=30,scale=1920:1080:force_original_aspect_ratio=increase,"
                     "crop=1920:1080,setsar=1[base];[base][1:v]overlay=0:0:shortest=1,format=yuv420p[v]",
                     "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-threads", "4", str(path)], folder)
            chapter_parts.append(path)
            timeline.append({"start": cursor + shot["start"], "duration": shot["duration"],
                             "source_start": shot["source_start"], "source": asset["source_page"],
                             "artist": story["artist"]})
        concat = folder / f"shots-{story['id']}.txt"
        concat.write_text("\n".join(f"file '{p.name}'" for p in chapter_parts), encoding="utf-8")
        part = folder / f"part-{story['id']}.mp4"
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
             "-i", str(audio), "-t", str(length), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-af", "apad", "-c:a", "aac", "-b:a", "192k", str(part)], folder)
        chapters.append({"start": cursor, "artist": story["artist"], "headline": story["headline"]})
        cues.extend(subtitle_cues(json.loads((folder / f"alignment-{story['id']}.json").read_text()), cursor))
        parts.append(part)
        cursor += duration(part)
    save(folder / "timeline.json", timeline)
    save(folder / "chapters.json", chapters)
    ass = folder / "subtitles.ass"
    events = "\n".join(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},Default,,0,0,0,,{_ass_escape(t)}" for a, b, t in cues)
    ass.write_text(
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 0\n"
        "\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,"
        "Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        "Style: Default,Arial,44,&H00FFFFFF,&H000000FF,&H00101010,&H90000000,-1,0,0,0,100,100,0,0,3,1,0,2,230,230,40,1\n"
        "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n" + events + "\n", encoding="utf-8")
    concat = folder / "parts.txt"
    concat.write_text("\n".join(f"file '{p.name}'" for p in parts), encoding="utf-8")
    joined, final = folder / "joined.mp4", folder / f"radar-musical-{edition}-16x9.mp4"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(joined)], folder)
    music_args, audio_filter, audio_map = [], [], "0:a"
    music = settings.background_music_path
    if settings.background_music_volume > 0 and music.exists():
        def mean_db(path: Path) -> float:
            result = run(["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], folder)
            return float(re.search(r"mean_volume: (-?[0-9.]+) dB", result.stderr).group(1))
        gain = 10 ** ((mean_db(joined) - mean_db(music) + settings.background_music_db_under_voice) / 20) * settings.background_music_volume
        music_args = ["-i", str(music)]
        audio_filter = ["-filter_complex", f"[1:a]volume={gain:.6f},afade=t=out:st={max(0, duration(music)-2):.3f}:d=2,apad[music];"
                        "[0:a][music]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]"]
        audio_map = "[a]"
    # Relative ASS path avoids Windows drive-letter/filter escaping issues.
    run([get_ffmpeg_exe(), "-v", "error", "-y", "-i", str(joined), *music_args,
         "-vf", "ass=subtitles.ass", *audio_filter, "-map", "0:v", "-map", audio_map,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-threads", "4",
         "-c:a", "aac", "-b:a", "192k", "-t", str(cursor), "-movflags", "+faststart", str(final)], folder, 1800)
    review(final, stories, timeline, folder)
    return final


def review(video: Path, stories: list[dict], timeline: list[dict], folder: Path) -> dict:
    from PIL import Image, ImageDraw, ImageFont

    info = probe(video)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    if (stream["width"], stream["height"]) != (WIDTH, HEIGHT) or duration(video) < 150:
        raise RuntimeError("Daily bulletin has incorrect dimensions or is too short")
    intervals = {}
    for shot in timeline:
        used = intervals.setdefault(shot["source"], [])
        a, b = shot["source_start"], shot["source_start"] + shot["duration"]
        if any(not (b <= x + .02 or a >= y - .02) for x, y in used):
            raise RuntimeError("Repeated source interval")
        used.append((a, b))
    result = run(["ffmpeg", "-v", "info", "-i", str(video),
                  "-vf", "blackdetect=d=0.4:pix_th=0.08:pic_th=0.98",
                  "-af", "silencedetect=noise=-42dB:d=2", "-f", "null", "-"], folder, 600)
    (folder / "decode-check.log").write_text(result.stderr, encoding="utf-8")
    black = [[float(a), float(b)] for a, b in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", result.stderr)]
    silences = re.findall(r"silence_duration: ([0-9.]+)", result.stderr)
    report = {"full_decode_passed": True, "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
              "duration": duration(video), "stories": len(stories),
              "unique_sources": len(intervals), "shots": len(timeline), "width": WIDTH, "height": HEIGHT,
              "black_intervals": black, "silences_over_2s": silences, "source_intervals_do_not_repeat": True,
              "voice_provider": "elevenlabs", "voice_ids": sorted({
                  json.loads((folder / f"alignment-{s['id']}.json").read_text()).get("voice_id", "cached_fixture")
                  for s in stories}), "language": "pt-BR",
              "background_music_ratio": settings.background_music_volume, "background_music_loops": False}
    save(folder / "qa-report.json", report)
    sheet = Image.new("RGB", (1440, math.ceil(len(timeline) / 3) * 298), "#171717")
    draw, font = ImageDraw.Draw(sheet), ImageFont.truetype(font_file(), 18)
    for index, shot in enumerate(timeline):
        frame = folder / f"review-final-{index:03d}.jpg"
        run(["ffmpeg", "-v", "error", "-y", "-ss", str(shot["start"] + shot["duration"] / 2),
             "-i", str(video), "-frames:v", "1", "-vf", "scale=480:270", str(frame)], folder)
        x, y = (index % 3) * 480, (index // 3) * 298
        with Image.open(frame) as image:
            sheet.paste(image, (x, y))
        draw.text((x + 6, y + 273), f"{shot['start']:.1f}s | {shot['artist']}", font=font, fill="white")
    sheet.save(folder / "final-review.jpg")
    if black or silences:
        raise RuntimeError("Video review found a black frame or a prolonged audio gap")
    return report
