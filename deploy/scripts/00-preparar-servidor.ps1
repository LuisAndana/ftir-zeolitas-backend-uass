# Paso 1 (una sola vez): instala Docker, abre el firewall y crea /opt/ftir con un .env de claves aleatorias.
. "$PSScriptRoot\_comun.ps1"

Write-Host "Preparando $Servidor para $Dominio ..." -ForegroundColor Cyan
Invoke-Ssh "mkdir -p $RutaRemota"
Send-ScriptRemoto "preparar.sh"
Invoke-Ssh "bash $RutaRemota/preparar.sh $Dominio" -Interactivo
Write-Host "`nListo. Siguiente: .\01-migrar-bd.ps1" -ForegroundColor Green
