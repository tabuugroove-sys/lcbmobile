param([switch]$Preflight, [switch]$DryRun)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = 'C:\lcbmobile-news'
Set-Location $root
$env:PYTHONUTF8 = '1'
$env:PATH = "C:\ProgramData\chocolatey\bin;C:\Python311;C:\Python311\Scripts;$env:PATH"
$env:CONTENT_LANG = 'pt-BR'
$env:TIMEZONE = 'America/Sao_Paulo'
$env:DB_PATH = "$root\data\state.db"
$env:OUTPUT_DIR = "$root\out"
$env:YOUTUBE_TOKEN_FILE = "$root\secrets\youtube_token.json"
$env:YOUTUBE_CLIENT_SECRET_FILE = "$root\secrets\client_secret.json"
$env:YOUTUBE_COOKIES_FILE = "$root\secrets\youtube_cookies.txt"
$env:YOUTUBE_EXPECTED_CHANNEL_ID = 'UC-TFUUc4YHleNoIFXBVaj7A'
$env:REWRITE_PROVIDER = 'template'
$env:ANALYTICS_ENABLED = 'true'
$env:ANALYTICS_HISTORY_LIMIT = '250'
$env:ANALYTICS_CANDIDATE_POOL = '60'
$env:FALLBACK_TO_YESTERDAY = 'true'
$env:TTS_PROVIDER = 'elevenlabs'
$env:ELEVENLABS_API_KEY = (Get-Content "$root\secrets\elevenlabs_api_key.txt" -Raw).Trim()
$env:ELEVENLABS_VOICE_ID = 'pNInz6obpgDQGcFmaJgB'
$env:ELEVENLABS_MODEL = 'eleven_multilingual_v2'
$env:ELEVENLABS_STABILITY = '0.62'
$env:ELEVENLABS_SIMILARITY = '0.78'
$env:ELEVENLABS_STYLE = '0.18'
$env:ELEVENLABS_SPEED = '0.82'
$env:BACKGROUND_MUSIC_PATH = "$root\assets\audio\primeira_for_youtube.wav"
$env:BACKGROUND_MUSIC_VOLUME = '0.25'
$env:BACKGROUND_MUSIC_DB_UNDER_VOICE = '0'
$env:MAC_MEDIA_ROOT = "$root\data\mac_media"
$env:MAC_MEDIA_WAIT_SECONDS = '240'
$env:MAC_MEDIA_TOTAL_WAIT_SECONDS = '900'
$env:MAC_MEDIA_HEARTBEAT_TTL_SECONDS = '900'
$env:RETRY_DELAY_SECONDS = '200'
foreach ($name in @('LCBAND_URGENT_BOT_TOKEN', 'LCBAND_URGENT_CHAT_ID', 'ESCALATION_BOT_TOKEN', 'ESCALATION_BOT_CHAT_ID')) {
    $path = "$root\secrets\$($name.ToLower()).txt"
    if (Test-Path $path) { [Environment]::SetEnvironmentVariable($name, (Get-Content $path -Raw).Trim()) }
}
$logs = "$root\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$flags = @('--scheduled')
if ($Preflight) { $flags = @('--preflight') }
if ($DryRun) { $flags = @('--no-publish') }
$logFile = "$logs\daily-music-news.log"
if ($Preflight -or $DryRun) { $logFile = "$logs\daily-music-news-check-$PID.log" }
$ErrorActionPreference = 'Continue'
try {
    & "$root\.venv\Scripts\python.exe" -m scripts.run_daily_music_news @flags *>> $logFile
    $code = $LASTEXITCODE
}
finally { $ErrorActionPreference = 'Stop' }
exit $code
