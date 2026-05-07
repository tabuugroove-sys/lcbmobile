"""One-shot OAuth flow to refresh youtube_token.json locally.

Run when the existing refresh token has been revoked or expired (Google
returns `invalid_grant`). After it succeeds, copy the resulting JSON into
the YOUTUBE_TOKEN GitHub secret so the GHA runner picks it up.

    python -m scripts.get_youtube_token
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET = Path("client_secret.json")
TOKEN_FILE = Path("youtube_token.json")


def main() -> None:
    if not CLIENT_SECRET.exists():
        print(f"ERROR: {CLIENT_SECRET} not found in cwd. cd into ~/lcbmobile first.")
        sys.exit(1)

    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json())
    print(f"\n✅ New refresh token saved to {TOKEN_FILE.resolve()}")
    print("\nNow upload it as the YOUTUBE_TOKEN GitHub secret:")
    print(f"  gh secret set YOUTUBE_TOKEN -R tabuugroove-sys/lcbmobile < {TOKEN_FILE}")


if __name__ == "__main__":
    main()
