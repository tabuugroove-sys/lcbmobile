$ErrorActionPreference = "Stop"

$RepoDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $RepoDir ".venv\Scripts\python.exe"
$SecretsDir = Join-Path $RepoDir "secrets"

if (-not (Test-Path $Python)) {
    throw "Missing server virtualenv: $Python"
}

$env:PATH = "C:\ProgramData\chocolatey\bin;C:\Python311;C:\Python311\Scripts;$env:PATH"
$env:LOCAL_BACKUP_PYTHON = $Python
$env:RUNNER_ROLE = "server-primary"
$env:PUBLISH_SLOTS = "08:13=1,13:13=2,20:13=3"
$env:LOCAL_BACKUP_COOLDOWN_MINUTES = "15"
$env:TIMEZONE = "America/Sao_Paulo"
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

Set-Location $RepoDir
& $Python -m scripts.local_backup_runner
exit $LASTEXITCODE
