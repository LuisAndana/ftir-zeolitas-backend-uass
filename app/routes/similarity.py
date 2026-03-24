"""
⚡ BÚSQUEDA DE SIMILITUD ULTRA-OPTIMIZADA CON MANEJO DE ERRORES
"""

import logging
import json
import time
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import numpy as np
from scipy.spatial.distance import euclidean, cosine
from scipy.stats import pearsonr
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Dict, List, Tuple, Optional

from app.core.database import get_db, SessionLocal
from app.core.security import get_current_user
from app.models.spectrum import Spectrum
from app.models.user import User
from app.schemas.similarity import SimilaritySearchRequest
from app.services.similarity_calculator import SimilarityCalculator
import mysql.connector
from mysql.connector import Error

logger = logging.getLogger(__name__)
router = APIRouter()
calculator = SimilarityCalculator()

# ========================================
# CACHE EN MEMORIA
# ========================================

class SpectrumCache:
    """Cache en memoria para espectros"""

    def __init__(self, ttl_minutes: int = 60):
        self.cache: Dict = {}
        self.peaks_cache: Dict = {}
        self.ttl = timedelta(minutes=ttl_minutes)
        self.lock = Lock()

    def get(self, spectrum_id: int) -> Optional[Dict]:
        with self.lock:
            if spectrum_id in self.cache:
                data, timestamp = self.cache[spectrum_id]
                if datetime.now() - timestamp < self.ttl:
                    return data
                else:
                    del self.cache[spectrum_id]
        return None

    def set(self, spectrum_id: int, data: Dict):
        with self.lock:
            self.cache[spectrum_id] = (data, datetime.now())

    def clear_old(self):
        with self.lock:
            now = datetime.now()
            self.cache = {k: v for k, v in self.cache.items()
                         if now - v[1] < self.ttl}

spectrum_cache = SpectrumCache(ttl_minutes=60)

# ========================================
# CONFIGURACIÓN BD
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
            database=config["database"],
            autocommit=True,
            connection_timeout=5
        )
        return connection
    except Error as e:
        logger.error(f"❌ Error conexión dataset: {e}")
        return None

# ========================================
# FUNCIONES VECTORIZADAS
# ========================================

def normalize_spectrum(intensities: np.ndarray) -> np.ndarray:
    """Normalizar espectro"""
    arr = np.array(intensities, dtype=np.float32)
    min_val = np.min(arr)
    max_val = np.max(arr)
    if max_val - min_val == 0:
        return arr
    return (arr - min_val) / (max_val - min_val)

def normalize_spectra_batch(spectra_list: np.ndarray) -> np.ndarray:
    """Normalizar múltiples espectros vectorizadamente"""
    min_vals = np.min(spectra_list, axis=1, keepdims=True)
    max_vals = np.max(spectra_list, axis=1, keepdims=True)
    ranges = max_vals - min_vals
    ranges[ranges == 0] = 1
    return (spectra_list - min_vals) / ranges

def calculate_similarities_vectorized(
    ref_spectrum: np.ndarray,
    test_spectra: List[np.ndarray],
    method: str = "cosine"
) -> np.ndarray:
    """Calcular similitudes vectorizadamente"""
    try:
        min_len = min(len(ref_spectrum), min((len(s) for s in test_spectra), default=0))
        if min_len == 0:
            return np.array([0.0] * len(test_spectra))

        ref = ref_spectrum[:min_len]
        test_array = np.array([s[:min_len] for s in test_spectra], dtype=np.float32)

        if method == "cosine":
            norm_ref = np.linalg.norm(ref)
            norm_test = np.linalg.norm(test_array, axis=1)
            dot_products = np.dot(test_array, ref)
            similarities = dot_products / (norm_ref * norm_test + 1e-10)
            return np.clip((similarities + 1) / 2, 0, 1)

        elif method == "pearson":
            ref_centered = ref - np.mean(ref)
            test_centered = test_array - np.mean(test_array, axis=1, keepdims=True)
            cov = np.sum(ref_centered * test_centered, axis=1)
            std_ref = np.std(ref)
            std_test = np.std(test_array, axis=1)
            correlations = cov / (std_ref * std_test + 1e-10)
            return np.clip((correlations + 1) / 2, 0, 1)

        elif method == "euclidean":
            distances = np.linalg.norm(test_array - ref, axis=1)
            return 1 / (1 + distances)

        return np.array([0.5] * len(test_spectra))

    except Exception as e:
        logger.warning(f"Error cálculo vectorizado: {e}")
        return np.array([0.0] * len(test_spectra))

