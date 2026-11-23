# Muestra contenedores, ultimos logs del backend y comprueba el sitio por HTTPS.
. "$PSScriptRoot\_comun.ps1"
Invoke-Ssh "cd $RutaRemota && docker compose -f docker-compose.prod.yml ps && docker compose -f docker-compose.prod.yml logs --tail=25 backend"
foreach ($ruta in "/", "/api/zeolites") {
    try { $r = Invoke-WebRequest "https://$Dominio$ruta" -UseBasicParsing; Write-Host "$ruta -> $($r.StatusCode)" }
    catch { Write-Host "$ruta -> $($_.Exception.Response.StatusCode.value__) (401 es normal: pide sesion)" }
}
