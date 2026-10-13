param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = 'C:\lcbmobile-news'
Set-Location $root
$env:PYTHONUTF8 = '1'
$env:YOUTUBE_TOKEN_FILE = "$root\secrets\youtube_token.json"
$env:YOUTUBE_CLIENT_SECRET_FILE = "$root\secrets\client_secret.json"
$env:YOUTUBE_EXPECTED_CHANNEL_ID = 'UC-TFUUc4YHleNoIFXBVaj7A'
$env:COMMENTS_DB_PATH = "$root\data\comments.db"
$env:COMMENT_REPLY_PROVIDER = 'minimax'
$env:COMMENT_MINIMAX_MODEL = 'MiniMax-M2.5'
$env:MINIMAX_BASE_URL = 'https://api.minimax.io/anthropic'
$env:MINIMAX_API_KEY = (Get-Content "$root\secrets\minimax_api_key.txt" -Raw).Trim()
$env:COMMENT_SCAN_ALL = 'true'
$env:COMMENT_MAX_PER_RUN = '40'
$env:COMMENT_REPLY_DELAY_SECONDS = '5'
$env:COMMENT_DRY_RUN = 'false'
New-Item -ItemType Directory -Force "$root\logs" | Out-Null
$mutex = New-Object System.Threading.Mutex($false, 'Global\LCBMobileCommentResponder')
$held = $false
try {
    try { $held = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $held = $true }
    if (-not $held) { exit 0 }
    $flags = @()
    if ($DryRun) { $flags += '--dry-run' }
    & "$root\.venv\Scripts\python.exe" -m scripts.reply_comments @flags *>> "$root\logs\comment-responder.log"
    $code = $LASTEXITCODE
} finally {
    if ($held) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
    Remove-Item Env:MINIMAX_API_KEY -ErrorAction SilentlyContinue
}
exit $code
