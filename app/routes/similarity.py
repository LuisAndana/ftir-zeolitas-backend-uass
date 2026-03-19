"""
Rutas para búsqueda de similitud espectral FTIR
CU-F-005: Ejecutar búsqueda de similitud
CU-F-006: Comparar dos espectros
Integrado con dataset de zeolitas FTIR
"""

import logging
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import numpy as np
from scipy.spatial.distance import euclidean, cosine
from scipy.stats import pearsonr

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.spectrum import Spectrum
from app.models.user import User
from app.schemas.similarity import SimilaritySearchRequest
from app.services.similarity_calculator import SimilarityCalculator
import mysql.connector
from mysql.connector import Error

logger = logging.getLogger(__name__)
router = APIRouter()

# Inicializar calculadora de similitud
calculator = SimilarityCalculator()

# ========================================
# FUNCIONES AUXILIARES PARA DATASET
# ========================================

def get_db_config():
    """Obtener configuración de base de datos"""
    from app.core.config import settings
    return {
        "host": settings.db_host,
        "user": settings.db_user,
        "password": settings.db_password,
        "database": settings.db_name,
    }

def connect_dataset_db():
    """Conectar a la base de datos del dataset"""
    try:
        config = get_db_config()
        connection = mysql.connector.connect(
            host=config["host"],
            user=config["user"],
            password=config["password"],
            database=config["database"]
        )
        return connection
    except Error as e:
        logger.error(f"Error de conexión al dataset: {e}")
        return None

def normalize_spectrum(intensities):
    """Normalizar espectro"""
    arr = np.array(intensities)
    min_val = np.min(arr)
    max_val = np.max(arr)
    if max_val - min_val == 0:
        return arr
    return (arr - min_val) / (max_val - min_val)

def calculate_euclidean_similarity(spectrum1, spectrum2):
    """Calcular similitud Euclidiana (0-1) - CORREGIDO"""
    try:
        if len(spectrum1) == 0 or len(spectrum2) == 0:
            return 0.0
        min_len = min(len(spectrum1), len(spectrum2))
        spec1 = spectrum1[:min_len]
        spec2 = spectrum2[:min_len]
        distance = euclidean(spec1, spec2)
        similarity = 1 / (1 + distance)
        return float(round(similarity, 4))
    except Exception as e:
        logger.warning(f"Error en euclidean_similarity: {e}")
        return 0.0

def calculate_cosine_similarity(spectrum1, spectrum2):
    """Calcular similitud del coseno (0-1) - CORREGIDO"""
    try:
        if len(spectrum1) == 0 or len(spectrum2) == 0:
            return 0.0
        min_len = min(len(spectrum1), len(spectrum2))
        spec1 = spectrum1[:min_len]
        spec2 = spectrum2[:min_len]
        # ✅ CORRECCIÓN: Fórmula correcta para convertir distancia coseno a similitud
        distance = cosine(spec1, spec2)
        similarity = (1 - distance) / 2  # Rango 0-1
        return float(round(similarity, 4))
    except Exception as e:
        logger.warning(f"Error en cosine_similarity: {e}")
        return 0.0

def calculate_pearson_similarity(spectrum1, spectrum2):
    """Calcular similitud de Pearson (0-1)"""
    try:
        if len(spectrum1) < 2 or len(spectrum2) < 2:
            return 0.0
        min_len = min(len(spectrum1), len(spectrum2))
        spec1 = spectrum1[:min_len]
        spec2 = spectrum2[:min_len]
        correlation, _ = pearsonr(spec1, spec2)
        similarity = (correlation + 1) / 2
        return float(round(similarity, 4))
    except Exception as e:
        logger.warning(f"Error en pearson_similarity: {e}")
        return 0.0

