#!/usr/bin/env bash
# Se ejecuta EN EL SERVIDOR (lo lanza 01-migrar-bd.ps1). Importa /opt/ftir/backups/dump.sql.gz.
set -euo pipefail
cd /opt/ftir
set -a; . ./.env; set +a
DC="docker compose -f docker-compose.prod.yml"

echo "==> Levantando solo la base de datos"
$DC up -d db
for i in $(seq 1 40); do
  $DC exec -T db mysqladmin ping -h localhost -uroot -p"$MYSQL_ROOT_PASSWORD" --silent >/dev/null 2>&1 && break
  sleep 3
done

echo "==> Importando (puede tardar varios minutos)"
gunzip -c backups/dump.sql.gz | $DC exec -T db mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ftir_zeolitas

echo "==> Verificación"
$DC exec -T db mysql -uroot -p"$MYSQL_ROOT_PASSWORD" ftir_zeolitas -e \
  "SELECT 'users' t, COUNT(*) n FROM users UNION ALL SELECT 'spectra', COUNT(*) FROM spectra UNION ALL SELECT 'ftir_spectra', COUNT(*) FROM ftir_spectra UNION ALL SELECT 'zeolite_families', COUNT(*) FROM zeolite_families;"
echo "Importación terminada."
