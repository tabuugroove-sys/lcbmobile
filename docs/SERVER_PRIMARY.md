# Windows server primary publisher

The primary Shorts runtime is deployed at `C:\lcbmobile-news` on the configured
Windows publishing host. It is isolated from the LCBand services on that host.

## Schedule and ownership

- Windows Scheduled Task: `LCBMobile News Primary`
- Account: `NT AUTHORITY\SYSTEM`
- Poll interval: every five minutes
- Pipeline timeout: 45 minutes
- Due slots in `America/Sao_Paulo`: 08:13, 13:13 and 20:13
- Expected daily count after each slot: 1, 2 and 3 Shorts
- Mac backup checks the same channel 15 minutes later at 08:28, 13:28 and 20:28
- GitHub `pipeline.yml` has no cron; it remains a manual cloud fallback

The server checks the real YouTube uploads playlist before rendering. If the
expected count is already present, it exits successfully. This prevents races
with a manual run or the Mac backup.

## Runtime

- Python: `C:\lcbmobile-news\.venv\Scripts\python.exe`
- Entrypoint: `C:\lcbmobile-news\scripts\run_server_primary.ps1`
- State: `C:\lcbmobile-news\data\state.db`
- Daily logs: `C:\lcbmobile-news\logs\server-primary-YYYY-MM-DD.log`
- Rendered files: `C:\lcbmobile-news\out`
- Secrets: `C:\lcbmobile-news\secrets` (ACL limited to Administrator and SYSTEM)

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
