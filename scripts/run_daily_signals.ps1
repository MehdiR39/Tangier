# Daily Signals runner — Windows PowerShell
# Invoked by Task Scheduler once per weekday morning.

$ErrorActionPreference = "Stop"

# --- Config --------------------------------------------------------------
$ProjectRoot = "C:\tangier_L"
$LogDir      = Join-Path $ProjectRoot "logs"
$LogFile     = Join-Path $LogDir ("daily_" + (Get-Date -Format "yyyy-MM-dd") + ".log")

# --- Pre-flight checks ---------------------------------------------------
if (-not (Test-Path $ProjectRoot)) {
    Write-Error "Project directory not found: $ProjectRoot"
    exit 1
}

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

Set-Location $ProjectRoot

# --- Run via docker compose ----------------------------------------------
"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Starting daily signals..." |
    Tee-Object -FilePath $LogFile -Append

# `--rm` : auto-cleanup container after exit
# We pipe both stdout and stderr into the log file.
docker compose run --rm daily-signals 2>&1 |
    Tee-Object -FilePath $LogFile -Append

$exitCode = $LASTEXITCODE

"[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Exit code: $exitCode" |
    Tee-Object -FilePath $LogFile -Append

exit $exitCode
