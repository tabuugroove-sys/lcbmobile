# Windows server primary publisher

The primary Shorts runtime is deployed at `C:\lcbmobile-news` on the configured
Windows publishing host. It is isolated from the LCBand services on that host.

## Schedule and ownership

- Windows Scheduled Task: `LCBMobile News Primary`
- Account: `NT AUTHORITY\SYSTEM`
- Poll interval: every five minutes
- Pipeline timeout: 45 minutes
- Due slots in `America/Sao_Paulo`: 09:13, 14:13 and 19:13
- Expected daily count after each slot: 1, 2 and 3 Shorts
- Mac backup checks the same channel 15 minutes later at 09:28, 14:28 and 19:28
- GitHub Actions independently checks the live YouTube quota one hour later at
  10:13, 15:13 and 20:13 BRT. It uses the reliable pre-cinematic renderer only
  when the Windows server still has not delivered the expected Short.
- A failed verified publication sends one audible urgent-bot alert per missed
  quota milestone. Retries continue on schedule after the alert.

The server checks the real YouTube uploads playlist before rendering. If the
expected count is already present, it exits successfully. This prevents races
with a manual run or the Mac backup.

The opening curiosity frame must contain two different visual roles: the main
subject on the left and a named opponent, colleague, audience or event context
on the right. It may use distinct images from the source article when Commons
does not provide both roles. A single image is never duplicated across both
halves; the safe fallback is one photo plus an editorial teaser panel.

## Runtime

- Python: `C:\lcbmobile-news\.venv\Scripts\python.exe`
- Entrypoint: `C:\lcbmobile-news\scripts\run_server_primary.ps1`
- State: `C:\lcbmobile-news\data\state.db`
- Daily logs: `C:\lcbmobile-news\logs\server-primary-YYYY-MM-DD.log`
- Rendered files: `C:\lcbmobile-news\out`
- Secrets: `C:\lcbmobile-news\secrets` (ACL limited to Administrator and SYSTEM)

Urgent notifications use `LCBAND_URGENT_BOT_TOKEN` and
`LCBAND_URGENT_CHAT_ID`, with the escalation and notify bots as fallbacks. On
Windows these values are loaded from matching lowercase files in `secrets`.

The primary uses the configured ElevenLabs pt-BR voice. Until a funded cloud AI
key is available, `REWRITE_PROVIDER=template` builds a conservative Portuguese
script only from the RSS title, summary and source. It does not invent facts.

## Checks

```powershell
Get-ScheduledTask -TaskName "LCBMobile News Primary"
Get-ScheduledTaskInfo -TaskName "LCBMobile News Primary"
Start-ScheduledTask -TaskName "LCBMobile News Primary"
Get-Content C:\lcbmobile-news\logs\server-primary-$(Get-Date -Format yyyy-MM-dd).log -Tail 80
```

Do not copy secret values into logs, commits or support messages.
