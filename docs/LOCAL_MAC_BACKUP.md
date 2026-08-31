# Local Mac publishing backup

This is the emergency path when the Windows primary publisher misses a slot.

## How it works

- macOS `launchd` starts `scripts/run_local_backup.sh` every five minutes.
- `scripts/local_backup_runner.py` reads the authenticated channel's uploads
  playlist through YouTube Data API.
- The runner expects 1/2/3 Shorts after 08:28, 13:28 and 20:28 BRT. These are
  15 minutes after the primary server slots.
- If the channel already has the expected count, it exits without rendering.
- If a Short is missing, it syncs recent source URLs into local SQLite, runs one
  pipeline item and verifies that a new Short actually appears on YouTube.
- A file lock prevents concurrent runs. Failed attempts have a 15-minute
  cooldown. The normal pipeline still performs up to five item attempts.

The local route uses the signed-in Claude CLI (`LOCAL_CLAUDE_FALLBACK=true`), so
it does not depend on Anthropic API credits or Gemini free-tier quota. Voiceover
uses the same ElevenLabs pt-BR profile as the cloud workflow; the API key is read
from macOS Keychain service `lcbmobile-elevenlabs-api`. It posts to YouTube only.
Telegram and Instagram remain optional cloud publishers.

Server operations are documented in [`SERVER_PRIMARY.md`](SERVER_PRIMARY.md).

## Local-only files

`.env.local`, `client_secret.json`, `youtube_token.json`, `data/` and `out/` are
gitignored. Never commit them.

The installed runtime lives at `~/.local/share/lcbmobile-backup`. It is outside
`Documents` because macOS privacy controls block background LaunchAgents from
reading that folder. The source repository remains the place to edit code.

## Operations

```bash
# Inspect status
launchctl print gui/$(id -u)/com.tabuugroove.lcbmobile.local-backup

# Install or refresh the persistent runtime after source changes
./scripts/install_local_backup.sh

# Run the gate once
~/.local/share/lcbmobile-backup/scripts/run_local_backup.sh

# Stop the backup
launchctl bootout gui/$(id -u)/com.tabuugroove.lcbmobile.local-backup

# Start it again
launchctl bootstrap gui/$(id -u) \
  ~/Library/LaunchAgents/com.tabuugroove.lcbmobile.local-backup.plist
```

Logs and last result:

```text
~/.local/share/lcbmobile-backup/data/local_backup.stdout.log
~/.local/share/lcbmobile-backup/data/local_backup.stderr.log
~/.local/share/lcbmobile-backup/data/local_backup_state.json
```