def detect_peaks_simple(wavenumbers: np.ndarray, absorbance: np.ndarray, threshold: float = 0.01) -> list:
    """
    Detectar picos locales en espectro normalizado
    Retorna lista de wavenumbers donde hay picos
    """
    if len(absorbance) < 3:
        return []

    try:
        # Normalizar absorbance
        abs_arr = np.array(absorbance, dtype=float)
        max_abs = np.max(abs_arr)
        min_abs = np.min(abs_arr)

        if max_abs == min_abs:
            return []

        norm_abs = (abs_arr - min_abs) / (max_abs - min_abs)
        peaks = []

        # Detectar máximos locales
        for i in range(1, len(norm_abs) - 1):
            if (norm_abs[i] > norm_abs[i-1] and
                norm_abs[i] > norm_abs[i+1] and
                norm_abs[i] > threshold):
                peaks.append(float(wavenumbers[i]))

        return peaks
    except Exception as e:
        logger.error(f"Error en detect_peaks_simple: {e}")
        return []

def match_peaks_simple(peaks1: list, peaks2: list, tolerance: float = 4) -> dict:
    """
    Emparejar picos entre dos espectros
    Retorna dict con matched, unmatched, total y matched_count
    """
    matched = []
    unmatched = []

    for p1 in peaks1:
        found = False
        for p2 in peaks2:
            if abs(p1 - p2) <= tolerance:
                matched.append(p1)
                found = True
                break
        if not found:
            unmatched.append(p1)

    return {
        "matched": matched,
        "unmatched": unmatched,
        "total": len(peaks1),
        "matched_count": len(matched)
    }

def get_spectrum_from_dataset(spectrum_id):
    """Obtener espectro desde el dataset"""
    try:
        connection = connect_dataset_db()
        if not connection:
            return None

        cursor = connection.cursor()
        cursor.execute("""
            SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            WHERE fs.id = %s
        """, (spectrum_id,))

        result = cursor.fetchone()
        cursor.close()
        connection.close()

        if result:
            return {
                "id": result[0],
                "spectrum_data": json.loads(result[1]),
                "sample_code": result[2],
                "zeolite_name": result[3],
                "equipment": result[4]
            }
        return None
    except Error as e:
        logger.error(f"Error obteniendo espectro del dataset: {e}")
        return None

def search_similar_in_dataset(spectrum_id, method="pearson", top_n=10, min_similarity=0.5, tolerance=4):
    """
    Buscar espectros similares en el dataset CON detección de picos
    """
    try:
        connection = connect_dataset_db()
        if not connection:
            return []

        cursor = connection.cursor()

        # Obtener espectro de referencia
        cursor.execute("""
            SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            WHERE fs.id = %s
        """, (spectrum_id,))

        ref_result = cursor.fetchone()
        if not ref_result:
            cursor.close()
            connection.close()
            return []

        ref_data = json.loads(ref_result[1])
        ref_intensities = np.array(ref_data["intensities"])
        ref_intensities_norm = normalize_spectrum(ref_intensities)

        # ✅ NUEVO: Detectar picos en el espectro de referencia
        ref_wavenumbers = np.array(range(len(ref_intensities)))
        ref_peaks = detect_peaks_simple(ref_wavenumbers, ref_intensities_norm, threshold=0.01)
        logger.debug(f"Picos detectados en referencia: {len(ref_peaks)}")

        # Obtener todos los espectros
        cursor.execute("""
            SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment, fs.measurement_date
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            WHERE fs.id != %s
            LIMIT 5000
        """, (spectrum_id,))

        all_spectra = cursor.fetchall()
        similarities = []

        for spec in all_spectra:
            spec_data = json.loads(spec[1])
            spec_intensities = np.array(spec_data["intensities"])
            spec_intensities_norm = normalize_spectrum(spec_intensities)

            # Calcular similitud
            if method == "euclidean":
                similarity = calculate_euclidean_similarity(ref_intensities_norm, spec_intensities_norm)
            elif method == "cosine":
                similarity = calculate_cosine_similarity(ref_intensities_norm, spec_intensities_norm)
            elif method == "pearson":
                similarity = calculate_pearson_similarity(ref_intensities_norm, spec_intensities_norm)
            elif method == "combined":
                euc = calculate_euclidean_similarity(ref_intensities_norm, spec_intensities_norm)
                cos = calculate_cosine_similarity(ref_intensities_norm, spec_intensities_norm)
                pea = calculate_pearson_similarity(ref_intensities_norm, spec_intensities_norm)
                similarity = (euc * 0.33 + cos * 0.33 + pea * 0.34)
            else:
                similarity = 0.0

            if similarity >= min_similarity:
                # ✅ NUEVO: Detectar picos en este espectro y emparejar
                spec_wavenumbers = np.array(range(len(spec_intensities)))
                spec_peaks = detect_peaks_simple(spec_wavenumbers, spec_intensities_norm, threshold=0.01)
                peak_match = match_peaks_simple(ref_peaks, spec_peaks, tolerance=tolerance)

                similarities.append({
                    "spectrum_id": spec[0],
                    "sample_code": spec[2],
                    "zeolite_name": spec[3],
                    "equipment": spec[4],
                    "measurement_date": str(spec[5]) if spec[5] else "N/A",
                    "similarity": similarity,
                    "matching_peaks": peak_match["matched_count"],
                    "total_peaks": peak_match["total"]
                })

        cursor.close()
        connection.close()

        # Ordenar por similitud
        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        return similarities[:top_n]

    except Error as e:
        logger.error(f"Error en búsqueda del dataset: {e}")
        return []

