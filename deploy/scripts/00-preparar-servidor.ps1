# Paso 1 (una sola vez): comprueba el proxy compartido del VPS y crea ~/ftir con un .env de claves aleatorias (no instala ni cambia nada ajeno).
. "$PSScriptRoot\_comun.ps1"

Write-Host "Preparando $Servidor para $Dominio ..." -ForegroundColor Cyan
Invoke-Ssh "mkdir -p $RutaRemota"
Send-ScriptRemoto "preparar.sh"
Invoke-Ssh "bash $RutaRemota/preparar.sh $Dominio"
Write-Host "`nListo. Siguiente: .\01-migrar-bd.ps1" -ForegroundColor Green
