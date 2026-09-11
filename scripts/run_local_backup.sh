#!/bin/zsh
set -eu

SCRIPT_DIR="${0:A:h}"
REPO_DIR="${SCRIPT_DIR:h}"
ENV_FILE="${REPO_DIR}/.env.local"
PYTHON_BIN="/Users/a1111/lcbmobile/.venv/bin/python"

export PATH="/Users/a1111/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export LOCAL_BACKUP_PYTHON="${PYTHON_BIN}"

if [[ ! -f "${ENV_FILE}" ]]; then
  print -u2 "Missing ${ENV_FILE}"
  exit 2
fi

set -a
source "${ENV_FILE}"
set +a

export CONTENT_LANG="${CONTENT_LANG:-pt-BR}"
export DRAMA_SIGNAL_WEIGHT="${DRAMA_SIGNAL_WEIGHT:-1.8}"
export AUTO_CUTOUT_ENABLED="${AUTO_CUTOUT_ENABLED:-false}"
export REQUIRE_VISUAL_MEDIA="${REQUIRE_VISUAL_MEDIA:-true}"
export MIN_VISUAL_MEDIA_ASSETS="${MIN_VISUAL_MEDIA_ASSETS:-3}"

if [[ "${TTS_PROVIDER:-}" == "elevenlabs" && -z "${ELEVENLABS_API_KEY:-}" ]]; then
  ELEVENLABS_API_KEY="$(/usr/bin/security find-generic-password \
    -a lcbmobile \
    -s lcbmobile-elevenlabs-api \
    -w)"
  export ELEVENLABS_API_KEY
fi

cd "${REPO_DIR}"
exec "${PYTHON_BIN}" -m scripts.local_backup_runner
