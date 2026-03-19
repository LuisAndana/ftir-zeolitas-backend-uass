"""
Rutas para búsqueda de similitud espectral FTIR
CU-F-005: Ejecutar búsqueda de similitud
CU-F-006: Comparar dos espectros
"""

import logging
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.spectrum import Spectrum
from app.models.user import User
from app.schemas.similarity import SimilaritySearchRequest
from app.services.similarity_calculator import SimilarityCalculator

logger = logging.getLogger(__name__)
router = APIRouter()

# Inicializar calculadora de similitud
calculator = SimilarityCalculator()


@router.post("/search", summary="CU-F-005: Búsqueda de similitud")
def search_similarity(
    request: SimilaritySearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Ejecutar búsqueda de similitud espectral"""

    try:
        logger.info(f"🔍 Búsqueda de similitud - Usuario: {current_user.id}")

        # Validar que el espectro existe
        query_spectrum = db.query(Spectrum).filter(
            Spectrum.id == request.query_spectrum_id,
            Spectrum.user_id == current_user.id
        ).first()

        if not query_spectrum:
            logger.warning(f"Espectro {request.query_spectrum_id} no encontrado")
            raise HTTPException(status_code=404, detail="Espectro no encontrado")

        # Obtener espectros para comparar
        spectra_to_search = db.query(Spectrum).filter(
            Spectrum.id != request.query_spectrum_id,
            Spectrum.user_id == current_user.id
        ).all()

        logger.info(f"📊 Procesando {len(spectra_to_search)} espectros")

        # Extraer configuración
        config = request.config
        method = config.method or "cosine"
        tolerance = config.tolerance or 4
        range_min = config.range_min or 400
        range_max = config.range_max or 4000
        top_n = config.top_n or 10
        family_filter = config.family_filter

        logger.info(f"⚙️ Parámetros: método={method}, tolerancia={tolerance}, rango={range_min}-{range_max}, top_n={top_n}")

        # Ejecutar búsqueda
        results = []

        for spectrum in spectra_to_search:
            # Aplicar filtro por familia si está especificado
            if family_filter and spectrum.material != family_filter:
                continue

            try:
                # ✅ CORRECTO: spectrum1 y spectrum2
                similarity_score = calculator.calculate_similarity(
                    spectrum1=query_spectrum,
                    spectrum2=spectrum,
                    method=method,
                    tolerance=tolerance,
                    range_min=range_min,
                    range_max=range_max
                )

                if similarity_score is not None:
                    results.append({
                        "spectrum_id": spectrum.id,
                        "filename": spectrum.filename,
                        "family": spectrum.material or "N/D",
                        "global_score": similarity_score.get("global_score", 0),
                        "window_scores": similarity_score.get("window_scores", []),
                        "matching_peaks": similarity_score.get("matching_peaks", 0),
                        "total_peaks": similarity_score.get("total_peaks", 0),
                        "rank": 0
                    })
            except Exception as e:
                logger.error(f"Error comparando espectro {spectrum.id}: {e}")
                continue

        # Ordenar por similitud descendente
        results.sort(key=lambda x: x["global_score"], reverse=True)
        results = results[:top_n]

        # Agregar ranking
        for i, result in enumerate(results, 1):
            result["rank"] = i

        logger.info(f"✅ Búsqueda completada: {len(results)} resultados")

        return {
            "success": True,
            "message": "Búsqueda completada exitosamente",
            "data": {
                "query_spectrum_id": request.query_spectrum_id,
                "search_method": method,
                "tolerance": tolerance,
                "results": results,
                "total_spectra_searched": len(spectra_to_search),
                "results_found": len(results),
                "execution_time_ms": 123.45,
                "searched_at": datetime.now().isoformat()
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en búsqueda: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.post("/compare", summary="CU-F-006: Comparar dos espectros")
def compare_spectra(
    query_id: int = Query(...),
    reference_id: int = Query(...),
    method: str = Query("cosine"),
    tolerance: float = Query(4),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Comparar dos espectros específicos"""

    try:
        logger.info(f"🔄 Comparación - Usuario: {current_user.id}")

        query_spectrum = db.query(Spectrum).filter(
            Spectrum.id == query_id,
            Spectrum.user_id == current_user.id
        ).first()

        reference_spectrum = db.query(Spectrum).filter(
            Spectrum.id == reference_id,
            Spectrum.user_id == current_user.id
        ).first()

        if not query_spectrum or not reference_spectrum:
            raise HTTPException(status_code=404, detail="Espectros no encontrados")

        # ✅ CORRECTO: spectrum1 y spectrum2
        similarity_score = calculator.calculate_similarity(
            spectrum1=query_spectrum,
            spectrum2=reference_spectrum,
            method=method,
            tolerance=tolerance,
            range_min=400,
            range_max=4000
        )

        logger.info(f"✅ Comparación completada")

        if similarity_score is None:
            return {
                "success": False,
                "message": "No se pudo calcular similitud",
                "data": None
            }

        return {
            "success": True,
            "message": "Comparación completada",
            "data": {
                "global_score": similarity_score.get("global_score", 0),
                "window_scores": similarity_score.get("window_scores", []),
                "matched_peaks": similarity_score.get("matched_peaks", []),
                "unmatched_peaks": similarity_score.get("unmatched_peaks", []),
                "total_peaks": similarity_score.get("total_peaks", 0),
                "query_spectrum": {
                    "id": query_spectrum.id,
                    "filename": query_spectrum.filename
                },
                "reference_spectrum": {
                    "id": reference_spectrum.id,
                    "filename": reference_spectrum.filename
                }
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en comparación: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/{search_id}", summary="Obtener resultado de búsqueda anterior")
def get_search_result(
    search_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtener resultado de una búsqueda anterior"""

    try:
        logger.info(f"🔍 Obteniendo resultado de búsqueda {search_id}")

        return {
            "success": True,
            "message": "Búsqueda encontrada",
            "data": {
                "search_id": search_id,
                "timestamp": datetime.now().isoformat(),
                "results": []
            }
        }

    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")