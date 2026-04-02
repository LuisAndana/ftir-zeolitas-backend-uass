#!/usr/bin/env python3
"""
Migración: agrega columnas role y verification_token a la tabla users.
Compatible con MySQL 5.7+
Ejecutar UNA sola vez: python migrate_users.py
"""
from app.core.database import engine
from app.core.config import settings
from sqlalchemy import text


def column_exists(conn, table: str, column: str) -> bool:
    """Verifica si una columna existe en la tabla."""
    result = conn.execute(text("""
        SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :db
          AND TABLE_NAME   = :table
          AND COLUMN_NAME  = :column
    """), {"db": settings.db_name, "table": table, "column": column})
    return result.scalar() > 0


def run():
    print("🔄 Aplicando migraciones a la tabla 'users'...\n")

    with engine.connect() as conn:

        # ── 1. Columna role ──────────────────────────────────────────────
        if not column_exists(conn, "users", "role"):
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN `role` VARCHAR(50) NOT NULL "
                "DEFAULT 'investigador' AFTER password_hash"
            ))
            conn.commit()
            print("  ✅ Columna 'role' agregada")
        else:
            print("  ⏭️  Columna 'role' ya existe, omitida")

        # ── 2. Columna verification_token ────────────────────────────────
        if not column_exists(conn, "users", "verification_token"):
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN verification_token "
                "VARCHAR(255) NULL AFTER is_verified"
            ))
            conn.commit()
            print("  ✅ Columna 'verification_token' agregada")
        else:
            print("  ⏭️  Columna 'verification_token' ya existe, omitida")

        # ── 3. is_active = False para usuarios no verificados (existentes) ─
        conn.execute(text(
            "UPDATE users SET is_active = 0 WHERE is_verified = 0"
        ))
        conn.commit()
        print("  ✅ Usuarios no verificados marcados como inactivos")

    print("\n✅ Migración completada. Reinicia el servidor FastAPI.")


if __name__ == "__main__":
    run()
