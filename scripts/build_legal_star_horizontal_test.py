"""Build a legal moving-media horizontal test video with ElevenLabs voiceover.

This is a workflow-only smoke test for the future media whitelist layer:
- star footage comes from explicitly licensed Wikimedia Commons files;
- credits are written next to the rendered video;
- original footage audio is muted;
- voiceover must use ElevenLabs in GitHub Actions.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from src.config import ROOT
from src.video.tts import get_tts_provider


OUT = ROOT / "out" / "legal_star_horizontal_test"

NEWS = {
    "title": "Shakira será atração de uma das três cerimônias de abertura da Copa do Mundo; Anitta também fará apresentação",
    "source": "G1 Pop & Arte",
    "url": "https://g1.globo.com/pop-arte/musica/noticia/2026/06/05/shakira-sera-atracao-de-uma-das-tres-cerimonias-de-abertura-da-copa-do-mundo-anitta-tambem-fara-apresentacao.ghtml",
}

ASSETS = [
    {
        "id": "shakira_un_imagine",
        "name": "Shakira",
        "media_type": "video",
        "commons_title": 'File:Na ONU, Shakira canta "Imagine" e pede igualdade para todos.webm',
        "file": "shakira_un_imagine_720p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/2/21/"
            "Na_ONU%2C_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm/"
            "Na_ONU%2C_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm.720p.vp9.webm"
        ),
        "credit": 'Na ONU, Shakira canta "Imagine", video by ONU Brasil, CC BY 3.0',
        "display_credit": "ONU Brasil, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:Na_ONU,_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
    {
        "id": "shakira_davos",
        "name": "Shakira",
        "media_type": "video",
        "commons_title": "File:Davos 2017 - An Insight, An Idea with Shakira.webm",
        "file": "shakira_davos_480p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/d/de/"
            "Davos_2017_-_An_Insight%2C_An_Idea_with_Shakira.webm/"
            "Davos_2017_-_An_Insight%2C_An_Idea_with_Shakira.webm.480p.vp9.webm"
        ),
        "credit": "Davos 2017 - An Insight, An Idea with Shakira, video by World Economic Forum, CC BY 3.0",
        "display_credit": "World Economic Forum, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:Davos_2017_-_An_Insight,_An_Idea_with_Shakira.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
    {
        "id": "shakira_goat",
        "name": "Shakira",
        "media_type": "video",
        "commons_title": "File:Shakira- They Said I Sang Like a Goat.webm",
        "file": "shakira_goat_480p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/e/ef/"
            "Shakira-_They_Said_I_Sang_Like_a_Goat.webm/"
            "Shakira-_They_Said_I_Sang_Like_a_Goat.webm.480p.vp9.webm"
        ),
        "credit": "Shakira: They Said I Sang Like a Goat, video by World Economic Forum, CC BY 3.0",
        "display_credit": "World Economic Forum, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:Shakira-_They_Said_I_Sang_Like_a_Goat.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
]

SCENES = [
    {
        "asset_id": "shakira_un_imagine",
        "seek_start": 0.0,
        "duration": 7.0,
        "eyebrow": "SHAKIRA  |  COPA DO MUNDO",
        "title": "Palco global em 2026",
        "body": "A G1 aponta Shakira entre as atrações da abertura.",
        "crop_x": 0,
        "crop_y": 0,
    },
    {
        "asset_id": "shakira_goat",
        "seek_start": 20.0,
        "duration": 7.0,
        "eyebrow": "HISTÓRICO  |  HIT GLOBAL",
        "title": "Nome forte para abertura",
        "body": "O roteiro foca em Shakira como personagem principal.",
        "crop_x": 110,
        "crop_y": 0,
    },
    {
        "asset_id": "shakira_davos",
        "seek_start": 105.0,
        "duration": 7.0,
        "eyebrow": "CONTEXTO  |  FIGURA PÚBLICA",
        "title": "Mais que um show",
        "body": "A edição alterna performance e fala pública licenciada.",
        "crop_x": 70,
        "crop_y": 0,
    },
    {
        "asset_id": "shakira_un_imagine",
        "seek_start": 10.0,
        "duration": 7.0,
        "eyebrow": "CENA  |  PERFORMANCE",
        "title": "Voz em primeiro plano",
        "body": "O áudio original fica mutado; entra só a narração.",
        "crop_x": 120,
        "crop_y": 20,
    },
    {
        "asset_id": "shakira_goat",
        "seek_start": 85.0,
        "duration": 7.0,
        "eyebrow": "CENA  |  PERFIL",
        "title": "Trajetória e impacto",
        "body": "Vários trechos constroem a matéria, não um bloco cru.",
        "crop_x": 145,
        "crop_y": 0,
    },
    {
        "asset_id": "shakira_davos",
        "seek_start": 220.0,
        "duration": 7.0,
        "eyebrow": "CENA  |  ENTREVISTA",
        "title": "Relevância internacional",
        "body": "A notícia ganha contexto sem usar material sem licença.",
        "crop_x": 30,
        "crop_y": 0,
    },
    {
        "asset_id": "shakira_goat",
        "seek_start": 150.0,
        "duration": 7.0,
        "eyebrow": "CENA  |  MONTAGEM",
        "title": "Cortes em ritmo de notícia",
        "body": "Subtítulos mostram a leitura completa do texto.",
        "crop_x": 80,
        "crop_y": 0,
    },
    {
        "asset_id": "shakira_un_imagine",
        "seek_start": 28.0,
        "duration": 7.0,
        "eyebrow": "FECHO  |  ABERTURA",
        "title": "O palco será dividido",
        "body": "Anitta aparece como contexto brasileiro da mesma matéria.",
        "crop_x": 20,
        "crop_y": 0,
    },
]

NARRATION_SEGMENTS = [
    (
        0.4,
        7.0,
        "Shakira voltou ao centro das notícias no Brasil por causa da abertura da Copa do Mundo de 2026.",
    ),
    (
        7.0,
        14.2,
        "Segundo a G1, ela será atração de uma das três cerimônias oficiais antes dos jogos.",
    ),
    (
        14.2,
        21.5,
        "O ponto forte da escolha é óbvio: Shakira já funciona como símbolo de Copa para muita gente.",
    ),
    (
        21.5,
        28.8,
        "A montagem usa vídeos licenciados de performance e entrevistas, com áudio original completamente mutado.",
    ),
    (
        28.8,
        36.3,
        "A ideia é transformar a notícia em um vídeo editorial: cortes, contexto, texto na tela e narração própria.",
    ),
    (
        36.3,
        43.6,
        "Anitta também aparece na matéria, mas aqui o foco principal fica na força global da Shakira.",
    ),
    (
        43.6,
        50.7,
        "Esse formato permite cobrir uma pessoa específica sem depender de imagens roubadas de red carpet.",
    ),
    (
        50.7,
        58.5,
        "E se a voz ficar mais longa que o plano inicial, o vídeo agora se estende até a narração terminar.",
    ),
]

USER_AGENT = "LCBMobileBot/1.0 legal-media-test (https://github.com/tabuugroove-sys/lcbmobile)"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def require_bin(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise RuntimeError(f"{name} not found")
    return binary


def download_with_retry(client: httpx.Client, urls: list[str]) -> tuple[bytes, str]:
    last_error: Exception | None = None
    for url in urls:
        if not url:
            continue
        for attempt in range(1, 5):
            try:
                resp = client.get(url)
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        f"retryable status {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                resp.raise_for_status()
                return resp.content, url
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                if attempt == 4:
                    break
                time.sleep(2.0 * attempt)
    if last_error:
        raise last_error
    raise RuntimeError("No download URL provided")


def imagemagick_bin() -> str:
    binary = shutil.which("magick") or shutil.which("convert")
    if not binary:
        raise RuntimeError("ImageMagick not found: expected magick or convert")
    return binary


def download_assets() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for asset in ASSETS:
            api = client.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "titles": asset["commons_title"],
                    "prop": "imageinfo",
                    "iiprop": "url|mime|size|extmetadata",
                    "format": "json",
                },
            )
            api.raise_for_status()
            pages = api.json()["query"]["pages"]
            page = next(iter(pages.values()))
            info = page["imageinfo"][0]
            urls = [str(asset.get("download_url") or ""), str(info["url"])]
            asset["mime"] = info.get("mime")
            asset["size"] = info.get("size")
            content, downloaded_url = download_with_retry(client, urls)
            asset["downloaded_url"] = downloaded_url
            (OUT / asset["file"]).write_bytes(content)
    (OUT / "credits.json").write_text(
        json.dumps({"news": NEWS, "assets": ASSETS, "scenes": SCENES}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "credits.txt").write_text(
        "\n".join(
            [
                f"News: {NEWS['title']} | {NEWS['source']} | {NEWS['url']}",
                *[f"{a['credit']} | {a['source']} | {a['license']}" for a in ASSETS],
            ]
        ),
        encoding="utf-8",
    )


def synthesize_voice() -> Path:
    text = " ".join(segment[2] for segment in NARRATION_SEGMENTS)
    (OUT / "voiceover.txt").write_text(text, encoding="utf-8")
    provider = get_tts_provider()
    if provider.name != "elevenlabs":
        raise RuntimeError(f"Expected ElevenLabs voiceover, got {provider.name}")
    return provider.synthesize(text, OUT / "voiceover.mp3", lang="pt-BR")


def _ass_time(seconds: float) -> str:
    centiseconds = int(round(seconds * 100))
    h = centiseconds // 360000
    centiseconds %= 360000
    m = centiseconds // 6000
    centiseconds %= 6000
    s = centiseconds // 100
    cs = centiseconds % 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def _wrap_subtitle(text: str, max_chars: int = 58) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines[:3]


def write_subtitles_ass() -> Path:
    subtitle_file = OUT / "subtitles.ass"
    events = "\n".join(
        (
            "Dialogue: 0,"
            f"{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,"
            f"{_ass_escape(text)}"
        )
        for start, end, text in NARRATION_SEGMENTS
    )
    subtitle_file.write_text(
        "\n".join(
            [
                "[Script Info]",
                "ScriptType: v4.00+",
                "PlayResX: 1920",
                "PlayResY: 1080",
                "",
                "[V4+ Styles]",
                (
                    "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
                    "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
                    "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
                    "Alignment,MarginL,MarginR,MarginV,Encoding"
                ),
                (
                    "Style: Default,DejaVu Sans,52,&H00FFFFFF,&H000000FF,"
                    "&H00111111,&HBB000000,-1,0,0,0,100,100,0,0,3,2,0,"
                    "2,120,120,76,1"
                ),
                "",
                "[Events]",
                "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
                events,
            ]
        ),
        encoding="utf-8",
    )
    return subtitle_file


def font_file(bold: bool = False) -> str:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return "DejaVuSans-Bold" if bold else "DejaVuSans"


def probe_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            require_bin("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        text=True,
    )
    return float(out.strip())


def make_overlay(scene: dict[str, object], asset: dict[str, object], index: int) -> Path:
    overlay = OUT / f"overlay_{index}.png"
    im = imagemagick_bin()
    subtitle = NARRATION_SEGMENTS[index - 1][2]
    subtitle_lines = _wrap_subtitle(subtitle)
    cmd = [
        im,
        "-size",
        "1920x1080",
        "xc:none",
        "-fill",
        "rgba(0,0,0,0.62)",
        "-draw",
        "rectangle 0,0 1920,252",
        "-fill",
        "rgba(0,0,0,0.70)",
        "-draw",
        "rectangle 0,820 1920,1080",
        "-fill",
        "#d23b68",
        "-draw",
        "rectangle 0,0 22,252",
        "-font",
        font_file(bold=True),
        "-fill",
        "#f8fafc",
        "-pointsize",
        "34",
        "-annotate",
        "+90+62",
        str(scene["eyebrow"]),
        "-font",
        font_file(bold=True),
        "-fill",
        "#ffffff",
        "-pointsize",
        "72",
        "-annotate",
        "+90+140",
        str(scene["title"]),
        "-font",
        font_file(),
        "-fill",
        "#d1d5db",
        "-pointsize",
        "32",
        "-annotate",
        "+90+202",
        str(scene["body"]),
        "-font",
        font_file(),
        "-fill",
        "#aeb7c5",
        "-pointsize",
        "22",
        "-annotate",
        "+90+236",
        str(asset.get("display_credit") or asset["credit"]),
        "-font",
        font_file(bold=True),
        "-fill",
        "#ffffff",
    ]
    for line_index, line in enumerate(subtitle_lines):
        cmd.extend(
            [
                "-pointsize",
                "46",
                "-gravity",
                "south",
                "-annotate",
                f"+0+{64 + (len(subtitle_lines) - line_index - 1) * 58}",
                line,
            ]
        )
    cmd.append(str(overlay))
    run(cmd)
    return overlay


def build_video() -> Path:
    require_bin("ffmpeg")
    assets_by_id = {str(asset["id"]): asset for asset in ASSETS}
    rendered_scenes: list[Path] = []
    planned_duration = sum(float(scene["duration"]) for scene in SCENES)
    voice_duration = probe_duration(OUT / "voiceover.mp3")
    target_duration = max(planned_duration, voice_duration + 0.6)
    scene_durations = [float(scene["duration"]) for scene in SCENES]
    scene_durations[-1] += max(target_duration - planned_duration, 0.0)
    total_duration = sum(scene_durations)
    video = OUT / "legal_star_horizontal.mp4"
    music = ROOT / "assets" / "audio" / "travel_todos_momentos.wav"
    music_volume = max(0.0, float(os.getenv("BACKGROUND_MUSIC_VOLUME", "0.15")))

    for index, scene in enumerate(SCENES, start=1):
        asset = assets_by_id[str(scene["asset_id"])]
        source = OUT / str(asset["file"])
        seek_start = float(scene["seek_start"])
        loop_source = bool(scene.get("loop_source"))
        if asset.get("media_type") == "image":
            duration = scene_durations[index - 1]
        elif loop_source:
            duration = scene_durations[index - 1]
        else:
            duration = min(scene_durations[index - 1], max(probe_duration(source) - seek_start, 0.0))
        overlay = make_overlay(scene, asset, index)
        scene_video = OUT / f"scene_{index}.mp4"
        if asset.get("media_type") == "image":
            frames = int(duration * 30)
            pan_x = int(scene.get("pan_x", 0))
            pan_y = int(scene.get("pan_y", 0))
            input_args = ["-loop", "1", "-i", str(source)]
            base_filter = (
                "scale=2240:1260:force_original_aspect_ratio=increase,"
                "zoompan="
                f"z='1.03+0.025*on/{frames}':"
                f"x='(iw-ow)/2+({pan_x})*on/{frames}':"
                f"y='(ih-oh)/2+({pan_y})*on/{frames}':"
                f"d={frames}:s=1920x1080:fps=30,"
                "setsar=1,eq=brightness=-0.06:saturation=0.95,"
            )
        else:
            crop_x = int(scene["crop_x"])
            crop_y = int(scene["crop_y"])
            input_args = ["-ss", f"{seek_start:.3f}", "-i", str(source)]
            if loop_source:
                input_args = ["-stream_loop", "-1", *input_args]
            base_filter = (
                "fps=30,scale=2100:1182:force_original_aspect_ratio=increase,"
                f"crop=1920:1080:x={crop_x}:y={crop_y},"
                "setsar=1,eq=brightness=-0.06:saturation=0.95,"
            )
        run(
            [
                "ffmpeg",
                "-y",
                *input_args,
                "-loop",
                "1",
                "-i",
                str(overlay),
                "-t",
                f"{duration:.3f}",
                "-filter_complex",
                (
                    f"[0:v]{base_filter}"
                    "fade=t=in:st=0:d=0.18,fade=t=out:st="
                    f"{max(duration - 0.25, 0):.3f}:d=0.25,"
                    "format=yuv420p[base];"
                    "[base][1:v]overlay=0:0:shortest=1,format=yuv420p[v]"
                ),
                "-map",
                "[v]",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-movflags",
                "+faststart",
                str(scene_video),
            ]
        )
        rendered_scenes.append(scene_video)

    concat_file = OUT / "scenes.txt"
    concat_file.write_text(
        "\n".join(f"file '{scene_video.name}'" for scene_video in rendered_scenes),
        encoding="utf-8",
    )
    silent_video = OUT / "legal_star_horizontal_silent.mp4"
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            str(silent_video),
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(silent_video),
            "-i",
            str(OUT / "voiceover.mp3"),
            "-stream_loop",
            "-1",
            "-i",
            str(music),
            "-t",
            f"{total_duration:.3f}",
            "-filter_complex",
            (
                f"[2:a]atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS,volume={music_volume:.3f}[m];"
                f"[1:a]atrim=0:{total_duration:.3f},adelay=200|200,volume=1.0[vo];"
                "[m][vo]amix=inputs=2:duration=first:dropout_transition=0[a]"
            ),
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(video),
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            "00:00:04",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(OUT / "preview.png"),
        ]
    )
    return video


def main() -> None:
    download_assets()
    synthesize_voice()
    video = build_video()
    print(f"created={video}")


if __name__ == "__main__":
    main()
