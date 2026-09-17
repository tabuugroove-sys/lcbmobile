#!/bin/zsh
set -eu

SOURCE_DIR="${0:A:h:h}"
RUNTIME_DIR="/Users/a1111/.local/share/lcbmobile-backup"
AGENT_FILE="/Users/a1111/Library/LaunchAgents/com.tabuugroove.lcbmobile.local-backup.plist"
LABEL="com.tabuugroove.lcbmobile.local-backup"

mkdir -p "${RUNTIME_DIR}" "${AGENT_FILE:h}"
rsync -a --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude '.env.local' \
  --exclude 'client_secret*.json' \
  --exclude 'youtube_token.json' \
  --exclude 'data/' \
  --exclude 'out/' \
  "${SOURCE_DIR}/" "${RUNTIME_DIR}/"

mkdir -p "${RUNTIME_DIR}/data" "${RUNTIME_DIR}/out"
for secret in .env.local client_secret.json youtube_token.json; do
  if [[ -f "${SOURCE_DIR}/${secret}" ]]; then
    cp "${SOURCE_DIR}/${secret}" "${RUNTIME_DIR}/${secret}"
  elif [[ ! -f "${RUNTIME_DIR}/${secret}" ]]; then
    print -u2 "Missing required secret in source and runtime: ${secret}"
    exit 2
  fi
done
cp "${SOURCE_DIR}/ops/${LABEL}.plist" "${AGENT_FILE}"
chmod 600 \
  "${RUNTIME_DIR}/.env.local" \
  "${RUNTIME_DIR}/client_secret.json" \
  "${RUNTIME_DIR}/youtube_token.json"
chmod +x \
  "${RUNTIME_DIR}/scripts/run_local_backup.sh" \
  "${RUNTIME_DIR}/scripts/install_local_backup.sh"

launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "${AGENT_FILE}"
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "Installed ${LABEL} in ${RUNTIME_DIR}"
