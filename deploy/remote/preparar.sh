#!/usr/bin/env bash
# Se ejecuta EN EL SERVIDOR (lo lanza 00-preparar-servidor.ps1). Es repetible y NO toca nada ajeno:
# no instala paquetes, no cambia el firewall ni los puertos (son del proxy compartido).
set -euo pipefail
DOMINIO="${1:?falta el dominio}"
RUTA="$HOME/ftir"

echo "==> Comprobando el servidor"
docker compose version >/dev/null || { echo "Docker Compose no esta disponible para este usuario" >&2; exit 1; }
docker network inspect proxy >/dev/null 2>&1 || { echo "No existe la red proxy del proxy compartido" >&2; exit 1; }
[ -x /srv/proxy/publicar ] || { echo "No se encuentra /srv/proxy/publicar" >&2; exit 1; }

echo "==> Carpetas en $RUTA"
mkdir -p "$RUTA"/{app,web,data/cache,data/uploads,backups}
# Los respaldos contienen datos de usuarios y el servidor es compartido: solo este usuario puede entrar.
chmod 700 "$RUTA/backups"

if [ ! -f "$RUTA/.env" ]; then
  echo "==> Creando .env con claves aleatorias (solo existe en el servidor)"
  umask 077
  cat > "$RUTA/.env" <<ENV
DOMAIN=$DOMINIO
FRONTEND_URL=https://$DOMINIO
ALLOWED_ORIGINS=https://$DOMINIO
MYSQL_ROOT_PASSWORD=$(openssl rand -hex 24)
DB_USER=ftir
DB_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(openssl rand -hex 32)
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_EMAIL=
SMTP_PASSWORD=
SMTP_FROM_NAME=FTIR Zeolitas UAS
ENV
  echo "    Para el correo edita SMTP_EMAIL y SMTP_PASSWORD: nano $RUTA/.env"
else
  echo "==> .env ya existe, no se toca"
fi
echo "Servidor listo."
