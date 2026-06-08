"""Build a legal moving-media horizontal test video with ElevenLabs voiceover.

This is a workflow-only smoke test for the future media whitelist layer:
- star footage comes from explicitly licensed Wikimedia Commons files;
- credits are written next to the rendered video;
- original footage audio is muted;
- voiceover must use ElevenLabs in GitHub Actions.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx

from src.config import ROOT
from src.video.tts import get_tts_provider


OUT = ROOT / "out" / "legal_star_horizontal_test"

NEWS = {
    "title": "'Não conseguiu cantar de tão bêbado': como excesso de álcool nos palcos e bastidores afeta rotina dos artistas",
    "source": "G1 Pop & Arte",
    "url": "https://g1.globo.com/pop-arte/sertanejo/noticia/2026/06/08/nao-conseguiu-cantar-de-tao-bebado-como-excesso-de-alcool-nos-palcos-e-bastidores-afeta-rotina-dos-artistas.ghtml",
}

ASSETS = [
    {
        "id": "ive_melon_red_carpet",
        "name": "IVE",
        "media_type": "video",
        "commons_title": "File:IVE (아이브) at the 2023 Melon Music Awards Red Carpet.webm",
        "file": "ive_melon_red_carpet_480p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/c/c4/"
            "IVE_%28%EC%95%84%EC%9D%B4%EB%B8%8C%29_at_the_2023_Melon_Music_Awards_Red_Carpet.webm/"
            "IVE_%28%EC%95%84%EC%9D%B4%EB%B8%8C%29_at_the_2023_Melon_Music_Awards_Red_Carpet.webm.480p.vp9.webm"
        ),
        "credit": "IVE at 2023 Melon Music Awards Red Carpet, video by 티비텐 TV10, CC BY 3.0",
        "display_credit": "IVE at 2023 Melon Music Awards Red Carpet, TV10, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:IVE_(%EC%95%84%EC%9D%B4%EB%B8%8C)_at_the_2023_Melon_Music_Awards_Red_Carpet.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
]

SCENES = [
    {
        "asset_id": "ive_melon_red_carpet",
        "seek_start": 2.0,
        "duration": 6.0,
        "eyebrow": "SCENE 1  |  CHEGADA",
        "title": "Entrada no tapete",
        "body": "Video real de red carpet, sem fotos estaticas.",
        "crop_x": 0,
        "crop_y": 0,
    },
    {
        "asset_id": "ive_melon_red_carpet",
        "seek_start": 18.0,
        "duration": 6.0,
        "eyebrow": "SCENE 2  |  PHOTO CALL",
        "title": "Poses para fotógrafos",
        "body": "Mais tapete e flashes, menos fala de entrevista.",
        "crop_x": 80,
        "crop_y": 25,
    },
    {
        "asset_id": "ive_melon_red_carpet",
        "seek_start": 32.0,
        "duration": 6.0,
        "eyebrow": "SCENE 3  |  PREMIAÇÃO",
        "title": "Linha de imprensa",
        "body": "O corte muda o enquadramento e mantém o ritmo visual.",
        "crop_x": 160,
        "crop_y": 45,
    },
    {
        "asset_id": "ive_melon_red_carpet",
        "seek_start": 55.0,
        "duration": 6.0,
        "eyebrow": "SCENE 4  |  FOTÓGRAFOS",
        "title": "Mais poses, outro ângulo",
        "body": "A montagem usa novos trechos do evento, nao um bloco cru.",
        "crop_x": 120,
        "crop_y": 0,
    },
    {
        "asset_id": "ive_melon_red_carpet",
        "seek_start": 72.0,
        "duration": 6.0,
        "eyebrow": "SCENE 5  |  SAÍDA",
        "title": "Aceno e fechamento",
        "body": "O final volta ao red carpet em movimento.",
        "crop_x": 180,
        "crop_y": 20,
    },
]

NARRATION_SEGMENTS = [
    (
        0.4,
        5.2,
        "Na notícia da G1, o excesso de álcool em palcos e bastidores volta ao centro da conversa.",
    ),
    (
        5.2,
        10.6,
        "A questão não é só festa: quando o limite passa, show, equipe e público sentem o impacto.",
    ),
    (
        10.6,
        16.4,
        "Neste teste, a LCB usa só vídeo legal de tapete vermelho e premiação, sem fotos paradas.",
    ),
    (
        16.4,
        22.6,
        "O foco visual fica em chegada, photo call, poses para fotógrafos e cortes rápidos de evento.",
    ),
    (
        22.6,
        29.4,
        "O áudio original fica mutado, a narração é nossa e a edição mostra trabalho editorial.",
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
            asset_url = str(asset.get("download_url") or info["url"])
            asset["mime"] = info.get("mime")
            asset["size"] = info.get("size")
            resp = client.get(asset_url)
            resp.raise_for_status()
            (OUT / asset["file"]).write_bytes(resp.content)
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
    total_duration = sum(float(scene["duration"]) for scene in SCENES)
    video = OUT / "legal_star_horizontal.mp4"
    music = ROOT / "assets" / "audio" / "travel_todos_momentos.wav"

    for index, scene in enumerate(SCENES, start=1):
        asset = assets_by_id[str(scene["asset_id"])]
        source = OUT / str(asset["file"])
        seek_start = float(scene["seek_start"])
        if asset.get("media_type") == "image":
            duration = float(scene["duration"])
        else:
            duration = min(float(scene["duration"]), max(probe_duration(source) - seek_start, 0.0))
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
            "-i",
            str(music),
            "-t",
            f"{total_duration:.3f}",
            "-filter_complex",
            (
                f"[2:a]atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS,volume=0.10[m];"
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
