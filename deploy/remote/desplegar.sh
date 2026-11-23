#!/usr/bin/env bash
# Se ejecuta EN EL SERVIDOR (lo lanza 02-desplegar.ps1) con app.tgz y web.tgz ya subidos a /opt/ftir.
set -euo pipefail
cd /opt/ftir
DC="docker compose -f docker-compose.prod.yml"

echo "==> Respaldo previo de la base de datos"
set -a; . ./.env; set +a
if $DC ps --status running db 2>/dev/null | grep -q db; then
  $DC exec -T db mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --single-transaction ftir_zeolitas | gzip > "backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sql.gz"
  ls -1t backups/pre-deploy-*.sql.gz | tail -n +6 | xargs -r rm --   # conserva los 5 últimos
fi

echo "==> Código del backend"
rm -rf app && mkdir app && tar -xzf app.tgz -C app && rm app.tgz
echo "==> Frontend"
rm -rf web && mkdir web && tar -xzf web.tgz -C web && rm web.tgz

echo "==> Construyendo y levantando"
$DC up -d --build

echo "==> Migraciones de esquema"
$DC exec -T backend alembic upgrade head

echo "==> Comprobando salud"
for i in $(seq 1 30); do
  if $DC exec -T backend python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then
    echo "Backend OK"; $DC ps; exit 0
  fi
  sleep 4
done
echo "El backend no respondió. Últimos logs:"; $DC logs --tail=40 backend; exit 1
