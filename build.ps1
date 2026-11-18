# build.ps1 - Compila Voz y actualiza dist\voz\ sin tocar tus datos.
#
# PyInstaller compila en build\ (carpeta temporal). De ahi solo se copian
# voz.exe y _internal\ a dist\voz\. Lo que la app guarda junto al .exe
# nunca se toca, se copia ni se borra:
#   config.json       tu configuracion
#   data\             tus dictados y voz.log
#   models\whisper\   el modelo Whisper descargado (~1.5 GB)
#
# Uso:  .\build.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$stage = "build\dist\voz"
$dist  = "dist\voz"

Write-Host "== Compilando Voz ==" -ForegroundColor Cyan
python -m PyInstaller build.spec --noconfirm --distpath "build\dist" --workpath "build\work"
if ($LASTEXITCODE -ne 0) {
    Write-Host "LA COMPILACION FALLO - dist\voz no se ha tocado." -ForegroundColor Red
    exit $LASTEXITCODE
}

# Solo ahora, con el build bueno en la mano, se cierra la app si esta abierta
# (no se puede sustituir un voz.exe en uso).
$running = Get-Process -Name "voz" -ErrorAction SilentlyContinue
if ($running) {
    Write-Host "Cerrando voz.exe para poder actualizarlo..."
    $running | Stop-Process -Force
    Start-Sleep -Seconds 2
}

New-Item -ItemType Directory -Force -Path $dist | Out-Null
Copy-Item (Join-Path $stage "voz.exe") (Join-Path $dist "voz.exe") -Force

# /MIR deja _internal identico al recien compilado (tambien borra restos de
# versiones anteriores). robocopy devuelve 0-7 si todo fue bien.
robocopy (Join-Path $stage "_internal") (Join-Path $dist "_internal") /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "No se pudo copiar _internal (robocopy $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

Remove-Item "build" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "OK: dist\voz\voz.exe actualizado. Configuracion, dictados y modelo intactos." -ForegroundColor Green
Write-Host "Para compartirlo: .\empaquetar.ps1"
exit 0
