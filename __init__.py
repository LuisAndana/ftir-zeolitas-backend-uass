"""
FTIR Zeolitas Backend API
Aplicación FastAPI para gestionar espectros FTIR
"""

__version__ = "1.0.0"
__author__ = "FTIR Zeolitas Team"

from app.core.config import settings
from app.core.database import get_db

__all__ = [
    "settings",
    "get_db"
]