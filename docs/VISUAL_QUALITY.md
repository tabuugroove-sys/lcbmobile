# Shorts visual quality

The 2026-10-16 incident had three separate causes: the first Commons image
was always reused as the cover, the fixed five-scene layout created empty
scenes when only two photos existed, and downloaded-video caches did not
verify that their metadata named the story's artist. Renato Russo was also
absent from headline artist discovery, so the optional Mac was never asked
to fetch his footage.

## Current checks

- Scene layouts are built from actual available assets. Zero-image templates
  cannot be selected or rendered. A genuine single-photo fallback stays a
  single image; its existing urgent alert remains in effect.
- Photos and video source URLs from the last 12 successful YouTube Shorts
  within 72 hours are excluded from a new story. Dry-run folders are not
  publication history. Older manifests are read from their cached asset lists.
  New manifests contain photo assets, video source URLs and the actual layout.
- Dedup uses normalized source identity and perceptual image hashes. Changing
  a filename or image size does not make a photo editorially new.
- YouTube results and Mac caches must name the requested performer in title
  or uploader metadata. Known namesakes such as Leonardo da Vinci/Jardim and
  Joao Gomes Cravinho are excluded. This is metadata screening, not biometric
  identity verification.
- A performer and their own band are not an opponent pair: Renato Russo vs
  Legiao Urbana does not justify a question-mark split cover.
- Video sources with identical file hashes are not repeated within a Short.
  Scenes cannot be extended beyond the available footage as a frozen frame.
- When photos are scarce, one clear-face still can be extracted from each
  selected video. Keeping only the first usable still reduces interviewer
  close-ups being mistaken for additional artist photos. Face detection alone
  does not identify a person; editorial/visual review is still important.
- Each output is decoded for black intervals and gets `visual_qa.json` plus
  `visual_review.jpg` sampled from the actual MP4, not placeholder scene JPGs.

## Mac fallback

The cloud first tries its curated sources and YouTube; the outbound-only Mac
worker is a backup. Worker heartbeat and per-artist requests are under
`C:\lcbmobile-news\data\mac_media`. Verified existing clips remain usable when
the Mac is offline. No incoming SSH service on the Mac is required.

Short excerpts may come from interviews up to two hours long. If a bounded
range download fails for a long interview, it is not silently replaced with
a download of the entire interview. The server can wait up to 240 seconds
for one Mac request, with a 900-second total request budget per process.

Source licenses remain recorded honestly. These changes add no new licensing
restriction and do not treat standard YouTube uploads as CC-licensed.

## Verification

Use `tests/test_visual_quality.py` plus the cinematic, YouTube, Mac, music
filter and pipeline tests. A real mixed-media Renato Russo preview is under
`out/visual-quality-2026-10-16`. Preview generation must not publish or alter
existing public uploads. Inspect the final contact sheet and video before
calling a new edit accepted.
