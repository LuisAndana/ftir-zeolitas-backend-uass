"""
Aplicación principal FastAPI
Punto de entrada de la aplicación
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import init_db, test_db_connection

# ========================================
# CONFIGURAR LOGGING
# ========================================

logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========================================
# CREAR CARPETAS NECESARIAS
# ========================================

Path(settings.upload_folder).mkdir(parents=True, exist_ok=True)
logger.info(f"📁 Carpeta de uploads: {settings.upload_folder}")

# ========================================
# CREAR APLICACIÓN FASTAPI
# ========================================

app = FastAPI(
    title=settings.api_title,
    description=settings.api_description,
    version=settings.api_version,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# ========================================
# CONFIGURAR CORS
# ========================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

logger.info(f"✅ CORS configurado para: {settings.cors_origins}")

# ========================================
# RUTAS PRINCIPALES
# ========================================

@app.get("/", summary="Bienvenida", tags=["root"])
def root():
    """Ruta raíz de bienvenida"""
    return {
        "message": "Bienvenido a FTIR Zeolitas API",
        "version": settings.api_version,
        "environment": settings.environment,
        "docs": "/docs",
        "redoc": "/redoc"
    }

@app.get("/health", summary="Health Check", tags=["monitoring"])
def health_check():
    """Verificar que la API está activa"""
    return {
        "status": "ok",
        "version": settings.api_version,
        "environment": settings.environment
    }

# ========================================
# IMPORTAR Y REGISTRAR ROUTERS
# ========================================

logger.info("📦 Importando routers...")

from app.routes.auth import router as auth_router
from app.routes.spectra import router as spectra_router
from app.routes.zeolites import router as zeolites_router
from app.routes.similarity import router as similarity_router

logger.info("✅ Todos los routers importados")

# ========================================
# REGISTRAR CON PREFIJOS /api
# ========================================

logger.info("📌 Registrando routers...")

app.include_router(
    auth_router,
    prefix="/api/auth",
    tags=["autenticación"]
)

app.include_router(
    spectra_router,
    prefix="/api/spectra",
    tags=["espectros"]
)

app.include_router(
    zeolites_router,
    prefix="/api/zeolites",
    tags=["zeolitas"]
)

app.include_router(
    similarity_router,
    prefix="/api/similarity",
    tags=["similitud"]
)

logger.info("✅ Routers registrados:")
logger.info("   ✅ /api/auth")
logger.info("   ✅ /api/spectra")
logger.info("   ✅ /api/zeolites")
logger.info("   ✅ /api/similarity")

# ========================================
# EVENTOS
# ========================================

@app.on_event("startup")
async def startup_event():
    """Se ejecuta cuando inicia la aplicación"""
    logger.info("🚀 Iniciando aplicación FastAPI...")

    try:
        init_db()
        logger.info("✅ Base de datos inicializada")
    except Exception as e:
        logger.error(f"❌ Error inicializando base de datos: {e}")
        raise

    if test_db_connection():
        logger.info("✅ Conexión a MySQL verificada")
    else:
        logger.error("❌ No se pudo conectar a MySQL")
        raise Exception("No se pudo conectar a la base de datos")

    logger.info("🚀 ¡Aplicación lista para usar!\n")

@app.on_event("shutdown")
async def shutdown_event():
    """Se ejecuta cuando se apaga la aplicación"""
    logger.info("🛑 Cerrando aplicación...")

# ========================================
# MANEJO DE ERRORES
# ========================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Manejador global de excepciones"""
    logger.error(f"❌ Error: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Error interno del servidor",
            "detail": str(exc) if settings.debug else "Error no especificado"
        }
    )

# ========================================
# PUNTO DE ENTRADA
# ========================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
        access_log=True
    )