$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $RepoDir ".venv\Scripts\python.exe"
$SecretsDir = Join-Path $RepoDir "secrets"
$LogsDir = Join-Path $RepoDir "logs"
$LogFile = Join-Path $LogsDir ("server-primary-{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

New-Item -ItemType Directory -Force $LogsDir | Out-Null
Start-Transcript -Path $LogFile -Append | Out-Null
$ExitCode = 1

try {

if (-not (Test-Path $Python)) {
    throw "Missing server virtualenv: $Python"
}

$env:PATH = "C:\ProgramData\chocolatey\bin;C:\Python311;C:\Python311\Scripts;$env:PATH"
$env:IMAGEMAGICK_BINARY = "C:\Program Files\ImageMagick-7.1.2-Q16-HDRI\magick.exe"
$env:LOCAL_BACKUP_PYTHON = $Python
$env:RUNNER_ROLE = "server-primary"
$env:PUBLISH_SLOTS = "09:13=1,14:13=2,19:13=3"
$env:LOCAL_BACKUP_COOLDOWN_MINUTES = "15"
$env:PIPELINE_TIMEOUT_SECONDS = "2700"
$env:TIMEZONE = "America/Sao_Paulo"
$env:CONTENT_LANG = "pt-BR"
$env:DRAMA_SIGNAL_WEIGHT = "1.8"
$env:AUTO_CUTOUT_ENABLED = "false"
$env:REQUIRE_VISUAL_MEDIA = "true"
$env:MIN_VISUAL_MEDIA_ASSETS = "1"
$env:ALLOW_SOURCE_ARTICLE_IMAGE = "true"
$env:REQUIRE_VIDEO_MEDIA = "false"
$env:MIN_VIDEO_MEDIA_ASSETS = "0"
$env:REWRITE_PROVIDER = "template"
$env:TTS_PROVIDER = "elevenlabs"
$env:ELEVENLABS_VOICE_ID = "pNInz6obpgDQGcFmaJgB"
$env:ELEVENLABS_MODEL = "eleven_multilingual_v2"
$env:ELEVENLABS_STABILITY = "0.62"
$env:ELEVENLABS_SIMILARITY = "0.78"
$env:ELEVENLABS_STYLE = "0.18"
$env:ELEVENLABS_SPEED = "0.82"
$env:BACKGROUND_MUSIC_PATH = "assets/audio/primeira_for_youtube.wav"
$env:BACKGROUND_MUSIC_VOLUME = "0.25"
$env:OPTIONAL_PUBLISHERS = "telegram,instagram"
$env:YOUTUBE_TOKEN_FILE = Join-Path $SecretsDir "youtube_token.json"
$env:YOUTUBE_CLIENT_SECRET_FILE = Join-Path $SecretsDir "client_secret.json"
$env:DB_PATH = Join-Path $RepoDir "data\state.db"
$env:OUTPUT_DIR = Join-Path $RepoDir "out"
$env:ELEVENLABS_API_KEY = (Get-Content (Join-Path $SecretsDir "elevenlabs_api_key.txt") -Raw).Trim()

$OptionalSecrets = @{
    "LCBAND_URGENT_BOT_TOKEN" = "lcband_urgent_bot_token.txt"
    "LCBAND_URGENT_CHAT_ID" = "lcband_urgent_chat_id.txt"
    "ESCALATION_BOT_TOKEN" = "escalation_bot_token.txt"
    "ESCALATION_BOT_CHAT_ID" = "escalation_bot_chat_id.txt"
    "LCBAND_NOTIFY_BOT_TOKEN" = "lcband_notify_bot_token.txt"
    "LCBAND_NOTIFY_CHAT_ID" = "lcband_notify_chat_id.txt"
}
foreach ($Name in $OptionalSecrets.Keys) {
    $SecretFile = Join-Path $SecretsDir $OptionalSecrets[$Name]
    if (Test-Path $SecretFile) {
        Set-Item -Path "Env:$Name" -Value (Get-Content $SecretFile -Raw).Trim()
    }
}

Set-Location $RepoDir
& $Python -m scripts.local_backup_runner
$ExitCode = $LASTEXITCODE
}
catch {
    Write-Error $_
    $ExitCode = 1
}
finally {
    Stop-Transcript | Out-Null
}

exit $ExitCode
