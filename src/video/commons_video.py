"""Download curated, reusable artist video from Wikimedia Commons."""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx


log = logging.getLogger(__name__)
MANIFEST_POLICY_VERSION = 1
USER_AGENT = "LCBMobileNews/1.1 (https://github.com/tabuugroove-sys/lcbmobile)"


@dataclass(frozen=True)
class LicensedVideo:
    path: str
    title: str
    creator: str
    license: str
    license_url: str
    source_page: str
    source_url: str
    width: int
    height: int
    duration: float
    seek_seconds: float
    sha256: str

    def as_manifest(self) -> dict[str, object]:
        return asdict(self)


# Each entry is reviewed for identity, framing, resolution, and reuse rights.
# Dynamic video search is deliberately excluded from unattended production.
CURATED_VIDEOS: dict[str, tuple[dict[str, object], ...]] = {
    "lady gaga": (
        {
            "title": "SB50 Lady GaGa Interview.webm",
            "creator": "SMP Entertainment",
            "license": "CC BY 3.0",
            "license_url": "https://creativecommons.org/licenses/by/3.0/",
            "source_page": "https://commons.wikimedia.org/wiki/File:SB50_Lady_GaGa_Interview.webm",
            "source_url": (
                "https://upload.wikimedia.org/wikipedia/commons/transcoded/f/f9/"
                "SB50_Lady_GaGa_Interview.webm/"
                "SB50_Lady_GaGa_Interview.webm.720p.vp9.webm"
            ),
            "width": 1280,
            "height": 720,
            "duration": 212.035,
            "seek_seconds": 20.0,
        },
        {
            "title": 'Lady Gaga performs "The Star-Spangled Banner".webm',
            "creator": "Joint Congressional Committee on Inaugural Ceremonies",
            "license": "Public domain",
            "license_url": "https://creativecommons.org/publicdomain/mark/1.0/",
            "source_page": (
                "https://commons.wikimedia.org/wiki/"
                "File:Lady_Gaga_performs_%22The_Star-Spangled_Banner%22.webm"
            ),
            "source_url": (
                "https://upload.wikimedia.org/wikipedia/commons/transcoded/b/b4/"
                "Lady_Gaga_performs_%22The_Star-Spangled_Banner%22.webm/"
                "Lady_Gaga_performs_%22The_Star-Spangled_Banner%22.webm.720p.vp9.webm"
            ),
            "width": 1280,
            "height": 720,
            "duration": 116.023,
            "seek_seconds": 20.0,
        },
    ),
    "shakira": (
        {
            "title": 'Na ONU, Shakira canta "Imagine" e pede igualdade para todos.webm',
            "creator": "ONU Brasil",
            "license": "CC BY 3.0",
            "license_url": "https://creativecommons.org/licenses/by/3.0/",
            "source_page": (
                "https://commons.wikimedia.org/wiki/"
                "File:Na_ONU,_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm"
            ),
            "source_url": (
                "https://upload.wikimedia.org/wikipedia/commons/transcoded/2/21/"
                "Na_ONU%2C_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm/"
                "Na_ONU%2C_Shakira_canta_%22Imagine%22_e_pede_igualdade_para_todos.webm.720p.vp9.webm"
            ),
            "width": 1280,
            "height": 720,
            "duration": 224.0,
            "seek_seconds": 10.0,
        },
        {
            "title": "Davos 2017 - An Insight, An Idea with Shakira.webm",
            "creator": "World Economic Forum",
            "license": "CC BY 3.0",
            "license_url": "https://creativecommons.org/licenses/by/3.0/",
            "source_page": (
                "https://commons.wikimedia.org/wiki/"
                "File:Davos_2017_-_An_Insight,_An_Idea_with_Shakira.webm"
            ),
            "source_url": (
                "https://upload.wikimedia.org/wikipedia/commons/transcoded/d/de/"
                "Davos_2017_-_An_Insight%2C_An_Idea_with_Shakira.webm/"
                "Davos_2017_-_An_Insight%2C_An_Idea_with_Shakira.webm.480p.vp9.webm"
            ),
            "width": 854,
            "height": 480,
            "duration": 3600.0,
            "seek_seconds": 105.0,
        },
    ),
    "dua lipa": (
        {
            "title": "Interview with Dua Lipa at the 2021 Grammys.webm",
            "creator": "Warner Music New Zealand",
            "license": "CC BY 3.0",
            "license_url": "https://creativecommons.org/licenses/by/3.0/",
            "source_page": (
                "https://commons.wikimedia.org/wiki/"
                "File:Interview_with_Dua_Lipa_at_the_2021_Grammys.webm"
            ),
            "source_url": (
                "https://upload.wikimedia.org/wikipedia/commons/transcoded/0/0c/"
                "Interview_with_Dua_Lipa_at_the_2021_Grammys.webm/"
                "Interview_with_Dua_Lipa_at_the_2021_Grammys.webm.480p.vp9.webm"
            ),
            "width": 854,
            "height": 480,
            "duration": 180.0,
            "seek_seconds": 25.0,
        },
        {
            "title": "Interview with Dua Lipa from 2018.webm",
            "creator": "Warner Music New Zealand",
            "license": "CC BY 3.0",
            "license_url": "https://creativecommons.org/licenses/by/3.0/",
            "source_page": (
                "https://commons.wikimedia.org/wiki/"
                "File:Interview_with_Dua_Lipa_from_2018.webm"
            ),
            "source_url": (
                "https://upload.wikimedia.org/wikipedia/commons/transcoded/4/46/"
                "Interview_with_Dua_Lipa_from_2018.webm/"
                "Interview_with_Dua_Lipa_from_2018.webm.480p.vp9.webm"
            ),
            "width": 854,
            "height": 480,
            "duration": 180.0,
            "seek_seconds": 35.0,
        },
    ),
}


