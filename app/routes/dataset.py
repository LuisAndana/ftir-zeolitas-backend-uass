"""
Rutas para gestión del dataset de zeolitas FTIR
"""

import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Optional
from datetime import datetime

from app.services.zeolite_dataset_loader import ZeoliteDatasetLoader
from app.models.dataset_models import (
    DatasetStatus, DatasetSummary, LoadDatasetResponse, ClearDatasetResponse
)
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Variable global para rastrear el estado de carga
_loader_state = {
    "is_loading": False,
    "progress_percent": 0,
    "current_step": "Idle",
    "last_summary": None
}


def _get_db_config():
    """Obtener configuración de base de datos"""
    return {
        "host": settings.db_host,
        "user": settings.db_user,
        "password": settings.db_password,
        "database": settings.db_name,
    }


def _get_summary() -> DatasetSummary:
    """Obtener resumen del dataset"""
    try:
        loader = ZeoliteDatasetLoader(**_get_db_config())
        if not loader.connect():
            return None

        summary_dict = loader.get_summary()
        loader.disconnect()

        summary_dict["last_updated"] = datetime.now()
        return DatasetSummary(**summary_dict)
    except Exception as e:
        logger.error(f"Error obteniendo resumen: {e}")
        return None


@router.post(
    "/load",
    response_model=LoadDatasetResponse,
    summary="Cargar dataset completo",
    tags=["dataset"]
)
async def load_dataset(background_tasks: BackgroundTasks):
    """
    Cargar dataset completo de zeolitas FTIR

    - **3000+ muestras** de zeolitas
    - **9000+ espectros FTIR**
    - **72000+ picos identificados**
    - **54000+ análisis**
    - **45+ tipos de zeolitas**

    ⚠️ Nota: Esta operación puede tomar varios minutos
    """

    if _loader_state["is_loading"]:
        raise HTTPException(
            status_code=409,
            detail="Ya hay una carga en progreso"
        )

    def load_in_background():
        """Ejecutar carga en background"""
        _loader_state["is_loading"] = True
        _loader_state["progress_percent"] = 0
        _loader_state["current_step"] = "Iniciando..."

        try:
            start_time = datetime.now()

            loader = ZeoliteDatasetLoader(**_get_db_config())

            _loader_state["current_step"] = "Conectando a BD..."
            if not loader.connect():
                raise Exception("No se pudo conectar a la base de datos")

            _loader_state["current_step"] = "Creando tablas..."
            _loader_state["progress_percent"] = 10
            if not loader.create_tables():
                raise Exception("Error creando tablas")

            _loader_state["current_step"] = "Insertando tipos de zeolitas..."
            _loader_state["progress_percent"] = 20
            if not loader.insert_zeolite_types():
                raise Exception("Error insertando tipos de zeolitas")

            _loader_state["current_step"] = "Generando muestras..."
            _loader_state["progress_percent"] = 30
            if not loader.generate_samples(3000):
                raise Exception("Error generando muestras")

            _loader_state["current_step"] = "Generando espectros FTIR..."
            _loader_state["progress_percent"] = 50
            if not loader.generate_ftir_spectra(9000):
                raise Exception("Error generando espectros")

            _loader_state["current_step"] = "Generando picos FTIR..."
            _loader_state["progress_percent"] = 70
            if not loader.generate_ftir_peaks():
                raise Exception("Error generando picos")

            _loader_state["current_step"] = "Generando análisis..."
            _loader_state["progress_percent"] = 85
            if not loader.generate_analysis():
                raise Exception("Error generando análisis")

            _loader_state["current_step"] = "Finalizando..."
            _loader_state["progress_percent"] = 95

            summary = _get_summary()
            _loader_state["last_summary"] = summary
            _loader_state["progress_percent"] = 100
            _loader_state["current_step"] = "Completado"

            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Dataset cargado en {duration:.2f} segundos")

        except Exception as e:
            logger.error(f"❌ Error en carga: {e}")
            _loader_state["current_step"] = f"Error: {str(e)}"
        finally:
            _loader_state["is_loading"] = False

    background_tasks.add_task(load_in_background)

    return LoadDatasetResponse(
        success=True,
        message="Carga de dataset iniciada. Verifica el estado con /api/dataset/status",
        summary=None
    )


@router.get(
    "/status",
    response_model=DatasetStatus,
    summary="Estado de la carga",
    tags=["dataset"]
)
async def get_status():
    """Obtener estado actual de la carga del dataset"""

    summary = _loader_state.get("last_summary") or _get_summary()

    if summary is None:
        summary = DatasetSummary(
            zeolite_types=0,
            samples=0,
            spectra=0,
            peaks=0,
            analysis_records=0,
            total_records=0
        )

    return DatasetStatus(
        is_loading=_loader_state["is_loading"],
        progress_percent=_loader_state["progress_percent"],
        current_step=_loader_state["current_step"],
        total_records=summary.total_records,
        zeolite_types=summary.zeolite_types,
        samples=summary.samples,
        spectra=summary.spectra,
        peaks=summary.peaks,
        analysis_records=summary.analysis_records
    )


@router.get(
    "/summary",
    response_model=DatasetSummary,
    summary="Resumen del dataset",
    tags=["dataset"]
)
async def get_summary():
    """Obtener resumen del dataset actual"""

    summary = _get_summary()
    if summary is None:
        raise HTTPException(
            status_code=500,
            detail="Error obteniendo resumen del dataset"
        )
    return summary


@router.delete(
    "/clear",
    response_model=ClearDatasetResponse,
    summary="Limpiar dataset",
    tags=["dataset"]
)
async def clear_dataset():
    """
    ⚠️ ADVERTENCIA: Elimina TODOS los datos del dataset

    Esta operación es irreversible. Elimina:
    - Todas las muestras
    - Todos los espectros FTIR
    - Todos los picos identificados
    - Todos los análisis
    """

    if _loader_state["is_loading"]:
        raise HTTPException(
            status_code=409,
            detail="No se puede limpiar mientras hay una carga en progreso"
        )

    try:
        loader = ZeoliteDatasetLoader(**_get_db_config())
        if not loader.connect():
            raise Exception("No se pudo conectar a la base de datos")

        if not loader.clear_all_data():
            raise Exception("Error limpiando datos")

        loader.disconnect()

        _loader_state["progress_percent"] = 0
        _loader_state["current_step"] = "Idle"
        _loader_state["last_summary"] = None

        return ClearDatasetResponse(
            success=True,
            message="Dataset limpiado exitosamente",
            deleted_records=None
        )

    except Exception as e:
        logger.error(f"Error limpiando dataset: {e}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )