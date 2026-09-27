"""One-shot OAuth flow to refresh youtube_token.json locally.

Run when the existing refresh token has been revoked or expired (Google
returns `invalid_grant`) or when adding permissions for comment replies. After
it succeeds, copy the resulting JSON into the YOUTUBE_TOKEN GitHub secret so the
GHA runner picks it up.

    python -m scripts.get_youtube_token
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow

# youtube.upload    -> publish Shorts (existing pipeline)
# youtube.force-ssl -> read commentThreads + post comment replies (responder)
# youtube.readonly  -> required by YouTube Analytics reports.query
# yt-analytics.readonly -> read views and subscribers gained per video
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CLIENT_SECRET = Path("client_secret.json")
TOKEN_FILE = Path("youtube_token.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-secret", type=Path, default=CLIENT_SECRET)
    parser.add_argument("--output", type=Path, default=TOKEN_FILE)
    args = parser.parse_args()

    if not args.client_secret.exists():
        print(f"ERROR: OAuth client file not found: {args.client_secret}")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secret), SCOPES)
    # access_type=offline + prompt=consent guarantees a refresh_token even when
    # this account already authorized an older (narrower) scope set.
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(creds.to_json())
    args.output.chmod(0o600)
    print(f"\nNew refresh token saved to {args.output.resolve()}")
    print("\nNow upload it as the YOUTUBE_TOKEN GitHub secret:")
    print(
        "  gh secret set YOUTUBE_TOKEN -R tabuugroove-sys/lcbmobile < "
        f"{args.output}"
    )


if __name__ == "__main__":
    main()
