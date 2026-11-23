# Descarga un respaldo comprimido de la base de datos del servidor a deploy\backups-descargados\.
. "$PSScriptRoot\_comun.ps1"
$nombre = "respaldo-$(Get-Date -Format yyyyMMdd-HHmmss).sql.gz"
Invoke-Ssh "cd $RutaRemota && chmod 700 backups && umask 077 && set -a && . ./.env && set +a && export MYSQL_PWD=`"`$MYSQL_ROOT_PASSWORD`" && docker compose -f docker-compose.prod.yml exec -T -e MYSQL_PWD ftir-db mysqldump -uroot --single-transaction ftir_zeolitas | gzip > backups/$nombre"
$destino = Join-Path $RaizDeploy "backups-descargados"
New-Item -ItemType Directory -Force $destino | Out-Null
Copy-FromServer "$RutaRemota/backups/$nombre" $destino
Write-Host "Respaldo guardado en $destino\$nombre (contiene datos de usuarios: guardalo en un lugar seguro)." -ForegroundColor Green
