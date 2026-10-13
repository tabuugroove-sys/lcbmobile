# Server comment responder

The Windows runtime is `C:\lcbmobile-news`. The scheduled task is
`LCBMobile Comment Responder`, using `scripts/run_server_comments.ps1` every
15 minutes. It is independent of news rendering and uses a global named mutex
plus the task's IgnoreNew setting to prevent overlapping local senders.

## Coverage and delivery

`COMMENT_SCAN_ALL=true` paginates published comment threads for the expected
channel, including old videos and all reply pages. Top-level comments and
viewer follow-ups enter a persistent FIFO queue in `data/comments.db`.
It does not approve held-for-review comments or reply to the channel itself.
Replies to follow-ups address their author within the top-level thread (the
YouTube API supports only one reply level).

Before sending, the agent rereads the thread and its complete reply list.
Existing channel replies suppress duplicate top-level replies. Addressed channel
replies newer than a follow-up suppress that follow-up. Successful insert IDs are
recorded in `replied_comments`; older GitHub replies are discovered remotely.
Missing, failed or ambiguous transport receipts never count as delivered.

The server sends up to 40 replies per run, with a five-second spacing. This is
a batch size, not a daily/history cutoff. Remaining work stays queued; there
is no per-video or daily policy limit in full-channel mode. YouTube quota and
rate limits still apply. A provider failure or quota error stops the batch
without losing pending comments. Permanent spam/abuse moderation decisions
are recorded as skipped. Ordinary criticism, short comments and meaningful
emoji reactions can receive replies.

## MiniMax

`COMMENT_REPLY_PROVIDER=minimax` uses the official Anthropic-compatible endpoint
`https://api.minimax.io/anthropic`, model `MiniMax-M2.5`. Responses are short,
contextual and emotional: enthusiasm for positive reactions, empathy for sad
news, light humor where appropriate. No invented facts, harassment, fabricated
personal experience or instructions from untrusted comment text.

The API key must be provisioned from the authorized Vault entry to
`secrets/minimax_api_key.txt`; it must never be committed or logged. Failure
to access Vault is a deployment blocker, not permission to copy secrets from
another application's files. The server runner uses MiniMax exclusively; it
does not silently switch back to Anthropic/Gemini.

## Cutover

1. Deploy responder source and scripts, preserving server files and backups.
2. Provision the authorized key and verify expected-channel OAuth scope.
3. Run `run_server_comments.ps1 -DryRun` and inspect generated samples.
4. Set GitHub variable `COMMENT_RUNNER=server`, push the workflow ownership
   guards, and disable the old standalone GitHub responder workflow.
5. Ensure no old GitHub sender is active before starting the server sender.
6. Install the Windows task and verify actual YouTube reply IDs plus DB rows.

Until cutover is complete, the old GitHub responder remains the owner. A
successful code test or task registration alone is not proof of live replies.
