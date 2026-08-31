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

cd "${REPO_DIR}"
exec "${PYTHON_BIN}" -m scripts.local_backup_runner
