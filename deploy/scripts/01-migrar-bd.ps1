# Paso 2: copia tu base de datos LOCAL (MySQL) al servidor. REEMPLAZA las tablas de la BD remota.
. "$PSScriptRoot\_comun.ps1"

$mysqldump = (Get-Command mysqldump -ErrorAction SilentlyContinue).Source
if (-not $mysqldump) {
    $mysqldump = Get-ChildItem "C:\Program Files\MySQL\*\bin\mysqldump.exe", "C:\Program Files (x86)\MySQL\*\bin\mysqldump.exe" -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $mysqldump) { throw "No se encontro mysqldump. Instala MySQL o agrega su carpeta bin al PATH." }

Write-Host "ATENCION: se reemplazaran las tablas de la base de datos en $Servidor con las de tu PC." -ForegroundColor Yellow
if ((Read-Host "Escribe SI para continuar") -ne "SI") { Write-Host "Cancelado."; exit 0 }

$claveSegura = Read-Host "Contrasena de MySQL local (usuario $UsuarioMysqlLocal)" -AsSecureString
$clave = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($claveSegura))

$tmp = Join-Path $env:TEMP "ftir-migracion"
New-Item -ItemType Directory -Force $tmp | Out-Null
$sql = Join-Path $tmp "dump.sql"
$gz  = Join-Path $tmp "dump.sql.gz"
$cnf = Join-Path $tmp "cliente.cnf"

try {
    # La clave va en un archivo temporal (no en la linea de comandos) y se borra al terminar.
    Set-Content -Path $cnf -Encoding ASCII -Value "[client]`nuser=$UsuarioMysqlLocal`npassword=$clave`nhost=$HostMysqlLocal"

    Write-Host "1/4 Exportando base de datos local ..." -ForegroundColor Cyan
    & $mysqldump "--defaults-extra-file=$cnf" --single-transaction --routines --triggers --no-tablespaces `
        --set-gtid-purged=OFF --default-character-set=utf8mb4 "--result-file=$sql" $BaseDeDatosLocal
    if ($LASTEXITCODE -ne 0) { throw "mysqldump fallo." }

    Write-Host "2/4 Comprimiendo ($([math]::Round((Get-Item $sql).Length/1MB)) MB) ..." -ForegroundColor Cyan
    Compress-Gzip $sql $gz

    Write-Host "3/4 Subiendo al servidor ($([math]::Round((Get-Item $gz).Length/1MB)) MB comprimidos) ..." -ForegroundColor Cyan
    Send-ConfigDocker
    Invoke-Ssh "mkdir -p $RutaRemota/backups"
    Copy-ToServer @($gz) "$RutaRemota/backups"
    Send-ScriptRemoto "importar-bd.sh"

    Write-Host "4/4 Importando en el servidor ..." -ForegroundColor Cyan
    Invoke-Ssh "bash $RutaRemota/importar-bd.sh"
}
finally {
    Remove-Item $cnf, $sql, $gz -Force -ErrorAction SilentlyContinue
    $clave = $null
}
Write-Host "`nBase de datos migrada. Compara los conteos de arriba con tu BD local. Siguiente: .\02-desplegar.ps1" -ForegroundColor Green
