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
        "id": "ive_red_carpet",
        "name": "IVE",
        "commons_title": "File:IVE (아이브) at the 2023 Melon Music Awards Red Carpet.webm",
        "file": "ive_red_carpet_480p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/c/c4/"
            "IVE_%28%EC%95%84%EC%9D%B4%EB%B8%8C%29_at_the_2023_Melon_Music_Awards_Red_Carpet.webm/"
            "IVE_%28%EC%95%84%EC%9D%B4%EB%B8%8C%29_at_the_2023_Melon_Music_Awards_Red_Carpet.webm.480p.vp9.webm"
        ),
        "credit": "IVE at 2023 Melon Music Awards Red Carpet, video by 티비텐 TV10, CC BY 3.0",
        "display_credit": "IVE at 2023 Melon Music Awards Red Carpet, video by TV10, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:IVE_(%EC%95%84%EC%9D%B4%EB%B8%8C)_at_the_2023_Melon_Music_Awards_Red_Carpet.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
    {
        "id": "katy_perry_interview",
        "name": "Katy Perry",
        "commons_title": "File:Interview with Katy Perry on her role as UNICEF Goodwill Ambassador.webm",
        "file": "katy_perry_interview_720p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/c/cc/"
            "Interview_with_Katy_Perry_on_her_role_as_UNICEF_Goodwill_Ambassador.webm/"
            "Interview_with_Katy_Perry_on_her_role_as_UNICEF_Goodwill_Ambassador.webm.720p.vp9.webm"
        ),
        "credit": "Interview with Katy Perry, video by Priyanka Pruthi, CC BY 3.0",
        "display_credit": "Katy Perry interview, video by Priyanka Pruthi, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:Interview_with_Katy_Perry_on_her_role_as_UNICEF_Goodwill_Ambassador.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
    {
        "id": "lady_gaga_interview",
        "name": "Lady Gaga",
        "commons_title": "File:SB50 Lady GaGa Interview.webm",
        "file": "lady_gaga_sb50_interview_720p.webm",
        "download_url": (
            "https://upload.wikimedia.org/wikipedia/commons/transcoded/f/f9/"
            "SB50_Lady_GaGa_Interview.webm/SB50_Lady_GaGa_Interview.webm.720p.vp9.webm"
        ),
        "credit": "SB50 Lady GaGa Interview, video by SMP Entertainment, CC BY 3.0",
        "display_credit": "Lady Gaga interview, video by SMP Entertainment, CC BY 3.0",
        "source": "https://commons.wikimedia.org/wiki/File:SB50_Lady_GaGa_Interview.webm",
        "license": "https://creativecommons.org/licenses/by/3.0/",
    },
]

SCENES = [
    {
        "asset_id": "ive_red_carpet",
        "seek_start": 3.0,
        "duration": 6.0,
        "eyebrow": "SCENE 1  |  CHEGADA",
        "title": "Chegada ao tapete",
        "body": "A noticia fala sobre o limite entre festa, palco e bastidor.",
        "crop_x": 0,
        "crop_y": 10,
    },
    {
        "asset_id": "ive_red_carpet",
        "seek_start": 25.0,
        "duration": 6.0,
        "eyebrow": "SCENE 2  |  PHOTO CALL",
        "title": "Pose para imprensa",
        "body": "O visual mostra celebridades sob flashes, nao um trecho cru.",
        "crop_x": 100,
        "crop_y": 40,
    },
    {
        "asset_id": "katy_perry_interview",
        "seek_start": 10.0,
        "duration": 6.0,
        "eyebrow": "SCENE 3  |  ENTREVISTA",
        "title": "Bastidor em contexto",
        "body": "A narracao editorial conecta o B-roll a noticia do RSS.",
        "crop_x": 0,
        "crop_y": 0,
    },
    {
        "asset_id": "lady_gaga_interview",
        "seek_start": 25.0,
        "duration": 6.0,
        "eyebrow": "SCENE 4  |  IMPRENSA",
        "title": "Rotina de artista",
        "body": "Entrevistas ajudam a quebrar o ritmo e evitar bloco longo.",
        "crop_x": 60,
        "crop_y": 20,
    },
    {
        "asset_id": "ive_red_carpet",
        "seek_start": 65.0,
        "duration": 6.0,
        "eyebrow": "SCENE 5  |  PUBLICO",
        "title": "Aceno aos fas",
        "body": "O fechamento volta ao tapete, com novo enquadramento.",
        "crop_x": 160,
        "crop_y": 0,
    },
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
    text = (
        "Notícia da G1 Pop e Arte: excesso de álcool em palcos e bastidores "
        "pode afetar a rotina dos artistas. O ponto central é simples: quando "
        "a festa passa do limite, show, equipe e público sentem o impacto. "
        "Neste teste, a LCB monta cenas legais de tapete vermelho e entrevistas, "
        "com áudio original mutado e créditos preservados."
    )
    (OUT / "voiceover.txt").write_text(text, encoding="utf-8")
    provider = get_tts_provider()
    if provider.name != "elevenlabs":
        raise RuntimeError(f"Expected ElevenLabs voiceover, got {provider.name}")
    return provider.synthesize(text, OUT / "voiceover.mp3", lang="pt-BR")


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
    run(
        [
            im,
            "-size",
            "1920x1080",
            "xc:none",
            "-fill",
            "rgba(0,0,0,0.62)",
            "-draw",
            "rectangle 0,760 1920,1080",
            "-fill",
            "#d23b68",
            "-draw",
            "rectangle 0,0 22,1080",
            "-font",
            font_file(bold=True),
            "-fill",
            "#f8fafc",
            "-pointsize",
            "34",
            "-annotate",
            "+90+815",
            str(scene["eyebrow"]),
            "-font",
            font_file(bold=True),
            "-fill",
            "#ffffff",
            "-pointsize",
            "72",
            "-annotate",
            "+90+895",
            str(scene["title"]),
            "-font",
            font_file(),
            "-fill",
            "#d1d5db",
            "-pointsize",
            "32",
            "-annotate",
            "+90+965",
            str(scene["body"]),
            "-font",
            font_file(),
            "-fill",
            "#aeb7c5",
            "-pointsize",
            "22",
            "-annotate",
            "+90+1032",
            str(asset.get("display_credit") or asset["credit"]),
            str(overlay),
        ]
    )
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
        duration = min(float(scene["duration"]), max(probe_duration(source) - seek_start, 0.0))
        overlay = make_overlay(scene, asset, index)
        scene_video = OUT / f"scene_{index}.mp4"
        crop_x = int(scene["crop_x"])
        crop_y = int(scene["crop_y"])
        run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{seek_start:.3f}",
                "-i",
                str(source),
                "-loop",
                "1",
                "-i",
                str(overlay),
                "-t",
                f"{duration:.3f}",
                "-filter_complex",
                (
                    "[0:v]fps=30,scale=2100:1182:force_original_aspect_ratio=increase,"
                    f"crop=1920:1080:x={crop_x}:y={crop_y},"
                    "setsar=1,eq=brightness=-0.06:saturation=0.95,"
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
