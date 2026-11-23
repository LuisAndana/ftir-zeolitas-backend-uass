#!/usr/bin/env bash
# Se ejecuta EN EL SERVIDOR (lo lanza 00-preparar-servidor.ps1). Es repetible.
set -euo pipefail
DOMINIO="${1:?falta el dominio}"
RUTA=/opt/ftir

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo docker compose version >/dev/null
# Permite usar docker sin sudo (aplica en la proxima sesion SSH)
sudo usermod -aG docker "$USER"

echo "==> Firewall (solo SSH, HTTP y HTTPS)"
if command -v ufw >/dev/null 2>&1; then
  sudo ufw allow OpenSSH >/dev/null
  sudo ufw allow 80/tcp >/dev/null
  sudo ufw allow 443/tcp >/dev/null
  sudo ufw --force enable >/dev/null
fi

echo "==> Carpetas en $RUTA"
sudo mkdir -p "$RUTA" && sudo chown "$(id -un):$(id -gn)" "$RUTA"
mkdir -p "$RUTA"/{app,web,data/cache,data/uploads,backups}

if [ ! -f "$RUTA/.env" ]; then
  echo "==> Creando .env con claves aleatorias (solo existe en el servidor)"
  umask 077
  cat > "$RUTA/.env" <<ENV
DOMAIN=$DOMINIO
FRONTEND_URL=https://$DOMINIO
CORS_ORIGINS=https://$DOMINIO
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
  echo "    Edita SMTP_EMAIL / SMTP_PASSWORD con: nano $RUTA/.env"
else
  echo "==> .env ya existe, no se toca"
fi
echo "Servidor listo."
