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

# 3) Restore runtime files into the fresh bundle.
#    robocopy /MIR is used instead of Copy-Item: if dist\voz\<name> somehow
#    survived COLLECT (e.g. the app was running and held file locks),
#    Copy-Item would nest the copy (models\models\...) while robocopy
#    mirrors the backup deterministically and never nests.
foreach ($name in @("config.json", "data", "models")) {
    $bak = Join-Path $backup $name
    if (Test-Path $bak) {
        Write-Host "Restoring $name -> $dist"
        $dst = Join-Path $dist $name
        if ($name -eq "config.json") {
            Copy-Item $bak $dst -Force
        } else {
            robocopy $bak $dst /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS | Out-Null
            if ($LASTEXITCODE -ge 8) {
                Write-Host "robocopy failed for $name (exit $LASTEXITCODE)" -ForegroundColor Red
                exit 1
            }
        }
    }
}

# 4) Safety net: detect and fix a nested models\models left over when the
#    app was running during the build (COLLECT could not wipe dist\voz).
$nested = Join-Path $dist "models\models"
if (Test-Path $nested) {
    Write-Host "Detected nested models\models (app running during build?) - fixing..." -ForegroundColor Yellow
    if (-not (Test-Path (Join-Path $dist "models\whisper"))) {
        # Real cache lost: adopt the nested copy instead of re-downloading.
        Move-Item $nested (Join-Path $dist "models\whisper")
        Write-Host "Adopted nested model as dist\voz\models\whisper" -ForegroundColor Yellow
    } else {
        Remove-Item $nested -Recurse -Force
        Write-Host "Removed nested duplicate model" -ForegroundColor Yellow
    }
}

# 5) Drop the snapshot once restored. Keeping models\ here would be a
#    ~1.5 GB duplicate of the live cache in dist\voz\models\.
if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }

# 6) Auditability: surface any build warnings about excluded modules
#    (a real importer appearing here means the exclusion must be reverted),
#    then drop the PyInstaller work dir (regenerated on every build,
#    ~70 MB saved).
$warn = Join-Path "build\voz" "warn-voz.txt"
if (Test-Path $warn) {
    $pandasWarn = Select-String -Path $warn -Pattern "pandas" -SimpleMatch | Select-Object -First 2
    if ($pandasWarn) {
        Write-Host "WARNING: excluded 'pandas' is referenced by the build:" -ForegroundColor Yellow
        foreach ($w in $pandasWarn) { Write-Host "  $($w.Line)" -ForegroundColor Yellow }
        Write-Host "-> revierte el excludes de pandas en build.spec si esto persiste." -ForegroundColor Yellow
    } else {
        Write-Host "pandas exclusion clean (no build warnings)." -ForegroundColor Green
    }
}
if (Test-Path "build") { Remove-Item "build" -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "OK: dist\voz\voz.exe rebuilt (config/data/models preserved)." -ForegroundColor Green
