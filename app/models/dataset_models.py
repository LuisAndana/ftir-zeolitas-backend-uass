"""
Modelos Pydantic para el dataset de zeolitas
"""

from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class DatasetStatus(BaseModel):
    """Estado de la carga del dataset"""
    is_loading: bool
    progress_percent: int
    current_step: str
    total_records: int
    zeolite_types: int
    samples: int
    spectra: int
    peaks: int
    analysis_records: int

    class Config:
        schema_extra = {
            "example": {
                "is_loading": False,
                "progress_percent": 100,
                "current_step": "Completado",
                "total_records": 138000,
                "zeolite_types": 45,
                "samples": 3000,
                "spectra": 9000,
                "peaks": 72000,
                "analysis_records": 54000
            }
        }


class DatasetSummary(BaseModel):
    """Resumen del dataset"""
    zeolite_types: int
    samples: int
    spectra: int
    peaks: int
    analysis_records: int
    total_records: int
    last_updated: Optional[datetime] = None

    class Config:
        schema_extra = {
            "example": {
                "zeolite_types": 45,
                "samples": 3000,
                "spectra": 9000,
                "peaks": 72000,
                "analysis_records": 54000,
                "total_records": 138000,
                "last_updated": "2026-03-19T12:00:00"
            }
        }


class LoadDatasetResponse(BaseModel):
    """Respuesta de carga del dataset"""
    success: bool
    message: str
    summary: Optional[DatasetSummary] = None
    duration_seconds: Optional[float] = None
    error: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "success": True,
                "message": "Dataset cargado exitosamente",
                "summary": {
                    "zeolite_types": 45,
                    "samples": 3000,
                    "spectra": 9000,
                    "peaks": 72000,
                    "analysis_records": 54000,
                    "total_records": 138000,
                    "last_updated": "2026-03-19T12:00:00"
                },
                "duration_seconds": 120.5
            }
        }


class ClearDatasetResponse(BaseModel):
    """Respuesta de limpieza del dataset"""
    success: bool
    message: str
    deleted_records: Optional[int] = None
    error: Optional[str] = None