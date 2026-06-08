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

ASSETS = [
    {
        "id": "neymar_free_kick",
        "name": "Neymar",
        "commons_title": "File:Neymar takes a free kick - BRA v. RSA, Rio 2016.ogv",
        "file": "neymar_free_kick.ogv",
        "credit": "Neymar free kick, video by Rodrigogomesonetwo, CC BY-SA 4.0",
        "source": "https://commons.wikimedia.org/wiki/File:Neymar_takes_a_free_kick_-_BRA_v._RSA,_Rio_2016.ogv",
        "license": "https://creativecommons.org/licenses/by-sa/4.0/",
        "duration_limit": 26.0,
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
            asset_url = info["url"]
            asset["mime"] = info.get("mime")
            asset["size"] = info.get("size")
            resp = client.get(asset_url)
            resp.raise_for_status()
            (OUT / asset["file"]).write_bytes(resp.content)
    (OUT / "credits.json").write_text(
        json.dumps(ASSETS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (OUT / "credits.txt").write_text(
        "\n".join(f"{a['credit']} | {a['source']} | {a['license']}" for a in ASSETS),
        encoding="utf-8",
    )


def synthesize_voice() -> Path:
    text = (
        "Teste editorial da LCB. Agora o vídeo usa footage real de Neymar, "
        "baixado do Wikimedia Commons com licença explícita e crédito preservado. "
        "O áudio original fica mutado. A narração é nossa, feita no ElevenLabs, "
        "com música baixa no fundo."
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


def make_overlay(asset: dict[str, object]) -> Path:
    overlay = OUT / "overlay.png"
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
            "LEGAL COMMONS VIDEO  |  ORIGINAL AUDIO MUTED",
            "-font",
            font_file(bold=True),
            "-fill",
            "#ffffff",
            "-pointsize",
            "72",
            "-annotate",
            "+90+895",
            "Neymar em footage legal",
            "-font",
            font_file(),
            "-fill",
            "#d1d5db",
            "-pointsize",
            "32",
            "-annotate",
            "+90+965",
            "Video real do Wikimedia Commons com credito e licenca preservados.",
            "-font",
            font_file(),
            "-fill",
            "#aeb7c5",
            "-pointsize",
            "22",
            "-annotate",
            "+90+1032",
            str(asset["credit"]),
            str(overlay),
        ]
    )
    return overlay


def build_video() -> Path:
    require_bin("ffmpeg")
    asset = ASSETS[0]
    source = OUT / asset["file"]
    duration = min(float(asset["duration_limit"]), probe_duration(source), 30.0)
    video = OUT / "legal_star_horizontal.mp4"
    music = ROOT / "assets" / "audio" / "travel_todos_momentos.wav"
    overlay = make_overlay(asset)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-i",
            str(OUT / "voiceover.mp3"),
            "-i",
            str(music),
            "-loop",
            "1",
            "-i",
            str(overlay),
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            (
                "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
                "crop=1920:1080,setsar=1,eq=brightness=-0.06:saturation=0.95,"
                "fade=t=in:st=0:d=0.25,fade=t=out:st="
                f"{max(duration - 0.35, 0):.3f}:d=0.35,"
                "format=yuv420p[base];"
                "[base][3:v]overlay=0:0:shortest=1,format=yuv420p[v];"
                f"[2:a]atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,volume=0.10[m];"
                f"[1:a]atrim=0:{duration:.3f},adelay=200|200,volume=1.0[vo];"
                "[m][vo]amix=inputs=2:duration=first:dropout_transition=0[a]"
            ),
            "-map",
            "[v]",
            "-map",
            "[a]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
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
