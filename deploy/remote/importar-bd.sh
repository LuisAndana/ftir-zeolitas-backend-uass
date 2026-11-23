#!/usr/bin/env bash
# Se ejecuta EN EL SERVIDOR (lo lanza 01-migrar-bd.ps1). Importa ~/ftir/backups/dump.sql.gz en ftir-db.
set -euo pipefail
cd "$HOME/ftir"
set -a; . ./.env; set +a
export MYSQL_PWD="$MYSQL_ROOT_PASSWORD"   # llega al contenedor sin aparecer en la lista de procesos
DC="docker compose -f docker-compose.prod.yml"

chmod 700 backups; chmod 600 backups/dump.sql.gz   # datos de usuarios en un servidor compartido

echo "==> Levantando solo la base de datos"
$DC up -d ftir-db
for i in $(seq 1 40); do
  $DC exec -T -e MYSQL_PWD ftir-db mysqladmin ping -h localhost -uroot --silent >/dev/null 2>&1 && break
  sleep 3
done

echo "==> Importando (puede tardar varios minutos)"
gunzip -c backups/dump.sql.gz | $DC exec -T -e MYSQL_PWD ftir-db mysql -uroot ftir_zeolitas

echo "==> Verificacion"
$DC exec -T -e MYSQL_PWD ftir-db mysql -uroot ftir_zeolitas -e \
  "SELECT 'users' t, COUNT(*) n FROM users UNION ALL SELECT 'spectra', COUNT(*) FROM spectra UNION ALL SELECT 'ftir_spectra', COUNT(*) FROM ftir_spectra UNION ALL SELECT 'zeolite_families', COUNT(*) FROM zeolite_families;"
echo "Importacion terminada."