def detect_peaks_vectorized(wavenumbers: np.ndarray, absorbance: np.ndarray, threshold: float = 0.01) -> List[float]:
    """Detectar picos vectorizadamente"""
    if len(absorbance) < 3:
        return []

    try:
        abs_arr = np.array(absorbance, dtype=np.float32)
        max_abs = np.max(abs_arr)
        min_abs = np.min(abs_arr)

        if max_abs == min_abs:
            return []

        norm_abs = (abs_arr - min_abs) / (max_abs - min_abs)
        is_greater_left = norm_abs[1:-1] > norm_abs[:-2]
        is_greater_right = norm_abs[1:-1] > norm_abs[2:]
        is_peak = is_greater_left & is_greater_right & (norm_abs[1:-1] > threshold)

        peak_indices = np.where(is_peak)[0] + 1
        return [float(wavenumbers[i]) for i in peak_indices]

    except Exception as e:
        logger.debug(f"Error detect_peaks: {e}")
        return []

def match_peaks_vectorized(peaks1: List[float], peaks2: List[float], tolerance: float = 4) -> Dict:
    """Emparejar picos vectorizadamente"""
    if not peaks1 or not peaks2:
        return {"matched": [], "unmatched": peaks1, "total": len(peaks1), "matched_count": 0}

    peaks1_arr = np.array(peaks1, dtype=np.float32)
    peaks2_arr = np.array(peaks2, dtype=np.float32)

    distances = np.abs(peaks1_arr[:, np.newaxis] - peaks2_arr[np.newaxis, :])
    matched_mask = np.any(distances <= tolerance, axis=1)
    matched_count = np.sum(matched_mask)

    return {
        "matched": peaks1_arr[matched_mask].tolist(),
        "unmatched": peaks1_arr[~matched_mask].tolist(),
        "total": len(peaks1),
        "matched_count": int(matched_count)
    }

# ========================================
# BÚSQUEDA EN DATASET
# ========================================

