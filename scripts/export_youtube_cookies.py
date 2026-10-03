"""Export only the explicitly authorized YouTube session from local Chrome."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
from uuid import uuid4

from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser


def export_youtube_cookies(destination: Path, profile: str = "Profile 1") -> int:
    browser_cookies = extract_cookies_from_browser("chrome", profile=profile)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    youtube_cookies = YoutubeDLCookieJar(str(temporary))
    for cookie in browser_cookies:
        domain = cookie.domain.lstrip(".").lower()
        if domain == "youtube.com" or domain.endswith(".youtube.com"):
            youtube_cookies.set_cookie(cookie)
    if not len(youtube_cookies):
        raise RuntimeError("The selected Chrome profile has no YouTube cookies")
    try:
        youtube_cookies.save(ignore_discard=True, ignore_expires=False)
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return len(youtube_cookies)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", default="Profile 1")
    args = parser.parse_args()
    count = export_youtube_cookies(args.output, args.profile)
    print(f"Saved {count} YouTube-only cookies; values are not logged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
