"""
Módulo routes: enrutadores de la aplicación
"""

from app.routes.auth import router as auth_router
from app.routes.spectra import router as spectra_router
from app.routes.zeolites import router as zeolites_router

__all__ = [
    "auth_router",
    "spectra_router",
    "zeolites_router"
]