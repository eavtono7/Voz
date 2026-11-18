# empaquetar.ps1 - Crea dist\Voz.zip listo para enviar a otra persona.
#
# El zip lleva solo el programa (voz.exe + _internal\). NUNCA incluye lo
# tuyo: ni tus dictados (data\), ni tu configuracion (config.json).
# Quien lo reciba descomprime, abre voz\voz.exe y el modelo se descarga
# solo la primera vez (~1.5 GB).
#
# Uso:
#   .\empaquetar.ps1              zip pequeno, sin el modelo
#   .\empaquetar.ps1 -ConModelo   zip grande, funciona sin internet

param([switch]$ConModelo)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path "dist\voz\voz.exe")) {
    Write-Host "No existe dist\voz\voz.exe. Ejecuta primero .\build.ps1" -ForegroundColor Red
    exit 1
}

$zip = "dist\Voz.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

$excluir = @("--exclude", "voz/data", "--exclude", "voz/config.json")
if (-not $ConModelo) { $excluir += @("--exclude", "voz/models") }

Write-Host "== Empaquetando Voz ==" -ForegroundColor Cyan
tar.exe -a -c -f $zip -C dist @excluir voz
if ($LASTEXITCODE -ne 0) {
    Write-Host "No se pudo crear el zip (tar $LASTEXITCODE)." -ForegroundColor Red
    exit 1
}

# Red de seguridad: si algo personal se colara en el zip, se borra y se avisa.
$personal = tar.exe -t -f $zip | Select-String -Pattern "^voz/(data/|config\.json)"
if ($personal) {
    Remove-Item $zip -Force
    Write-Host "ERROR: el zip contenia datos personales; se ha borrado." -ForegroundColor Red
    exit 1
}

$mb = [math]::Round((Get-Item $zip).Length / 1MB)
Write-Host ""
Write-Host "OK: $zip ($mb MB) - sin dictados ni configuracion personal." -ForegroundColor Green
if (-not $ConModelo) {
    Write-Host "El modelo no va dentro: se descarga solo al abrir Voz por primera vez."
}
exit 0