def search_similar_in_dataset_ultra_fast(
    spectrum_id: int,
    method: str = "pearson",
    top_n: int = 10,
    min_similarity: float = 0.5,
    tolerance: float = 4,
    max_workers: int = 12
) -> List[Dict]:
    """
    ⚡ BÚSQUEDA ULTRA-OPTIMIZADA EN DATASET
    """
    start_time = time.time()

    try:
        connection = connect_dataset_db()
        if not connection:
            logger.warning("⚠️ No hay conexión al dataset")
            return []

        cursor = connection.cursor()

        # ✅ Obtener espectro de referencia
        cursor.execute("""
            SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            WHERE fs.id = %s
        """, (spectrum_id,))

        ref_result = cursor.fetchone()
        if not ref_result:
            logger.warning(f"⚠️ Espectro de referencia {spectrum_id} no encontrado en dataset")
            cursor.close()
            connection.close()
            return []

        try:
            ref_data = json.loads(ref_result[1])
            ref_intensities = np.array(ref_data.get("intensities", []), dtype=np.float32)
            if len(ref_intensities) == 0:
                logger.warning("⚠️ Espectro de referencia vacío")
                return []
        except Exception as e:
            logger.warning(f"⚠️ Error parseando espectro: {e}")
            return []

        ref_intensities_norm = normalize_spectrum(ref_intensities)
        ref_wavenumbers = np.arange(len(ref_intensities))
        ref_peaks = detect_peaks_vectorized(ref_wavenumbers, ref_intensities_norm)

        logger.debug(f"Picos detectados: {len(ref_peaks)}")

        # ✅ Cargar TODOS los espectros de una sola vez
        cursor.execute("""
            SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment, fs.measurement_date
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            WHERE fs.id != %s
            LIMIT 5000
        """, (spectrum_id,))

        all_spectra = cursor.fetchall()
        cursor.close()
        connection.close()

        if not all_spectra:
            logger.warning("⚠️ No hay espectros en el dataset para comparar")
            return []

        logger.info(f"📊 Procesando {len(all_spectra)} espectros del dataset")

        similarities = []

        # ✅ Dividir en lotes y procesar en paralelo
        batch_size = 250
        batches = [all_spectra[i:i+batch_size] for i in range(0, len(all_spectra), batch_size)]

        def process_batch(batch):
            batch_results = []
            try:
                intensities_list = []
                spec_info = []

                for spec_tuple in batch:
                    try:
                        spec_data = json.loads(spec_tuple[1])
                        intensities = np.array(spec_data.get("intensities", []), dtype=np.float32)
                        if len(intensities) > 0:
                            intensities_list.append(intensities)
                            spec_info.append(spec_tuple)
                    except:
                        continue

                if not intensities_list:
                    return batch_results

                # Normalizar lote
                max_len = max(len(i) for i in intensities_list)
                intensities_array = np.array([np.pad(i, (0, max_len - len(i)), 'constant')
                                              for i in intensities_list])
                normalized_batch = normalize_spectra_batch(intensities_array)

                # Calcular similitudes
                similarities_batch = calculate_similarities_vectorized(
                    ref_intensities_norm,
                    [norm_batch for norm_batch in normalized_batch],
                    method
                )

                # Procesar resultados
                for idx, (similarity, spec_info_tuple) in enumerate(zip(similarities_batch, spec_info)):
                    if similarity >= min_similarity:
                        spec_intensities_norm = normalized_batch[idx]
                        spec_wavenumbers = np.arange(len(spec_intensities_norm))
                        spec_peaks = detect_peaks_vectorized(spec_wavenumbers, spec_intensities_norm)
                        peak_match = match_peaks_vectorized(ref_peaks, spec_peaks, tolerance)

                        batch_results.append({
                            "spectrum_id": spec_info_tuple[0],
                            "sample_code": spec_info_tuple[2],
                            "zeolite_name": spec_info_tuple[3],
                            "equipment": spec_info_tuple[4],
                            "measurement_date": str(spec_info_tuple[5]) if spec_info_tuple[5] else "N/A",
                            "similarity": float(similarity),
                            "matching_peaks": peak_match["matched_count"],
                            "total_peaks": peak_match["total"]
                        })
            except Exception as e:
                logger.debug(f"Error procesando lote: {e}")

            return batch_results

        # Ejecutar en paralelo
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_batch, batch) for batch in batches]
            for future in as_completed(futures):
                batch_results = future.result()
                similarities.extend(batch_results)

        similarities.sort(key=lambda x: x["similarity"], reverse=True)

        elapsed = time.time() - start_time
        logger.info(f"⚡ Dataset procesado en {elapsed:.2f}s - {len(similarities)} resultados")

        return similarities[:top_n]

    except Exception as e:
        logger.error(f"❌ Error búsqueda dataset: {e}")
        return []

# ========================================
# ENDPOINTS
# ========================================

