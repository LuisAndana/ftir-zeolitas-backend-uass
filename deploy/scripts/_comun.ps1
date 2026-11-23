# Funciones compartidas por los scripts de despliegue. No se ejecuta solo.
$ErrorActionPreference = "Stop"
$RaizDeploy  = Split-Path -Parent $PSScriptRoot
$RaizBackend = Split-Path -Parent $RaizDeploy
$RutaRemota  = $null   # se calcula tras leer la configuracion: /home/<usuario>/ftir

$ArchivoConfig = Join-Path $PSScriptRoot "deploy.config.ps1"
if (-not (Test-Path $ArchivoConfig)) {
    throw "Falta deploy\scripts\deploy.config.ps1. Copia deploy.config.example.ps1 con ese nombre y ajusta los valores."
}
. $ArchivoConfig
$RutaRemota = "/home/" + $Servidor.Split("@")[0] + "/ftir"

foreach ($herramienta in "ssh", "scp", "tar", "git") {
    if (-not (Get-Command $herramienta -ErrorAction SilentlyContinue)) { throw "No se encontro '$herramienta' en el PATH." }
}

$OpcionesSsh = @("-o", "StrictHostKeyChecking=accept-new")
if ($LlaveSsh) { $OpcionesSsh += @("-i", $LlaveSsh) }

function Invoke-Ssh([string]$Comando, [switch]$Interactivo) {
    $argumentos = @() + $OpcionesSsh
    if ($Interactivo) { $argumentos += "-t" }
    & ssh @argumentos $Servidor $Comando
    if ($LASTEXITCODE -ne 0) { throw "El comando remoto fallo (codigo $LASTEXITCODE)." }
}

function Copy-ToServer([string[]]$Archivos, [string]$Destino = $RutaRemota) {
    & scp @OpcionesSsh @Archivos "${Servidor}:${Destino}/"
    if ($LASTEXITCODE -ne 0) { throw "scp fallo (codigo $LASTEXITCODE)." }
}

function Copy-FromServer([string]$Remoto, [string]$Local) {
    & scp @OpcionesSsh "${Servidor}:${Remoto}" $Local
    if ($LASTEXITCODE -ne 0) { throw "scp fallo (codigo $LASTEXITCODE)." }
}

function Send-ConfigDocker {
    Copy-ToServer @(
        (Join-Path $RaizDeploy "docker-compose.prod.yml"),
        (Join-Path $RaizDeploy "nginx.conf")
    )
}

function Send-ScriptRemoto([string]$Nombre) {
    Copy-ToServer @((Join-Path $RaizDeploy "remote\$Nombre"))
    Invoke-Ssh "sed -i 's/\r$//' $RutaRemota/$Nombre && chmod +x $RutaRemota/$Nombre"
}

function Compress-Gzip([string]$Origen, [string]$Destino) {
    $entrada = [IO.File]::OpenRead($Origen)
    $salida  = [IO.File]::Create($Destino)
    $gz = New-Object IO.Compression.GZipStream($salida, [IO.Compression.CompressionMode]::Compress)
    try { $entrada.CopyTo($gz) } finally { $gz.Dispose(); $salida.Dispose(); $entrada.Dispose() }
}
