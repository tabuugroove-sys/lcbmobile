# LCBMobile handoff for another LLM

Updated: 2026-09-17, America/Sao_Paulo.

## Start here

- Source checkout: `/Users/a1111/Documents/Codex/2026-04-29/github/lcbmobile`
- Repository: `tabuugroove-sys/lcbmobile`
- Active branch: `claude/create-news-feed-yMBpb`
- Last verified behavior commit: `7654b08`
- Never print, commit or copy credential values into chat or logs.
- Recheck runtime state before making a current operational claim. A commit,
  successful task exit or dashboard row is not proof of a YouTube publication.

The project collects Brazilian music news from RSS,
deduplicates and scores candidates, generates a narrated vertical Short and
publishes it through the YouTube Data API. Selection is intentionally kept near
music, musicians, DJs, concerts, releases and personal drama involving artists.

The preferred Short renderer uses `cinematic_music_news_v1`: verified
Wikimedia Commons photographs and curated reusable video when an exact known
artist can be resolved, alternating framed/full compositions, short centered
headlines, pt-BR subtitles, archive labels and a visible Creative Commons
credit on the final scene. Only `Public domain`, `CC0` and `CC BY` media are
accepted automatically; `CC BY-SA`, unclear rights and ambiguous identities
are rejected. If the strict media check rejects every eligible story, the same
run automatically selects the best story again and produces the classic format
instead of publishing nothing.

## YouTube downloading: exact code truth

There is **no explicit ban on downloading from YouTube anywhere in this
repository** at commit `9ce3db1`. There is no `BLOCK_YOUTUBE_DOWNLOAD` setting,
no YouTube-domain rejection branch and no guard that throws because a media URL
belongs to YouTube. Do not tell the user that such a ban was added: it was not.

The current boundary is architectural: a YouTube downloader was never
implemented or wired into the production media resolver.

- `src/video/generator.py:28-29` imports only the licensed image and video
  providers from `commons_media` and `commons_video`.
- `src/video/generator.py:929-948`, function `resolve_visual_media()`, calls only
  `fetch_licensed_artist_images()` and `fetch_licensed_artist_videos()`.
- `src/video/commons_video.py:37-39` defines the reviewed whitelist
  `CURATED_VIDEOS` and explicitly excludes dynamic video search from unattended
  production.
- `src/video/commons_video.py:182-245`, function
  `fetch_licensed_artist_videos()`, downloads only URLs already present in that
  whitelist and writes a rights manifest.
- `requirements.txt:1-22` contains neither `yt-dlp` nor `youtube-dl`.

Therefore, the precise answer to "where was the prohibition added?" is:
**nowhere**. Production is currently whitelist-only, not because code blocks
YouTube, but because no arbitrary-YouTube ingestion path exists.

The reason it was not implemented is rights and channel risk, not a technical
limitation. The user's permission cannot grant rights held by the owner of a
third-party upload. YouTube states that even a few seconds can create copyright
issues, that adding original material does not automatically make a use fair,
and that fair use is ultimately decided by courts. A Content ID claim can
block, monetize or track a video; a valid copyright removal request creates a
strike, and three active strikes in 90 days can subject a channel to
termination. Deleting a video normally does not remove an existing strike.

Official references:

- https://support.google.com/youtube/answer/2797449?hl=en
- https://support.google.com/youtube/answer/9783148?hl=en-on
- https://support.google.com/youtube/answer/7002106?hl=en
- https://support.google.com/youtube/answer/2814000?hl=en

This is why the implemented availability strategy is "licensed rich media when
available, classic format otherwise", rather than automatically downloading
unlicensed YouTube uploads. A future agent may add a YouTube-source adapter for
media that the user owns, has explicit permission to download and reuse, or can
prove is published under compatible reuse terms. Such an adapter should require
source-level rights evidence and preserve it in the existing manifest; it
should not infer permission merely from clip length, cropping, subtitles,
voiceover or editing.

## Current ownership model

### 1. Windows server is primary for regular Shorts

