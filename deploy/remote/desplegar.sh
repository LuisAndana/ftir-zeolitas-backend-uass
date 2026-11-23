#!/usr/bin/env bash
# Se ejecuta EN EL SERVIDOR (lo lanza 02-desplegar.ps1) con app.tgz y web.tgz ya subidos a ~/ftir.
set -euo pipefail
cd "$HOME/ftir"
set -a; . ./.env; set +a
export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"
DC="docker compose -f docker-compose.prod.yml"

echo "==> Respaldo previo de la base de datos"
chmod 700 backups   # datos de usuarios en un servidor compartido
if $DC ps --status running ftir-db 2>/dev/null | grep -q ftir-db; then
  ( umask 077; $DC exec -T -e MYSQL_PWD ftir-db mysqldump -uroot --single-transaction ftir_zeolitas | gzip > "backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sql.gz" )
  ls -1t backups/pre-deploy-*.sql.gz | tail -n +6 | xargs -r rm --   # conserva los 5 ultimos
fi

echo "==> Codigo del backend"
rm -rf app && mkdir app && tar -xzf app.tgz -C app && rm app.tgz
echo "==> Frontend"
rm -rf web && mkdir web && tar -xzf web.tgz -C web && rm web.tgz

echo "==> Construyendo y levantando (solo este proyecto)"
$DC up -d --build --remove-orphans

echo "==> Migraciones de esquema"
$DC exec -T ftir-api alembic upgrade head

echo "==> Comprobando salud del backend"
ok=0
for i in $(seq 1 30); do
  if $DC exec -T ftir-api python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then ok=1; break; fi
  sleep 4
done
if [ "$ok" -ne 1 ]; then echo "El backend no respondio. Ultimos logs:"; $DC logs --tail=40 ftir-api; exit 1; fi
echo "Backend OK"

echo "==> Publicando en el proxy compartido"
/srv/proxy/publicar ftir
$DC ps
