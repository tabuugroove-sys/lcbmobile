"""Authorize the LOOXX channel and save an offline YouTube OAuth token."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402

from src.suno.youtube import SCOPES  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    parser.add_argument(
        "--output", type=Path, default=Path("looxx_youtube_token.json")
    )
    args = parser.parse_args()
    if not args.client_secret.exists():
        raise SystemExit(f"OAuth client file not found: {args.client_secret}")

    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secret), SCOPES)
    credentials = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )
    service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
    response = service.channels().list(part="id,snippet", mine=True).execute()
    channels = response.get("items", [])
    if not channels:
        raise SystemExit(
            "The selected Google account has no YouTube channel. "
            "Create the LOOXX channel first, then run this command again."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(credentials.to_json())
    args.output.chmod(0o600)
    channel = channels[0]
    print(f"Authorized channel: {channel['snippet']['title']} ({channel['id']})")
    print(f"Token saved securely to: {args.output.resolve()}")
    print("Upload it to GitHub without printing it:")
    print(
        "  gh secret set LOOXX_YOUTUBE_TOKEN "
        "-R tabuugroove-sys/lcbmobile < " + str(args.output)
    )


if __name__ == "__main__":
    main()