@router.post("/search")
def search_similarity(
    request: SimilaritySearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """⚡ Búsqueda ultra-rápida"""

    start_time = time.time()

    try:
        logger.info(f"🔍 Búsqueda - Usuario: {current_user.id}")

        # Obtener espectros del usuario
        query_spectrum = db.query(Spectrum).filter(
            Spectrum.id == request.query_spectrum_id,
            Spectrum.user_id == current_user.id
        ).first()

        if not query_spectrum:
            raise HTTPException(status_code=404, detail="Espectro no encontrado en tu perfil")

        spectra_to_search = db.query(Spectrum).filter(
            Spectrum.id != request.query_spectrum_id,
            Spectrum.user_id == current_user.id
        ).all()

        config = request.config
        method = config.method or "pearson"
        tolerance = config.tolerance or 4
        range_min = config.range_min or 400
        range_max = config.range_max or 4000
        top_n = config.top_n or 10
        family_filter = config.family_filter

        results = []

        # ✅ Búsqueda en usuario
        if len(spectra_to_search) > 0:
            logger.info(f"⚡ Buscando en {len(spectra_to_search)} espectros del usuario...")

            user_results = []

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

                    if similarity_score:
                        user_results.append({
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
                    logger.debug(f"Error comparando espectro {spectrum.id}: {e}")

            results.extend(user_results)
            logger.info(f"✅ {len(user_results)} resultados del usuario")

        # ✅ Búsqueda en dataset
        logger.info(f"⚡ Iniciando búsqueda en dataset...")

        dataset_results = search_similar_in_dataset_ultra_fast(
            request.query_spectrum_id,
            method=method.lower() if method in ["euclidean", "cosine", "pearson"] else "pearson",
            top_n=top_n,
            min_similarity=0.5,
            tolerance=tolerance,
            max_workers=12
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

        results.sort(key=lambda x: x["global_score"], reverse=True)
        results = results[:top_n]

        for i, result in enumerate(results, 1):
            result["rank"] = i

        execution_time_ms = int((time.time() - start_time) * 1000)

        logger.info(f"⚡ Búsqueda completada en {execution_time_ms}ms")

        return {
            "success": True,
            "message": "Búsqueda completada",
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
                "execution_time_ms": execution_time_ms,
                "searched_at": datetime.now().isoformat()
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error en búsqueda: {str(e)}")


@router.post("/compare")
def compare_spectra(
    query_id: int = Query(...),
    reference_id: int = Query(...),
    method: str = Query("pearson"),
    tolerance: float = Query(4),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Comparar dos espectros"""

    try:
        # Buscar en BD del usuario primero
        query_spectrum = db.query(Spectrum).filter(
            Spectrum.id == query_id,
            Spectrum.user_id == current_user.id
        ).first()

        reference_spectrum = db.query(Spectrum).filter(
            Spectrum.id == reference_id,
            Spectrum.user_id == current_user.id
        ).first()

        if query_spectrum and reference_spectrum:
            similarity_score = calculator.calculate_similarity(
                spectrum1=query_spectrum,
                spectrum2=reference_spectrum,
                method=method,
                tolerance=tolerance
            )

            return {
                "success": True,
                "message": "Comparación completada",
                "data": {
                    "query": {"id": query_spectrum.id, "filename": query_spectrum.filename},
                    "reference": {"id": reference_spectrum.id, "filename": reference_spectrum.filename},
                    "method": method,
                    "global_score": similarity_score.get("global_score", 0) if similarity_score else 0
                }
            }

        raise HTTPException(status_code=404, detail="Espectros no encontrados")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error comparación: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# ✅ GET SPECTRUM PARA COMPARACIÓN
# Busca en AMBAS bases de datos
# ========================================

# ========================================
# ✅ NUEVO ENDPOINT - GET SPECTRUM PARA COMPARACIÓN
# ========================================

@router.get("/spectrum-for-comparison/{spectrum_id}")
def get_spectrum_for_comparison(spectrum_id: int):
    """Obtener espectro para comparación (busca en dataset + usuario DB)"""
    logger.info(f"🔍 GET /spectrum-for-comparison/{spectrum_id}")

    try:
        # ========================================
        # INTENTAR DATASET PRIMERO
        # ========================================
        connection = connect_dataset_db()
        if connection:
            cursor = connection.cursor()
            cursor.execute("""
                SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment, fs.measurement_date
                FROM ftir_spectra fs
                JOIN zeolite_samples zs ON fs.sample_id = zs.id
                JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
                WHERE fs.id = %s
            """, (spectrum_id,))

            result = cursor.fetchone()
            cursor.close()
            connection.close()

            if result:
                logger.info(f"✅ Espectro encontrado en DATASET: {result[2]}")
                try:
                    spectrum_data = json.loads(result[1])
                    wavenumbers = spectrum_data.get("wavenumbers", [])
                    intensities = spectrum_data.get("intensities", spectrum_data.get("absorbance", []))
                except:
                    wavenumbers = []
                    intensities = []

                return {
                    "success": True,
                    "source": "dataset",
                    "spectrum": {
                        "id": result[0],
                        "filename": result[2],
                        "family": result[3],
                        "equipment": result[4],
                        "spectrum_data": {
                            "wavenumbers": wavenumbers,
                            "intensities": intensities
                        },
                        "source": "zeolite_dataset"
                    }
                }

        # ========================================
        # FALLBACK: Buscar en usuario DB
        # ========================================
        logger.info(f"⚠️ No en dataset, buscando en usuario DB...")

        db = SessionLocal()
        try:
            spectrum = db.query(Spectrum).filter(Spectrum.id == spectrum_id).first()

            if spectrum:
                logger.info(f"✅ Espectro encontrado en USER DB: {spectrum.filename}")

                # Parsear wavenumber_data
                wavenumbers = []
                intensities = []

                if spectrum.wavenumber_data:
                    try:
                        data = json.loads(spectrum.wavenumber_data)
                        wavenumbers = data.get("wavenumbers", [])
                        intensities = data.get("intensities", data.get("absorbance", []))
                    except:
                        pass

                return {
                    "success": True,
                    "source": "user",
                    "spectrum": {
                        "id": spectrum.id,
                        "filename": spectrum.filename,
                        "family": spectrum.material or "N/A",
                        "equipment": spectrum.technique or "N/A",
                        "spectrum_data": {
                            "wavenumbers": wavenumbers,
                            "intensities": intensities
                        },
                        "source": "user_database"
                    }
                }
        finally:
            db.close()

        # ========================================
        # NO ENCONTRADO
        # ========================================
        logger.warning(f"❌ Espectro {spectrum_id} no encontrado en ninguna BD")
        raise HTTPException(status_code=404, detail=f"Espectro no encontrado")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

# ========================================
# GET DATASET SPECTRA
# ========================================

@router.get("/dataset/spectra")
def get_dataset_spectra(
        limit: int = Query(5000, ge=1, le=5000),
        skip: int = Query(0, ge=0),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    """
    ✅ Obtener todos los espectros del dataset
    Útil para ver la biblioteca completa
    """
    try:
        connection = connect_dataset_db()
        if not connection:
            raise HTTPException(status_code=500, detail="No se pudo conectar al dataset")

        cursor = connection.cursor()

        # Contar total
        cursor.execute("SELECT COUNT(*) FROM ftir_spectra")
        total = cursor.fetchone()[0]

        # Obtener espectros
        cursor.execute("""
            SELECT fs.id, zs.sample_code, zt.name, fs.equipment, fs.measurement_date, fs.spectrum_data
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            ORDER BY fs.id DESC
            LIMIT %s OFFSET %s
        """, (limit, skip))

        results = cursor.fetchall()
        cursor.close()
        connection.close()

        spectra = []
        for result in results:
            try:
                spectrum_data = json.loads(result[5])
            except:
                spectrum_data = {}

            spectra.append({
                "id": result[0],
                "sample_code": result[1],
                "zeolite_name": result[2],
                "equipment": result[3],
                "measurement_date": str(result[4]) if result[4] else None,
                "filename": f"{result[1]} ({result[2]})",
                "spectrum_data": spectrum_data
            })

        return {
            "success": True,
            "data": spectra,
            "total": total,
            "pagination": {
                "skip": skip,
                "limit": limit,
                "total": total
            }
        }

    except Exception as e:
        logger.error(f"Error obteniendo dataset: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# GET SPECTRUM INFO
# ========================================

@router.get("/spectrum/{spectrum_id}")
def get_spectrum_info(spectrum_id: int):
    """
    ✅ Obtener espectro del dataset
    Maneja correctamente cuando no existe
    """
    try:
        # Primero verificar si existe
        connection = connect_dataset_db()
        if not connection:
            raise HTTPException(status_code=500, detail="No se pudo conectar a la base de datos")

        cursor = connection.cursor()

        cursor.execute("""
            SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment, fs.measurement_date
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            WHERE fs.id = %s
            LIMIT 1
        """, (spectrum_id,))

        result = cursor.fetchone()
        cursor.close()
        connection.close()

        if not result:
            logger.warning(f"⚠️ Espectro {spectrum_id} no encontrado en dataset")
            raise HTTPException(status_code=404, detail=f"Espectro {spectrum_id} no existe en el dataset")

        try:
            spectrum_data = json.loads(result[1])
        except:
            spectrum_data = {"error": "No se pudo procesar los datos"}

        return {
            "success": True,
            "spectrum": {
                "id": result[0],
                "spectrum_data": spectrum_data,
                "sample_code": result[2],
                "zeolite_name": result[3],
                "equipment": result[4],
                "measurement_date": str(result[5]) if result[5] else "N/A"
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error obteniendo espectro: {e}")
        raise HTTPException(status_code=500, detail=str(e))