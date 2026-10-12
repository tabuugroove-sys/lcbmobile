$ErrorActionPreference = 'Stop'
$taskName = 'LCBMobile Shorts Completed Day Check'
$description = 'LCBMobile verified zero-Shorts completed-day check at 00:05 BRT'
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -ne $description) {
    throw 'A different task already owns the completed-day check name'
}
$next = [DateTime]::UtcNow.Date.AddHours(3).AddMinutes(5)
if ($next -le [DateTime]::UtcNow) { $next = $next.AddDays(1) }
$start = $next.ToString("yyyy-MM-ddTHH:mm:ss'Z'")
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>$description</Description></RegistrationInfo>
  <Triggers><CalendarTrigger>
    <Repetition><Interval>PT15M</Interval><Duration>PT1H</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    <StartBoundary>$start</StartBoundary><Enabled>true</Enabled>
    <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
  </CalendarTrigger></Triggers>
  <Principals><Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable><Enabled>true</Enabled><ExecutionTimeLimit>PT10M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="System"><Exec>
    <Command>C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe</Command>
    <Arguments>-NoProfile -NonInteractive -ExecutionPolicy Bypass -File C:\lcbmobile-news\scripts\run_server_primary.ps1</Arguments>
    <WorkingDirectory>C:\lcbmobile-news</WorkingDirectory>
  </Exec></Actions>
</Task>
"@
Register-ScheduledTask -TaskName $taskName -Xml $xml -User 'SYSTEM' -Force | Out-Null
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName, State, @{Name='StartUTC';Expression={$_.Triggers.StartBoundary}}
