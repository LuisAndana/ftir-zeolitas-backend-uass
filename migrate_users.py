#!/usr/bin/env python3
"""
Migración: agrega columnas role y verification_token a la tabla users.
Ejecutar UNA sola vez:
    python migrate_users.py
"""
from app.core.database import engine
from sqlalchemy import text

migrations = [
    # Rol del usuario
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS `role` VARCHAR(50) NOT NULL DEFAULT 'investigador'
    AFTER password_hash;
    """,
    # Token de verificación de correo
    """
    ALTER TABLE users
    ADD COLUMN IF NOT EXISTS verification_token VARCHAR(255) NULL UNIQUE
    AFTER is_verified;
    """,
    # is_active en FALSE para usuarios existentes sin verificar (opcional)
    # Comenta esta línea si quieres mantener activos a los usuarios actuales:
    # "UPDATE users SET is_active = 0 WHERE is_verified = 0;",
]

def run():
    print("🔄 Aplicando migraciones a la tabla 'users'...")
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql.strip()))
                conn.commit()
                print(f"  ✅ OK: {sql.strip()[:60]}...")
            except Exception as e:
                print(f"  ⚠️  {e}")
    print("\n✅ Migración completada. Reinicia el servidor FastAPI.")

if __name__ == "__main__":
    run()
