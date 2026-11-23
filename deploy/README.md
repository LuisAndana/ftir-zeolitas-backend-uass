# Despliegue en el VPS compartido (Hostinger) con PowerShell

El VPS ya aloja otros proyectos y tiene un **proxy Caddy compartido** (`/srv/proxy`, guia en `/srv/proxy/LEEME.md`)
que es el unico que usa los puertos 80/443 y saca los certificados HTTPS. Este proyecto NO abre puertos ni toca
el firewall: se une a la red `proxy` con etiquetas y se publica con `/srv/proxy/publicar ftir`.

```
Internet -> proxy Caddy -> ftir-web (nginx: Angular + /api) -> ftir-api (FastAPI) -> ftir-db (MySQL 9.4)
```

Todo vive en `~/ftir` del servidor (`/home/andana/ftir`). El frontend se compila en tu PC y se sube construido.

## Antes de empezar

1. **DNS**: registro **A** `zeolitas.forasoft.cloud` -> `193.43.134.86` (panel DNS de Hostinger). Sin eso Let's Encrypt
   no da el certificado. Si prefieres otro subdominio, cambialo en `deploy\scripts\deploy.config.ps1`.
2. **Llave SSH cargada** (una vez por sesion de Windows, PowerShell como administrador la primera vez):
   `Start-Service ssh-agent` y `ssh-add $env:USERPROFILE\.ssh\id_ed25519`.
3. **Seguridad**: el `.env` local y su historial de git tienen secretos reales (P0 #1 de `CLAUDE.md`). El servidor
   genera claves nuevas; aun asi rota la contrasena de aplicacion de Gmail y la de MySQL local.
4. **Commit** de lo que quieras publicar: se sube lo versionado (`git archive`), no tu carpeta.

## Pasos (PowerShell en tu PC, desde `deploy\scripts`)

```powershell
.\00-preparar-servidor.ps1   # comprueba el proxy, crea ~/ftir y su .env con claves aleatorias (no cambia nada ajeno)
.\01-migrar-bd.ps1           # copia tu MySQL local al servidor (pide confirmacion y la clave local)
.\02-desplegar.ps1           # compila Angular, sube todo, levanta, migra esquema y publica en el proxy
.\03-estado.ps1              # contenedores, logs y lo que esta publicado
```

Para publicar cambios despues: commit + `.\02-desplegar.ps1` (respaldo previo de la BD, conserva 5).
`.\04-respaldo.ps1` descarga un respaldo a tu PC.

## Notas

- Reglas del proxy cumplidas: `name: ftir` unico, servicios `ftir-*`, la base solo en la red interna, sin `ports:`.
- **Correo**: en el servidor `nano ~/ftir/.env` (`SMTP_EMAIL`, `SMTP_PASSWORD`) y
  `docker compose -f docker-compose.prod.yml up -d` desde `~/ftir`.
- **Primer arranque**: el motor de similitud reconstruye su cache desde la BD (~100 s); hasta entonces `/search` da 503.
- `/docs` y `/redoc` no se exponen (nginx solo reenvia `/api/`).
- Nunca `docker compose down -v` en `/srv/proxy` (borra los certificados de todos los proyectos).
- Para dejar de publicar: `/srv/proxy/publicar --retirar ftir`.
