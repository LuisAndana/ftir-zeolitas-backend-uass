# Despliegue en un VPS (Hostinger) con PowerShell

Arquitectura: **Caddy** (HTTPS automatico) -> **backend FastAPI** -> **MySQL 9.4**, todo en Docker Compose
en `/opt/ftir` del servidor. Solo Caddy abre puertos (80/443). El frontend Angular se compila en tu PC y se
sube ya construido. Todo se hace desde PowerShell con los scripts de `deploy\scripts\`.

## Antes de empezar

1. **VPS Ubuntu 22.04 o 24.04** con acceso SSH por llave (recomendado) y el cliente OpenSSH de Windows
   (`ssh`, `scp`, `tar` ya vienen en Windows 10/11).
2. **DNS**: en el panel del dominio, un registro **A** (y otro para `www` si lo quieres) hacia la IP del VPS.
   Caddy solo obtiene el certificado HTTPS cuando el dominio ya apunta al servidor.
3. **Seguridad (obligatorio antes de publicar)**: el `.env` local y su historial de git contienen secretos
   reales (pendiente P0 #1 de `CLAUDE.md`). El servidor NO los usa: genera claves nuevas aleatorias. Aun asi,
   rota la contrasena de aplicacion de Gmail y la de MySQL local.
4. Haz **commit** de lo que quieras publicar: el despliegue sube lo versionado (`git archive`), no tu carpeta.

## Pasos (PowerShell, desde `deploy\scripts`)

Si tu llave SSH tiene passphrase, cargala una vez para no escribirla en cada comando (PowerShell como administrador la primera vez):

```powershell
Set-Service ssh-agent -StartupType Manual; Start-Service ssh-agent
ssh-add $env:USERPROFILE\.ssh\id_ed25519
```

El usuario del VPS puede ser no-root (usa `sudo`; pedira su contrasena en el paso 00).


```powershell
Copy-Item deploy.config.example.ps1 deploy.config.ps1   # edita servidor, dominio, rutas
.\00-preparar-servidor.ps1   # una vez: Docker, firewall, /opt/ftir y .env con claves aleatorias
.\01-migrar-bd.ps1           # copia tu MySQL local al servidor (pide confirmacion y la clave local)
.\02-desplegar.ps1           # compila Angular, sube backend + frontend, levanta todo, migra esquema
.\03-estado.ps1              # contenedores, logs y comprobacion HTTPS
```

Para publicar cambios despues: commit + `.\02-desplegar.ps1`. Hace un respaldo de la BD antes (conserva 5).
`.\04-respaldo.ps1` descarga un respaldo a tu PC.

## Notas

- **Correo** (recuperar contrasena): edita en el servidor `nano /opt/ftir/.env` (`SMTP_EMAIL`, `SMTP_PASSWORD`)
  y reinicia: `docker compose -f docker-compose.prod.yml up -d`.
- **Primer arranque**: el motor de similitud reconstruye su cache desde la BD (~100 s). Hasta entonces
  `/search` responde 503.
- `/docs`, `/redoc` y `/openapi.json` estan bloqueados desde fuera (Caddyfile).
- El frontend usa `apiUrl: '/api'` en produccion (misma direccion que la web, sin CORS).
- Revertir: los respaldos estan en `/opt/ftir/backups/`.
