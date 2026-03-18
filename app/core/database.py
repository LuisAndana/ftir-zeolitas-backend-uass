"""
Configuración de la base de datos SQLAlchemy
Gestión de conexiones, sesiones y pool de conexiones
"""

import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Obtener configuraciones
settings = get_settings()

# ========================================
# CONFIGURAR ENGINE
# ========================================

engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600
)

# ========================================
# CREAR SESIÓN LOCAL
# ========================================

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# ========================================
# BASE PARA MODELOS
# ========================================

Base = declarative_base()


# ========================================
# DEPENDENCIA DE FASTAPI
# ========================================

def get_db():
    """
    Dependencia de FastAPI para obtener la sesión de base de datos

    Uso en rutas:
        @router.get("/")
        def my_route(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Error en sesión de BD: {e}")
        db.rollback()
        raise
    finally:
        db.close()


# ========================================
# CONTEXT MANAGER (para uso fuera de rutas)
# ========================================

@contextmanager
def get_db_context():
    """
    Context manager para usar la BD fuera de rutas FastAPI

    Uso:
        with get_db_context() as db:
            user = db.query(User).filter(...).first()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error en transacción: {e}")
        raise
    finally:
        db.close()


# ========================================
# INICIALIZACIÓN
# ========================================

def init_db():
    """
    Inicializar la base de datos
    Crear todas las tablas si no existen
    """
    try:
        logger.info("📊 Inicializando base de datos...")

        # Importar todos los modelos para asegurar que se registren en Base
        from app.models.user import User
        from app.models.spectrum import Spectrum
        from app.models.zeolite_family import ZeoliteFamily
        from app.models.similarity_result import SimilarityResult
        from app.models.session_token import SessionToken

        # Crear todas las tablas definidas
        Base.metadata.create_all(bind=engine)
        logger.info("✅ Base de datos inicializada correctamente")

    except Exception as e:
        logger.error(f"❌ Error inicializando base de datos: {e}")
        raise


def test_db_connection() -> bool:
    """
    Probar la conexión a la base de datos

    Returns:
        bool: True si la conexión es exitosa, False en caso contrario
    """
    try:
        with engine.connect() as connection:
            # Usar text() para raw SQL en SQLAlchemy 2.0+
            result = connection.execute(text("SELECT 1"))
            logger.info("✅ Conexión a MySQL verificada")
            return True
    except Exception as e:
        logger.error(f"❌ Error conectando a MySQL: {e}")
        return False


def drop_all_tables():
    """
    Eliminar todas las tablas de la base de datos

    ⚠️ ADVERTENCIA: Solo usar en desarrollo/testing
    """
    try:
        logger.warning("⚠️  Eliminando todas las tablas...")
        Base.metadata.drop_all(bind=engine)
        logger.info("✅ Tablas eliminadas")
    except Exception as e:
        logger.error(f"❌ Error eliminando tablas: {e}")
        raise


def reset_db():
    """
    Reset completo de la base de datos
    Elimina todas las tablas y las recrea

    ⚠️ ADVERTENCIA: Solo usar en desarrollo/testing
    """
    try:
        logger.warning("⚠️  Reseteando base de datos...")
        drop_all_tables()
        init_db()
        logger.info("✅ Base de datos reseteada")
    except Exception as e:
        logger.error(f"❌ Error en reset: {e}")
        raise