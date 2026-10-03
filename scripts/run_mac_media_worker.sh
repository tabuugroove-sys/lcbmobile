#!/bin/zsh
set -eu
REPO_DIR="${0:A:h:h}"
export PATH="/Users/a1111/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export YOUTUBE_COOKIES_FILE="${REPO_DIR}/secrets/youtube_cookies.txt"
export MAC_MEDIA_CHROME_PROFILE="Profile 1"
cd "${REPO_DIR}"
exec /Users/a1111/lcbmobile/.venv/bin/python -m scripts.mac_media_worker
