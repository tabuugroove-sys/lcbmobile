# Long-form graphics rollout

Approved by the user on 2026-11-09 for future daily 16:9 bulletins.
Shorts, topic ranking, upload deduplication, music and schedules are unchanged.

## Runtime

`LONGFORM_PLANNER=beats` selects source-aware sentence editing in
`src/video/horizontal_news.py`. The Windows daily wrapper and the GitHub daily
fallback configure this flag. Unset it or set `legacy` to return to the previous
renderer. A legacy render cannot satisfy a beats cache check.
Chapter boundaries share a single narration frame clock, preventing accumulated
rounding from adding a tail across four or five stories. The timing policy is
included in the final-render cache digest.

The style combines source-article photos, reviewed artist footage, animated
editorial text, and optional numeric fact graphics. Each shot records its role
and provenance in `editorial-plan.json` and `timeline.json`. Artist-name matching
does not prove that footage depicts the specific event. Sensitive-topic keyword
checks suppress generic archive footage; they are not semantic verification.

## Numeric graphics

Numeric cards require explicit reviewed `story.infographics` entries. Automatic
number extraction is NOT enabled. Do not claim that every unattended bulletin
will contain numeric charts. Without these entries, the sentence editor still
uses the animated typography style, photos and footage.

Each entry supplies `value`, `unit`, `block_value`, `evidence_quote`,
`source_page`, and optionally `approximate`. The source URL must match the story;
the exact evidence must appear once in both narration and voice alignment.
Only supported units and positive whole-number counts are accepted. At most two
existing 2-4-second shots per story are replaced; narration is never extended.
Invalid facts are skipped. Editorial review must verify the claim itself:
runtime validation checks anchors, not semantic truth.

## Verification and rollback

Use `scripts/preview_longform_beats.py` with a new output directory to re-edit
saved narration without publishing or buying new voice generation. Inspect the
contact sheet and sampled animation frames in addition to automated QA.
Historical previews must not be published as current news.

Release artifacts and before-copies are stored under
`out/infographic-deploy-20261109` on the server. Activation is gated on a complete
server render and passing tests. The wrapper is installed last; SHA-256 checks
reject changed staging files or concurrent production edits.

Rollback the daily wrapper to its before-copy first. Leaving the new renderer
modules installed is safe with `LONGFORM_PLANNER=legacy`; this does not revert
unrelated Shorts or analytics changes. No SSH, RDP or Scheduled Task settings
need to be modified.

## Review findings

The November 8 production fixture exposed a pre-existing identity mismatch:
the story about Priscilla Monroy carries `artist=priscilla` and footage of the
singer Priscilla. The graphics rollout does not fix artist entity resolution.
The fixture is an unpublished re-edit for technical verification, not a new
editorial approval or a candidate for republication. Automated decode, timing
and layout checks must not be presented as a semantic footage review.