- SSH alias: `capytime` (do not put the host IP in repository files).
- Runtime: `C:\lcbmobile-news`.
- Scheduled Task: `LCBMobile News Primary`, running as `SYSTEM`.
- The task polls every five minutes.
- Due slots: 09:13, 14:13 and 19:13 BRT.
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

Editorial ranking keeps the music filter as a hard gate and then combines
historical YouTube reaction, freshness, a known-artist signal and confirmed
drama terms. Server `DRAMA_SIGNAL_WEIGHT=1.8`. Drama can change priority and
the factual hook; it must never invent or intensify an unsupported claim.

The source configuration uses a photo-first, availability-safe policy:
`REQUIRE_VISUAL_MEDIA=true`, `MIN_VISUAL_MEDIA_ASSETS=1`,
`REQUIRE_VIDEO_MEDIA=false` and `MIN_VIDEO_MEDIA_ASSETS=0`. The first selection
pass skips a story with no reusable photo and continues to the next eligible
story. Video is optional. If the entire candidate pool has no photo,
`_select_with_classic_fallback()` in `src/pipeline.py:52-80` reranks without the
gate and publishes the classic format so the scheduled slot is not lost.

Deployment status at 2026-09-17 15:31 BRT: commit `7654b08` was pushed and the
Mac backup runtime has the photo-first defaults with LaunchAgent exit code `0`.
The copied Windows runtime is **not yet verified or updated** because both SSH
attempts to `capytime` timed out during banner exchange. Reconnect, copy
`src/config.py` and `scripts/run_server_primary.ps1`, then inspect the four
effective environment values before claiming Windows deployment.

Automatic GrabCut is present only as an experimental path and remains disabled
with `AUTO_CUTOUT_ENABLED=false`; automated masking was rejected in QA when a
concert crowd could be mistaken for a subject. Framed-photo fallback is the
current production-safe behavior.

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
- Backup slots: 09:28, 14:28 and 19:28 BRT, 15 minutes after primary.
- It uses the same real YouTube count gate and posts only when the server missed
  the required count.
- Rewrite provider: signed-in local Claude CLI.
- ElevenLabs key comes from macOS Keychain service
  `lcbmobile-elevenlabs-api`; never print it.
- Publisher is YouTube only. Telegram and Instagram are optional elsewhere.

After changing shared runtime code, run `scripts/install_local_backup.sh`. If
Codex sandboxing blocks `launchctl bootstrap`, run the bootstrap with explicit
system approval and verify `last exit code = 0`.

### 3. GitHub Actions is the independent last-resort fallback

`.github/workflows/pipeline.yml` runs at 10:13, 15:13 and 20:13 BRT, one hour
after the Windows slots. Before rendering it reads the authenticated YouTube
uploads playlist and compares today's real Short count with the expected 1/2/3
quota. A met quota is a no-op. A missing quota uses YouTube only, disables the
strict `3 photos + 2 videos` gate and renders the reliable graphic/photo mode.
The workflow verifies the channel again after upload and pages the urgent bot
if the quota is still missing. Manual `workflow_dispatch` remains available.

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

- Media-gate and failover targeted verification: `34/34` unit tests passed.
- `tests/test_pipeline_classic_publish.py` forces zero photo/video assets and
  proves that the pipeline still calls the YouTube publisher and records a
  successful remote id. A separate real render with the same zero-media setup
  produced an H.264/AAC 1080x1920 MP4 lasting 8.97 seconds, confirming that the
  classic renderer itself does not depend on media assets.
- Cinematic/selection targeted verification on 2026-09-11: `21/21` passed;
  the pt-BR dry-run rendered six licensed images at 1080x1920, 30 fps, 30 s.
- Windows targeted verification: `9/9` scheduler/template tests passed.
- A clean Windows full `unittest discover` can fail the existing horizontal
  metadata test when generated `out/daily_legal_multinews/credits.txt` is not
  present. That fixture issue is unrelated to regular Shorts publishing.
- The local full discovery reached 64 tests but also could not import the
  YouTube publisher test because `python-telegram-bot` is absent from the local
  interpreter. The targeted media-gate suite does not depend on that package.
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
