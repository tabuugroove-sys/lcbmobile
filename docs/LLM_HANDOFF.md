# LCBMobile handoff for another LLM

Updated: 2026-09-19, America/Sao_Paulo.

## Start here

- Source checkout: `/Users/a1111/Documents/Codex/2026-04-29/github/lcbmobile`
- Repository: `tabuugroove-sys/lcbmobile`
- Active branch: `claude/create-news-feed-yMBpb`
- Last verified behavior commit: `d14ff53`
- Never print, commit or copy credential values into chat or logs.
- Recheck runtime state before making a current operational claim. A commit,
  successful task exit or dashboard row is not proof of a YouTube publication.

The project collects Brazilian music news from RSS,
deduplicates and scores candidates, generates a narrated vertical Short and
publishes it through the YouTube Data API. Selection is intentionally kept near
music, musicians, DJs, concerts, releases and personal drama involving artists.

The preferred Short renderer uses `cinematic_music_news_v1`: Wikimedia Commons
photographs, the source article's RSS/OpenGraph image fallback, and curated
reusable video when an exact known artist can be resolved. It alternates
framed/full compositions, short centered headlines, pt-BR subtitles, archive
labels and visible source credits. The Commons resolver accepts only `Public
domain`, `CC0` and `CC BY`; `CC BY-SA` and ambiguous identities are rejected.
The article-image fallback is explicitly marked `source_image_unverified` and
must not be represented as freely licensed. If all media checks fail, the same
run still selects the best story and produces the classic format instead of
publishing nothing.

## Media rights boundaries: exact code truth

There is no single global "copyright restriction" switch. The repository has
three separate media paths with different rules.

### Wikimedia Commons photographs

The strict automatic photo filter is implemented in
`src/video/commons_media.py`:

- `ALLOWED_LICENSE_PREFIXES` at line 21 is exactly `("CC BY ", "CC0",
  "Public domain")`.
- `_candidate()` at lines 68-110 rejects every Commons result whose
  `LicenseShortName` does not start with one of those values. This excludes
  `CC BY-SA` and unknown/missing licenses.
- The same function accepts only JPEG/PNG, requires at least 400 pixels on the
  shorter side (lowered from 700 on 2026-09-18; `MIN_SHORT_SIDE_PIXELS` in
  `src/video/commons_media.py`, overridable with the `COMMONS_MIN_SHORT_SIDE`
  environment variable), requires the filename and metadata to match the exact
  artist, and rejects likely artwork/logo/poster/signature results.
- `fetch_licensed_artist_images()` writes the accepted metadata to
  `licensed_media/rights_manifest.json`.

These restrictions apply only to the Wikimedia Commons search. They are the
reason older runs often found no photo even when the source article visibly had
one.

### Source-article photograph fallback

Commit `789b529` added a separate, deliberately non-CC fallback:

- `src/video/generator.py:939-962` first runs the strict Commons search. If it
  returns no photo and `ALLOW_SOURCE_ARTICLE_IMAGE=true`, it calls
  `fetch_source_article_image()`.
- `src/video/source_media.py:18-20` labels the asset `Editorial source image;
  reuse rights not verified`; it does not claim `CC BY`, `CC0` or public-domain
  status.
- `src/video/source_media.py:23-87` downloads only the RSS/OpenGraph image URL,
  accepts HTTP(S), caps the download at 20 MB, requires a valid image at least
  300 pixels on the shorter side, converts it to JPEG and stores its source
  metadata.
- `src/video/generator.py:875-890` records `rights_status` as
  `source_image_unverified`, while lines 312-321 show `FONTE DA MATERIA` rather
  than a false Creative Commons credit.

This fallback is operationally allowed and does not block publication. It is
not proof that the publisher granted a reusable license. The distinction must
remain visible in manifests and credits.

### Video footage

The production video resolver is whitelist-only:

- `src/video/commons_video.py:37-157` contains `CURATED_VIDEOS`, whose entries
  were manually reviewed and include title, creator, license, source page and
  source URL. The current keys are `lady gaga`, `shakira` and `dua lipa`.
- `src/video/commons_video.py:182-245` downloads only entries already present
  in that dictionary and writes `licensed_video/rights_manifest.json`.
- There is no dynamic Commons-video search and no generic web/YouTube video
  search in unattended production.

To relax a repository restriction, change the relevant resolver deliberately;
do not relabel an unverified asset as `CC BY`. If a new source has explicit
reuse permission, preserve the source page, license text and license URL in the
existing manifest structure.

