# build.ps1 — PyInstaller build for Voz WITHOUT losing runtime data.
#
# PyInstaller's COLLECT step deletes and recreates dist\voz\ entirely.
# Next to the .exe the app keeps runtime files you do NOT want to lose:
#   config.json          user settings
#   data\                dictations + voz.log
#   models\whisper\      downloaded Whisper model (~1.5 GB)
# This script closes a running app, snapshots those files, builds, and
# restores them into the fresh dist\voz\. The snapshot in .build-backup\
# is recreated from scratch each build and dropped after a successful
# restore, so the model never ends up duplicated on disk.

$ErrorActionPreference = "Stop"

Write-Host "== Voz build ==" -ForegroundColor Cyan

# 0) Close a running instance (else COLLECT fails on locked voz.exe)
$proc = Get-Process -Name "voz" -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "Closing running voz.exe..."
    $proc | Stop-Process -Force
    Start-Sleep -Seconds 2
}

# 1) Snapshot runtime files
$dist   = "dist\voz"
$backup = ".build-backup"
if (Test-Path $dist) {
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $backup | Out-Null
    foreach ($name in @("config.json", "data", "models")) {
        $src = Join-Path $dist $name
        if (Test-Path $src) {
            Write-Host "Backing up $name -> $backup"
            Copy-Item $src (Join-Path $backup $name) -Recurse -Force
        }
    }
}

# 2) Build
python -m PyInstaller build.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Host "BUILD FAILED - runtime files remain in .build-backup" -ForegroundColor Red
    exit $LASTEXITCODE
}

# 3) Restore runtime files into the fresh bundle
foreach ($name in @("config.json", "data", "models")) {
    $bak = Join-Path $backup $name
    if (Test-Path $bak) {
        Write-Host "Restoring $name -> $dist"
        $dst = Join-Path $dist $name
        if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
        Copy-Item $bak $dst -Recurse -Force
    }
}

# 4) Drop the snapshot once restored. Keeping models\ here would be a
#    ~1.5 GB duplicate of the live cache in dist\voz\models\.
if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }

Write-Host ""
Write-Host "OK: dist\voz\voz.exe rebuilt (config/data/models preserved)." -ForegroundColor Green
