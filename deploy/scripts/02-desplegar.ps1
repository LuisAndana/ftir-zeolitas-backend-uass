# Paso 3 (y cada vez que quieras publicar cambios): compila el frontend, sube backend + frontend y reinicia.
. "$PSScriptRoot\_comun.ps1"

# Solo se publica lo que esta COMMITEADO en el backend (git archive); avisa si hay cambios sin commit.
$pendientes = git -C $RaizBackend status --porcelain | Where-Object { $_ -notmatch "__pycache__" -and $_ -notmatch "\.env$" }
if ($pendientes) {
    Write-Host "Hay cambios sin commit en el backend (NO se publicaran):" -ForegroundColor Yellow
    $pendientes | ForEach-Object { Write-Host "  $_" }
    if ((Read-Host "Escribe SI para continuar de todos modos") -ne "SI") { exit 0 }
}

$tmp = Join-Path $env:TEMP "ftir-despliegue"
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $tmp | Out-Null

Write-Host "1/4 Compilando el frontend ..." -ForegroundColor Cyan
Push-Location $FrontendDir
try {
    if (-not (Test-Path "node_modules")) { npm ci; if ($LASTEXITCODE -ne 0) { throw "npm ci fallo." } }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "La compilacion de Angular fallo." }
} finally { Pop-Location }
$navegador = Get-ChildItem (Join-Path $FrontendDir "dist") -Directory | ForEach-Object { Join-Path $_.FullName "browser" } |
    Where-Object { Test-Path (Join-Path $_ "index.html") } | Select-Object -First 1
if (-not $navegador) { throw "No se encontro dist\*\browser\index.html tras compilar." }

Write-Host "2/4 Empaquetando ..." -ForegroundColor Cyan
tar -czf (Join-Path $tmp "web.tgz") -C $navegador .
if ($LASTEXITCODE -ne 0) { throw "No se pudo empaquetar el frontend." }
# git archive solo incluye archivos versionados; se excluye .env explicitamente (no viajan secretos).
git -C $RaizBackend archive --format=tar.gz -o (Join-Path $tmp "app.tgz") HEAD -- . ":(exclude).env" ":(exclude)deploy"
if ($LASTEXITCODE -ne 0) { throw "git archive fallo." }

Write-Host "3/4 Subiendo ..." -ForegroundColor Cyan
Send-ConfigDocker
Copy-ToServer @((Join-Path $tmp "app.tgz"), (Join-Path $tmp "web.tgz"))
Send-ScriptRemoto "desplegar.sh"

Write-Host "4/4 Desplegando en el servidor ..." -ForegroundColor Cyan
Invoke-Ssh "bash $RutaRemota/desplegar.sh" -Interactivo
Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "`nPublicado: https://$Dominio" -ForegroundColor Green