# ========================================
# ENDPOINTS MEJORADOS
# ========================================

@router.post("/search", summary="CU-F-005: Búsqueda de similitud")
def search_similarity(
    request: SimilaritySearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Ejecutar búsqueda de similitud espectral

    Busca en:
    1. Espectros del usuario en la BD principal
    2. Dataset de zeolitas FTIR (si está disponible)
    """

    try:
        logger.info(f"🔍 Búsqueda de similitud - Usuario: {current_user.id}")

        # Obtener espectros del usuario
        query_spectrum = db.query(Spectrum).filter(
            Spectrum.id == request.query_spectrum_id,
            Spectrum.user_id == current_user.id
        ).first()

        if not query_spectrum:
            logger.warning(f"Espectro {request.query_spectrum_id} no encontrado")
            raise HTTPException(status_code=404, detail="Espectro no encontrado")

        spectra_to_search = db.query(Spectrum).filter(
            Spectrum.id != request.query_spectrum_id,
            Spectrum.user_id == current_user.id
        ).all()

        logger.info(f"📊 Procesando {len(spectra_to_search)} espectros del usuario")

        config = request.config
        method = config.method or "pearson"
        tolerance = config.tolerance or 4
        range_min = config.range_min or 400
        range_max = config.range_max or 4000
        top_n = config.top_n or 10
        family_filter = config.family_filter

        logger.info(f"⚙️ Parámetros: método={method}, tolerancia={tolerance}, rango={range_min}-{range_max}, top_n={top_n}")

        results = []

        # Búsqueda en espectros del usuario
        for spectrum in spectra_to_search:
            if family_filter and spectrum.material != family_filter:
                continue

            try:
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
                        "source": "user_database",
                        "rank": 0
                    })
            except Exception as e:
                logger.error(f"Error comparando espectro {spectrum.id}: {e}")
                continue

        # Búsqueda en dataset de zeolitas
        dataset_results = search_similar_in_dataset(
            request.query_spectrum_id,
            method=method.lower() if method in ["euclidean", "cosine", "pearson"] else "pearson",
            top_n=top_n,
            min_similarity=0.5,
            tolerance=tolerance
        )

        for result in dataset_results:
            results.append({
                "spectrum_id": result["spectrum_id"],
                "filename": f"{result['sample_code']} ({result['zeolite_name']})",
                "family": result["zeolite_name"],
                "global_score": result["similarity"],
                "window_scores": [],
                "matching_peaks": result.get("matching_peaks", 0),
                "total_peaks": result.get("total_peaks", 0),
                "source": "zeolite_dataset",
                "equipment": result["equipment"],
                "rank": 0
            })

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
                "total_user_spectra_searched": len(spectra_to_search),
                "total_dataset_spectra_searched": len(dataset_results),
                "results_found": len(results),
                "user_results": sum(1 for r in results if r.get("source") == "user_database"),
                "dataset_results": sum(1 for r in results if r.get("source") == "zeolite_dataset"),
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
        method: str = Query("pearson"),
        tolerance: float = Query(4),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    Comparar dos espectros específicos
    Puede comparar espectros del usuario o del dataset
    """

    try:
        logger.info(f"🔄 Comparación - Usuario: {current_user.id}")
        logger.info(f"   Query ID: {query_id} | Reference ID: {reference_id}")
        logger.info(f"   Método: {method} | Tolerancia: {tolerance}")

        # ✅ VALIDAR PARÁMETROS
        valid_methods = ["cosine", "pearson", "euclidean"]
        if method not in valid_methods:
            method = "pearson"
            logger.warning(f"⚠️ Método inválido, usando pearson")

        # Intentar obtener espectros del usuario
        query_spectrum = db.query(Spectrum).filter(
            Spectrum.id == query_id,
            Spectrum.user_id == current_user.id
        ).first()

        reference_spectrum = db.query(Spectrum).filter(
            Spectrum.id == reference_id,
            Spectrum.user_id == current_user.id
        ).first()

        if query_spectrum and reference_spectrum:
            logger.info(f"✅ Ambos espectros encontrados en usuario database")

            # Comparación entre espectros del usuario
            similarity_score = calculator.calculate_similarity(
                spectrum1=query_spectrum,
                spectrum2=reference_spectrum,
                method=method,
                tolerance=tolerance,
                range_min=400,
                range_max=4000
            )

            if similarity_score is None:
                logger.error(f"❌ Calculator retornó None")
                return {
                    "success": False,
                    "message": "No se pudo calcular similitud",
                    "data": None
                }

            logger.info(f"✅ Similitud calculada: {similarity_score.get('global_score', 0)}")

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
                        "filename": query_spectrum.filename,
                        "source": "user_database"
                    },
                    "reference_spectrum": {
                        "id": reference_spectrum.id,
                        "filename": reference_spectrum.filename,
                        "source": "user_database"
                    }
                }
            }

        logger.info(f"🔍 Espectros no en usuario database, buscando en dataset...")

        # Intentar obtener del dataset
        query_dataset = get_spectrum_from_dataset(query_id)
        reference_dataset = get_spectrum_from_dataset(reference_id)

        if query_dataset and reference_dataset:
            logger.info(f"✅ Ambos espectros encontrados en dataset")
            logger.info(f"   Query: {query_dataset['sample_code']} | Reference: {reference_dataset['sample_code']}")

            query_intensities = np.array(query_dataset["spectrum_data"]["intensities"])
            ref_intensities = np.array(reference_dataset["spectrum_data"]["intensities"])

            logger.info(f"   Datos cargados: Query {len(query_intensities)} puntos | Ref {len(ref_intensities)} puntos")

            # ✅ VALIDAR DATOS NO VACÍOS
            if len(query_intensities) == 0 or len(ref_intensities) == 0:
                logger.error(f"❌ Espectros sin datos (vacíos)")
                return {
                    "success": False,
                    "message": "Espectros sin datos para comparación",
                    "data": None
                }

            query_norm = normalize_spectrum(query_intensities)
            ref_norm = normalize_spectrum(ref_intensities)

            logger.info(f"   Normalizados: Query min={np.min(query_norm):.4f}, max={np.max(query_norm):.4f}")
            logger.info(f"   Normalizados: Ref min={np.min(ref_norm):.4f}, max={np.max(ref_norm):.4f}")

            # ✅ CALCULAR TODOS LOS SCORES
            scores = {
                "euclidean": calculate_euclidean_similarity(query_norm, ref_norm),
                "cosine": calculate_cosine_similarity(query_norm, ref_norm),
                "pearson": calculate_pearson_similarity(query_norm, ref_norm)
            }

            logger.info(f"📈 Scores calculados:")
            logger.info(f"   Euclidean: {scores['euclidean']:.4f}")
            logger.info(f"   Cosine: {scores['cosine']:.4f}")
            logger.info(f"   Pearson: {scores['pearson']:.4f}")

            # ✅ OBTENER SCORE SELECCIONADO CON VALIDACIÓN
            selected_score = scores.get(method, scores["pearson"])

            # ✅ ASEGURAR RANGO 0-1
            if selected_score < 0:
                selected_score = 0.0
            elif selected_score > 1:
                selected_score = 1.0

            selected_score = float(round(selected_score, 4))
            logger.info(f"✅ Score final ({method}): {selected_score:.4f} ({selected_score * 100:.2f}%)")

            # ✅ DETECTAR PICOS Y EMPAREJAR
            query_wavenumbers = np.array(range(len(query_intensities)))
            ref_wavenumbers = np.array(range(len(ref_intensities)))
            query_peaks = detect_peaks_simple(query_wavenumbers, query_norm, threshold=0.01)
            ref_peaks = detect_peaks_simple(ref_wavenumbers, ref_norm, threshold=0.01)
            peak_match = match_peaks_simple(query_peaks, ref_peaks, tolerance=tolerance)

            logger.info(f"🎯 Picos detectados: Query {len(query_peaks)} | Ref {len(ref_peaks)}")
            logger.info(f"   Coincidencias: {peak_match['matched_count']}/{len(query_peaks)}")

            return {
                "success": True,
                "message": "Comparación completada",
                "data": {
                    "global_score": selected_score,
                    "all_scores": {
                        "euclidean": float(round(scores["euclidean"], 4)),
                        "cosine": float(round(scores["cosine"], 4)),
                        "pearson": float(round(scores["pearson"], 4))
                    },
                    "method_used": method,
                    "matched_peaks": peak_match["matched"],
                    "unmatched_peaks": peak_match["unmatched"],
                    "total_peaks": peak_match["total"],
                    "matching_peaks_count": peak_match["matched_count"],
                    "query_spectrum": {
                        "id": query_dataset["id"],
                        "filename": query_dataset["sample_code"],
                        "zeolite": query_dataset["zeolite_name"],
                        "source": "zeolite_dataset"
                    },
                    "reference_spectrum": {
                        "id": reference_dataset["id"],
                        "filename": reference_dataset["sample_code"],
                        "zeolite": reference_dataset["zeolite_name"],
                        "source": "zeolite_dataset"
                    }
                }
            }

        logger.error(f"❌ Espectros no encontrados en ninguna BD")
        raise HTTPException(status_code=404, detail="Espectros no encontrados")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en comparación: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get("/spectrum/{spectrum_id}")
def get_spectrum_info(spectrum_id: int):
    """Obtener información de un espectro específico"""
    try:
        connection = connect_dataset_db()
        if not connection:
            raise HTTPException(status_code=500, detail="No se pudo conectar a la BD")

        cursor = connection.cursor()
        cursor.execute("""
                       SELECT fs.id,
                              fs.spectrum_data,
                              zs.sample_code,
                              zt.name,
                              fs.equipment,
                              fs.measurement_date
                       FROM ftir_spectra fs
                                JOIN zeolite_samples zs ON fs.sample_id = zs.id
                                JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
                       WHERE fs.id = %s
                       """, (spectrum_id,))

        result = cursor.fetchone()
        cursor.close()
        connection.close()

        if not result:
            raise HTTPException(status_code=404, detail="Espectro no encontrado")

        return {
            "success": True,
            "spectrum": {
                "id": result[0],
                "spectrum_data": json.loads(result[1]),
                "sample_code": result[2],
                "zeolite_name": result[3],
                "equipment": result[4],
                "measurement_date": str(result[5]) if result[5] else "N/A"
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo espectro: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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