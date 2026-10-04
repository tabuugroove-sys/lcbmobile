$ErrorActionPreference = 'Stop'
$start = [DateTime]::UtcNow.Date.AddHours(18).ToString("yyyy-MM-ddTHH:mm:ss'Z'")
$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>LCBMobile daily 16:9 music bulletin at 15:00 BRT, retry checks every 15 minutes. Shorts task is separate.</Description></RegistrationInfo>
  <Triggers><CalendarTrigger>
    <Repetition><Interval>PT15M</Interval><Duration>PT8H</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    <StartBoundary>$start</StartBoundary><Enabled>true</Enabled>
    <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
  </CalendarTrigger></Triggers>
  <Principals><Principal id="System"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled><ExecutionTimeLimit>PT2H30M</ExecutionTimeLimit>
  </Settings>
  <Actions Context="System"><Exec>
    <Command>C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe</Command>
    <Arguments>-NoProfile -ExecutionPolicy Bypass -File C:\lcbmobile-news\scripts\run_server_daily.ps1</Arguments>
    <WorkingDirectory>C:\lcbmobile-news</WorkingDirectory>
  </Exec></Actions>
</Task>
"@
Register-ScheduledTask -TaskName 'LCBMobile Daily Music News' -Xml $xml -User 'SYSTEM' -Force | Out-Null
Get-ScheduledTask -TaskName 'LCBMobile Daily Music News' | Select-Object TaskName, State
Get-ScheduledTaskInfo -TaskName 'LCBMobile Daily Music News' | Select-Object NextRunTime, LastTaskResult
