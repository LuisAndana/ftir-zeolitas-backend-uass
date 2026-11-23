#!/usr/bin/env bash
# Se ejecuta EN EL SERVIDOR (lo lanza 00-preparar-servidor.ps1). Es repetible.
set -euo pipefail
DOMINIO="${1:?falta el dominio}"
RUTA=/opt/ftir

echo "==> Docker"
if ! command -v docker >/dev/null 2>&1; then
  # Repositorio APT oficial de Docker, con su llave verificada por huella (sin ejecutar scripts descargados).
  sudo apt-get update -y
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  HUELLA_ESPERADA="9DC858229FC7DD38854AE2D88D81803C0EBFCD88"
  HUELLA=$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '/^fpr:/ {print $10; exit}')
  if [ "$HUELLA" != "$HUELLA_ESPERADA" ]; then
    echo "La huella de la llave de Docker no coincide ($HUELLA). Abortando por seguridad." >&2
    sudo rm -f /etc/apt/keyrings/docker.asc
    exit 1
  fi
  sudo chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable"     | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update -y
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
# No se agrega al usuario al grupo "docker" (equivale a root): los scripts usan "sudo docker".
sudo docker compose version >/dev/null

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
  echo "    Edita SMTP_EMAIL / SMTP_PASSWORD con: nano $RUTA/.env"
else
  echo "==> .env ya existe, no se toca"
fi
echo "Servidor listo."