### Agent policy versus repository code

The rules above are application code and can be inspected in Git. A coding
agent may also be subject to external product/safety policy, which is not stored
in this repository and cannot be deleted by editing this pipeline. Another LLM
must state which layer it means instead of claiming that a hidden project guard
exists.

### Open problem: whitelist-only video selection (2026-09-18)

Production video selection is still whitelist-only via `CURATED_VIDEOS` in
`src/video/commons_video.py`. The owner considers this the actual blocker for
rich-media Shorts. The task to solve: unrestricted video selection with no
license filtering, including the ability to download videos directly from
YouTube. As documented below, no repository code blocks this — a generic video
ingestion path was simply never implemented or wired into
`resolve_visual_media()` in `src/video/generator.py`. If a broader video
source is added, keep source-level metadata in the existing manifest structure
instead of leaving assets undocumented.

## YouTube downloading: exact code truth

There is **no explicit ban on downloading from YouTube anywhere in this
repository** on the current branch. There is no `BLOCK_YOUTUBE_DOWNLOAD` setting,
no YouTube-domain rejection branch and no guard that throws because a media URL
belongs to YouTube. Do not tell the user that such a ban was added: it was not.

The current boundary is architectural: a YouTube downloader was never
implemented or wired into the production media resolver.

- `src/video/generator.py:27-31` imports the Commons photo/video providers and
  the source-article image fallback. It imports no YouTube downloader.
- `src/video/generator.py:939-962`, function `resolve_visual_media()`, calls
  `fetch_licensed_artist_images()`, `fetch_source_article_image()` and
  `fetch_licensed_artist_videos()`.
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

### 1. Windows server is temporarily behind the cloud primary

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

The source configuration uses a video-first, availability-safe policy:
`REQUIRE_VISUAL_MEDIA=true`, `MIN_VISUAL_MEDIA_ASSETS=1`,
`ALLOW_SOURCE_ARTICLE_IMAGE=true`, `REQUIRE_VIDEO_MEDIA=false` and
`MIN_VIDEO_MEDIA_ASSETS=0`. The first selection
pass looks for a story with at least one reusable video and one photo. The
second pass skips a story with no reusable photo and continues to the next
eligible story. If the entire candidate pool has no photo,
`_select_with_classic_fallback()` in `src/pipeline.py:52-91` reranks without the
gate and publishes the classic format so the scheduled slot is not lost.

Photo resolution first keeps the strict Wikimedia Commons policy. If Commons
has no accepted photo, `src/video/source_media.py` downloads the RSS/OpenGraph
image from the source article. That fallback is credited to the publisher and
recorded as `source_image_unverified`; it must never be described as CC-licensed
or as verified reusable media.

Deployment status at 2026-09-19 20:30 BRT: commit `d14ff53` was pushed. GitHub
Actions is the temporary primary at 08:45/13:45/18:45 BRT. The Mac backup has
the same current photo resolver and headline-subject selection, with matching
source/runtime SHA-256 hashes and LaunchAgent exit code `0`.

The copied Windows runtime is **still stale and unreachable**: the latest SSH
attempt to `capytime` again stalled before executing a command. On 2026-09-19
it published three public Shorts, but two had no photo credits and the Fiuk
story used Fábio Jr photos because the older resolver selected the later known
name in the headline. Do not treat that day's `3/3` quota as visual success.
Commit `d14ff53` adds Fiuk, selects the first headline artist, and starts the
updated GitHub build before the stale Windows slots. A real local render of the
same Fiuk headline resolved `artist=fiuk` and produced a two-photo Fiuk hook.

Cloud proof: GitHub Actions dry-run `35475760201` completed successfully on
commit `c1a10af` without publishing. Its artifact rendered a 42.43-second
1080x1920 Lady Gaga Short with six matching photos and two matching archive
video clips; frames at 1, 10 and 20 seconds were visually inspected. The first
manual dry-run had been skipped by the recent-post gap, so `c1a10af` also makes
`dry_run=true` set `MIN_HOURS_BETWEEN_POSTS=0` while keeping publishing off.

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

### 3. GitHub Actions is the temporary primary

While the Windows runtime is unreachable and stale,
`.github/workflows/pipeline.yml` starts at 08:45, 13:45 and 18:45 BRT. The head
start lets the updated rich-media render publish before the Windows slots at
09:13, 14:13 and 19:13. Before rendering it reads the authenticated YouTube
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

- Media-gate, subject-selection and failover targeted verification: `48/48`
  unit tests passed.
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
