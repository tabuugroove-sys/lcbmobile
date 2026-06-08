"""Build a legal-media horizontal test video with ElevenLabs voiceover.

This is a workflow-only smoke test for the future media whitelist layer:
- star visuals come from explicitly licensed Wikimedia Commons files;
- credits are written next to the rendered video;
- voiceover must use ElevenLabs in GitHub Actions.
"""
from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import httpx

from src.config import ROOT
from src.video.tts import get_tts_provider


OUT = ROOT / "out" / "legal_star_horizontal_test"

ASSETS = [
    {
        "id": "anitta",
        "name": "Anitta",
        "url": (
            "https://commons.wikimedia.org/wiki/Special:Redirect/file/"
            "Anitta%20-%20Citibank%20Hall%20%2830139698071%29.jpg"
        ),
        "file": "anitta.jpg",
        "credit": "Anitta, photo by Teca Lamboglia, CC BY 2.0",
        "source": "https://commons.wikimedia.org/wiki/File:Anitta_-_Citibank_Hall_(30139698071).jpg",
        "license": "https://creativecommons.org/licenses/by/2.0/",
    },
    {
        "id": "neymar",
        "name": "Neymar",
        "url": (
            "https://commons.wikimedia.org/wiki/Special:Redirect/file/"
            "Neymar%20%28cropped%29.jpg"
        ),
        "file": "neymar.jpg",
        "credit": "Neymar, photo by Alex Fau, CC BY 2.0",
        "source": "https://commons.wikimedia.org/wiki/File:Neymar_(cropped).jpg",
        "license": "https://creativecommons.org/licenses/by/2.0/",
    },
]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def download_assets() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for asset in ASSETS:
            resp = client.get(asset["url"])
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
        "Teste editorial da LCB. Aqui o vídeo usa apenas imagens de estrelas com "
        "licença explícita, crédito preservado e narração original em português. "
        "A ideia é simples: quando a notícia citar uma celebridade, o agente só "
        "pode usar mídia que esteja na whitelist legal, como press kit, media kit "
        "ou Creative Commons validado. Sem isso, ele volta para card visual seguro."
    )
    (OUT / "voiceover.txt").write_text(text, encoding="utf-8")
    provider = get_tts_provider()
    if provider.name != "elevenlabs":
        raise RuntimeError(f"Expected ElevenLabs voiceover, got {provider.name}")
    return provider.synthesize(text, OUT / "voiceover.mp3", lang="pt-BR")


def make_slide(
    *,
    source: Path,
    dest: Path,
    eyebrow: str,
    title: str,
    body: str,
    credit: str,
) -> None:
    title_wrapped = "\n".join(textwrap.wrap(title, width=24))
    body_wrapped = "\n".join(textwrap.wrap(body, width=48))
    run(
        [
            "magick",
            str(source),
            "-resize",
            "1920x1080^",
            "-gravity",
            "center",
            "-extent",
            "1920x1080",
            "-blur",
            "0x12",
            "-modulate",
            "72,85,100",
            "(",
            str(source),
            "-resize",
            "820x920>",
            "-gravity",
            "center",
            "-background",
            "none",
            "-extent",
            "860x940",
            ")",
            "-gravity",
            "east",
            "-geometry",
            "+110+0",
            "-composite",
            "-fill",
            "rgba(0,0,0,0.66)",
            "-draw",
            "rectangle 0,0 1040,1080",
            "-fill",
            "#d23b68",
            "-draw",
            "rectangle 0,0 22,1080",
            "-font",
            "DejaVu-Sans-Bold",
            "-fill",
            "#f8fafc",
            "-pointsize",
            "34",
            "-annotate",
            "+90+150",
            eyebrow,
            "-font",
            "DejaVu-Sans-Bold",
            "-fill",
            "#ffffff",
            "-pointsize",
            "78",
            "-interline-spacing",
            "8",
            "-annotate",
            "+90+300",
            title_wrapped,
            "-font",
            "DejaVu-Sans",
            "-fill",
            "#d1d5db",
            "-pointsize",
            "34",
            "-interline-spacing",
            "6",
            "-annotate",
            "+90+660",
            body_wrapped,
            "-font",
            "DejaVu-Sans",
            "-fill",
            "#aeb7c5",
            "-pointsize",
            "22",
            "-annotate",
            "+90+1010",
            credit[:120],
            str(dest),
        ]
    )


def build_video() -> Path:
    make_slide(
        source=OUT / "anitta.jpg",
        dest=OUT / "slide1.png",
        eyebrow="LEGAL MEDIA TEST  |  CC-BY ASSET",
        title="Estrela na tela, direito preservado",
        body=(
            "O pipeline pode usar imagens reais quando a licença está clara "
            "e o crédito acompanha o vídeo."
        ),
        credit=ASSETS[0]["credit"],
    )
    make_slide(
        source=OUT / "neymar.jpg",
        dest=OUT / "slide2.png",
        eyebrow="WHITELIST VISUAL  |  SEM FOOTAGE PIRATA",
        title="Só entra mídia liberada",
        body=(
            "Press kit, media kit ou Creative Commons validado. Se não passar "
            "no filtro, o vídeo volta para visual seguro."
        ),
        credit=ASSETS[1]["credit"],
    )
    make_slide(
        source=OUT / "anitta.jpg",
        dest=OUT / "slide3.png",
        eyebrow="LCB PIPELINE  |  ELEVENLABS VOICE",
        title="Formato pronto para notícias",
        body=(
            "Narração original, música própria em volume baixo e créditos dos "
            "assets no arquivo de saída."
        ),
        credit="Credits stored in credits.txt and credits.json",
    )

    video = OUT / "legal_star_horizontal.mp4"
    music = ROOT / "assets" / "audio" / "travel_todos_momentos.wav"
    run(
        [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-t",
            "10",
            "-i",
            str(OUT / "slide1.png"),
            "-loop",
            "1",
            "-t",
            "10",
            "-i",
            str(OUT / "slide2.png"),
            "-loop",
            "1",
            "-t",
            "10",
            "-i",
            str(OUT / "slide3.png"),
            "-i",
            str(OUT / "voiceover.mp3"),
            "-i",
            str(music),
            "-filter_complex",
            (
                "[0:v]scale=1920:1080,format=yuv420p,fade=t=in:st=0:d=0.25,"
                "fade=t=out:st=9.7:d=0.3[v0];"
                "[1:v]scale=1920:1080,format=yuv420p,fade=t=in:st=0:d=0.25,"
                "fade=t=out:st=9.7:d=0.3[v1];"
                "[2:v]scale=1920:1080,format=yuv420p,fade=t=in:st=0:d=0.25,"
                "fade=t=out:st=9.7:d=0.3[v2];"
                "[v0][v1][v2]concat=n=3:v=1:a=0[v];"
                "[4:a]atrim=0:30,asetpts=PTS-STARTPTS,volume=0.10[m];"
                "[3:a]adelay=250|250,volume=1.0[vo];"
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
