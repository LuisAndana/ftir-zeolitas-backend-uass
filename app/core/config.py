"""
Configuración de la aplicación FastAPI
Carga variables de entorno y define configuraciones globales
"""

from pydantic_settings import BaseSettings
from typing import List
import os
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Configuraciones de la aplicación
    Lee las variables del archivo .env
    """

    # ========================================
    # BASE DE DATOS - MYSQL
    # ========================================
    db_host: str = os.getenv("DB_HOST", "localhost")
    db_port: int = int(os.getenv("DB_PORT", "3306"))
    db_user: str = os.getenv("DB_USER", "root")
    db_password: str = os.getenv("DB_PASSWORD", "0405")
    db_name: str = os.getenv("DB_NAME", "ftir_zeolitas")

    @property
    def database_url(self) -> str:
        """Construir URL de conexión a MySQL"""
        return f"mysql+pymysql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # ========================================
    # SERVIDOR
    # ========================================
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = os.getenv("DEBUG", "True").lower() == "true"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    # ========================================
    # SEGURIDAD - JWT
    # ========================================
    secret_key: str = os.getenv(
        "SECRET_KEY",
        "tu_clave_super_secreta_cambiar_en_produccion_min_32_caracteres"
    )
    algorithm: str = os.getenv("ALGORITHM", "HS256")
    access_token_expire_minutes: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    refresh_token_expire_days: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

    # ========================================
    # CORS
    # ========================================
    cors_origins: List[str] = [
        "http://localhost:4200",
        "http://localhost:3000",
        "http://127.0.0.1:4200",
        "http://127.0.0.1:3000"
    ]

    # ========================================
    # ARCHIVOS - UPLOAD
    # ========================================
    upload_folder: str = os.getenv("UPLOAD_FOLDER", "./uploads/spectra")
    max_upload_size: int = int(os.getenv("MAX_UPLOAD_SIZE", "5242880"))  # 5MB

    # ========================================
    # API - INFORMACIÓN
    # ========================================
    api_title: str = os.getenv("API_TITLE", "FTIR Zeolitas API")
    api_version: str = os.getenv("API_VERSION", "1.0.0")
    api_description: str = os.getenv(
        "API_DESCRIPTION",
        "Backend API para Software FTIR Zeolitas"
    )

    # ========================================
    # EMAIL - SMTP (OPCIONAL)
    # ========================================
    smtp_server: str = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_email: str = os.getenv("SMTP_EMAIL", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "FTIR Zeolitas UAS")
    frontend_url: str = os.getenv("FRONTEND_URL", "http://localhost:4200")

    class Config:
        """Configuración de Pydantic"""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """
    Obtener configuraciones (cached)

    Returns:
        Settings: Objeto con todas las configuraciones
    """
    return Settings()


# Crear instancia global
settings = get_settings()

# Log de configuración al iniciar
if settings.debug:
    logger.debug(f"🔧 Configuración cargada:")
    logger.debug(f"   Ambiente: {settings.environment}")
    logger.debug(f"   Base de datos: {settings.db_host}:{settings.db_port}/{settings.db_name}")
    logger.debug(f"   Debug: {settings.debug}")
