# LCBMobile handoff for another LLM

Updated: 2026-09-01, America/Sao_Paulo.

## Start here

- Source checkout: `/Users/a1111/Documents/Codex/2026-04-29/github/lcbmobile`
- Repository: `tabuugroove-sys/lcbmobile`
- Active branch: `claude/create-news-feed-yMBpb`
- Last verified source commit: `4494e45`
- Never print, commit or copy credential values into chat or logs.
- Recheck runtime state before making a current operational claim. A commit,
  successful task exit or dashboard row is not proof of a YouTube publication.

The project collects music-adjacent Brazilian entertainment news from RSS,
deduplicates and scores candidates, generates a narrated vertical Short and
publishes it through the YouTube Data API. Selection is intentionally kept near
music, musicians, DJs, concerts, releases and personal drama involving artists.

## Current ownership model

### 1. Windows server is primary for regular Shorts

- SSH alias: `capytime` (do not put the host IP in repository files).
- Runtime: `C:\lcbmobile-news`.
- Scheduled Task: `LCBMobile News Primary`, running as `SYSTEM`.
- The task polls every five minutes.
- Due slots: 08:13, 13:13 and 20:13 BRT.
- Expected channel counts after the slots: 1, 2 and 3 Shorts for that BRT day.
- Entrypoint: `scripts/run_server_primary.ps1`.
- Gate/orchestrator: `scripts/local_backup_runner.py`.
- Pipeline subprocess timeout: 2,700 seconds; timeout returns code `124`.
- Server deployment is a copied runtime, not a Git checkout. Do not assume
  `git pull` is available there; deploy changed runtime files explicitly.

Before rendering, the runner reads the authenticated YouTube uploads playlist.
If the expected number of Shorts already exists, it exits without publishing.
After upload, it polls YouTube and only records success when the count increases.

The server currently uses `REWRITE_PROVIDER=template`, because the Anthropic
credit balance and Gemini quota were unavailable during deployment. The
template writer uses only RSS title, summary and source; it is conservative but
less polished than an LLM rewrite.

Voice and mix configuration:

- `TTS_PROVIDER=elevenlabs`
- voice id: `pNInz6obpgDQGcFmaJgB`
- model: `eleven_multilingual_v2`
- stability `0.62`, similarity `0.78`, style `0.18`, speed `0.82`
- background track: `assets/audio/primeira_for_youtube.wav`
- background music volume: `0.25`

Secrets live under `C:\lcbmobile-news\secrets` with ACL restricted to
Administrator and SYSTEM. Never read their values into an answer. Daily logs
are under `C:\lcbmobile-news\logs`.

### 2. Mac is backup only

- LaunchAgent: `com.tabuugroove.lcbmobile.local-backup`.
- Installed runtime: `~/.local/share/lcbmobile-backup`.
- Poll interval: every five minutes.
- Backup slots: 08:28, 13:28 and 20:28 BRT, 15 minutes after primary.
- It uses the same real YouTube count gate and posts only when the server missed
  the required count.
- Rewrite provider: signed-in local Claude CLI.
- ElevenLabs key comes from macOS Keychain service
  `lcbmobile-elevenlabs-api`; never print it.
- Publisher is YouTube only. Telegram and Instagram are optional elsewhere.

After changing shared runtime code, run `scripts/install_local_backup.sh`. If
Codex sandboxing blocks `launchctl bootstrap`, run the bootstrap with explicit
system approval and verify `last exit code = 0`.

### 3. GitHub Actions is manual fallback for regular Shorts

`.github/workflows/pipeline.yml` has no `schedule`; it keeps only
`workflow_dispatch`. This prevents GitHub from racing the Windows primary.

Do not disable unrelated scheduled workflows without an explicit request:

- `daily-legal-multinews.yml`: daily horizontal Top 5 video.
- `comment-responder.yml`: YouTube comment replies.
- `dashboard.yml`: static analytics dashboard refresh.
- `looxx-suno-autopost.yml`: separate LOOXX/Suno publishing flow.

## Last proven end-to-end publication

Historical evidence, not a claim about the current moment:

- 2026-08-31 20:14 BRT: Windows server observed `2/3` expected Shorts.
- 2026-08-31 20:19 BRT: server upload succeeded with YouTube id
  `1I_1-sUsg5I`.
- Server then verified `3/3` from the uploads playlist.
- Mac subsequently observed `3/3` and skipped, proving the backup did not race.

## Verification commands

Server task state and logs:

```powershell
ssh capytime 'Get-ScheduledTask -TaskName "LCBMobile News Primary"'
ssh capytime 'Get-ScheduledTaskInfo -TaskName "LCBMobile News Primary"'
ssh capytime 'Get-Content C:\lcbmobile-news\logs\server-primary-$(Get-Date -Format yyyy-MM-dd).log -Tail 100'
```

Mac backup:

```bash
launchctl print gui/$(id -u)/com.tabuugroove.lcbmobile.local-backup
tail -80 ~/.local/share/lcbmobile-backup/data/local_backup.stderr.log
```

Repository and GitHub fallback:

```bash
git status --short
git log -5 --oneline --decorate
gh workflow view pipeline.yml --repo tabuugroove-sys/lcbmobile --yaml
```

For publication proof, find all of these together:

1. due-count trigger (`2/3`, for example),
2. successful publisher result with remote YouTube id,
3. post-upload verification showing the count increased,
4. YouTube uploads-playlist readback.

## Tests and known limits

- Local source verification after review fixes: `32/32` unit tests passed.
- Windows targeted verification: `9/9` scheduler/template tests passed.
- A clean Windows full `unittest discover` can fail the existing horizontal
  metadata test when generated `out/daily_legal_multinews/credits.txt` is not
  present. That fixture issue is unrelated to regular Shorts publishing.
- Server and Mac have separate SQLite databases. Cross-runtime duplicate safety
  therefore depends on the real YouTube count check and remote source URL sync,
  not on a shared local DB.
- Do not change voice, music level, schedule, publisher ownership or provider
  routing silently. Those are explicit product decisions.

## Safe update sequence

1. Inspect `git status` and preserve unrelated user changes.
2. Make narrowly scoped edits and add tests.
3. Run the local unit suite and `git diff --check`.
4. Commit and push the active branch.
5. Copy only changed runtime files to the matching server paths.
6. Run targeted Windows tests and inspect Scheduled Task result/logs.
7. Refresh the installed Mac backup runtime when shared files changed.
8. Verify the next real publication from YouTube, not only from process logs.

Related documentation: `docs/SERVER_PRIMARY.md` and
`docs/LOCAL_MAC_BACKUP.md`.