def _write_manifest(
    path: Path,
    query: str | None,
    status: str,
    assets: list[LicensedVideo],
) -> None:
    path.write_text(
        json.dumps(
            {
                "policy_version": MANIFEST_POLICY_VERSION,
                "query": query,
                "status": status,
                "assets": [asset.as_manifest() for asset in assets],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def fetch_licensed_artist_videos(
    query: str | None,
    output_dir: Path,
    *,
    limit: int = 2,
    client: httpx.Client | None = None,
) -> list[LicensedVideo]:
    """Download pre-reviewed clips and preserve their rights evidence."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "rights_manifest.json"
    specs = CURATED_VIDEOS.get(query or "", ())
    if not specs:
        _write_manifest(manifest_path, query, "no_curated_video", [])
        return []

    if manifest_path.exists():
        try:
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            assets = [LicensedVideo(**row) for row in cached.get("assets", [])]
            if (
                cached.get("query") == query
                and cached.get("policy_version") == MANIFEST_POLICY_VERSION
                and cached.get("status") == "verified"
                and len(assets) >= min(limit, len(specs))
                and all(Path(asset.path).exists() for asset in assets)
            ):
                return assets[:limit]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            log.warning("Ignoring unusable video rights manifest: %s", manifest_path)

    owns_client = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(180.0, connect=20.0),
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    assets: list[LicensedVideo] = []
    try:
        for index, spec in enumerate(specs[:limit], start=1):
            path = output_dir / f"artist-video-{index:02d}.webm"
            digest = hashlib.sha256()
            try:
                with client.stream("GET", str(spec["source_url"])) as response:
                    response.raise_for_status()
                    with path.open("wb") as handle:
                        for chunk in response.iter_bytes(1024 * 1024):
                            handle.write(chunk)
                            digest.update(chunk)
                if path.stat().st_size < 100_000:
                    raise RuntimeError("downloaded video is unexpectedly small")
                assets.append(
                    LicensedVideo(path=str(path), sha256=digest.hexdigest(), **spec)
                )
            except Exception as exc:  # noqa: BLE001
                path.unlink(missing_ok=True)
                log.warning("Cannot download curated video %s: %s", spec["title"], exc)

        status = "verified" if len(assets) >= min(limit, len(specs)) else "incomplete"
        _write_manifest(manifest_path, query, status, assets)
        log.info("Commons video resolver: query=%r verified=%d", query, len(assets))
        return assets
    finally:
        if owns_client:
            client.close()
