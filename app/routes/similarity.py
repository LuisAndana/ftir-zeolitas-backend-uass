"""
⚡ BÚSQUEDA DE SIMILITUD ULTRA-OPTIMIZADA
✅ FIXES v2:
- detect_peaks_vectorized ahora usa wavenumbers REALES (no índices)
- match_peaks_vectorized usa tolerancia en cm⁻¹ correctamente
- search_similar_in_dataset_ultra_fast pasa wavenumbers reales a detect_peaks
- Mejor manejo de conexiones MySQL con try-finally
"""

import logging
import json
import time
import threading
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import numpy as np
from scipy.spatial.distance import euclidean, cosine
from scipy.stats import pearsonr
from scipy.interpolate import interp1d
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Dict, List, Tuple, Optional

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
# GRID FIJO PARA INTERPOLACIÓN
# ========================================

# Grid fijo: 400-4000 cm⁻¹ con paso de 2 cm⁻¹ → 1801 puntos
FIXED_GRID = np.linspace(400, 4000, 1801, dtype=np.float32)

# ========================================
# CACHE MATRICIAL DEL DATASET (PRELOADED)
# Carga todo el dataset en RAM como matriz numpy normalizada.
# Búsqueda = una sola operación matricial → prácticamente instantánea.
# ========================================

class DatasetMatrixCache:
    """
    Cache vectorial del dataset completo.
    - Al cargar: interpola todos los espectros al FIXED_GRID, normaliza, precomputa norms/means/stds/picos.
    - Al buscar: interpola el query al mismo grid → dot product matricial O(N*L) con numpy → <10ms.
    """

    def __init__(self):
        self.matrix: Optional[np.ndarray] = None    # (N, L) float32, normalizado 0-1
        self.norms: Optional[np.ndarray] = None      # (N,) para cosine
        self.means: Optional[np.ndarray] = None      # (N,) para pearson
        self.stds: Optional[np.ndarray] = None       # (N,) para pearson
        self.metadata: List[Dict] = []               # id, sample_code, zeolite_name, equipment, date
        self.peaks: List[List[float]] = []           # picos pre-calculados por espectro
        self.loaded: bool = False
        self.loading: bool = False
        self.lock = Lock()
        self.load_time: Optional[datetime] = None
        self.total_loaded: int = 0

    def _interpolate_to_grid(self, wavenumbers: np.ndarray, intensities: np.ndarray) -> Optional[np.ndarray]:
        """Interpola un espectro al FIXED_GRID. Retorna None si no hay solapamiento suficiente."""
        if len(wavenumbers) < 2 or len(intensities) < 2:
            return None
        try:
            sort_idx = np.argsort(wavenumbers)
            wn_s = wavenumbers[sort_idx]
            ab_s = intensities[sort_idx]

            wn_min, wn_max = float(wn_s[0]), float(wn_s[-1])
            grid_mask = (FIXED_GRID >= wn_min) & (FIXED_GRID <= wn_max)
            if np.sum(grid_mask) < 50:
                return None

            f = interp1d(wn_s, ab_s, kind='linear', bounds_error=False, fill_value=0.0)
            out = np.zeros(len(FIXED_GRID), dtype=np.float32)
            out[grid_mask] = f(FIXED_GRID[grid_mask]).astype(np.float32)
            return out
        except Exception:
            return None

    def load(self) -> bool:
        """Carga todo el dataset en RAM. Thread-safe; evita cargas concurrentes."""
        with self.lock:
            if self.loaded or self.loading:
                return self.loaded
            self.loading = True

        t0 = time.time()
        connection = None
        cursor = None
        try:
            connection = connect_dataset_db()
            if not connection:
                logger.warning("DatasetMatrixCache: no hay conexión al dataset")
                return False

            cursor = connection.cursor()
            cursor.execute("""
                SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment, fs.measurement_date
                FROM ftir_spectra fs
                JOIN zeolite_samples zs ON fs.sample_id = zs.id
                JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            """)
            rows = cursor.fetchall()

            if not rows:
                logger.warning("DatasetMatrixCache: dataset vacío")
                return False

            logger.info(f"DatasetMatrixCache: procesando {len(rows)} espectros...")

            matrix_rows, metadata, peaks_list = [], [], []

            for row in rows:
                try:
                    spec_data = json.loads(row[1]) if row[1] else {}
                    wn = np.array(spec_data.get("wavenumbers") or [], dtype=np.float32)
                    ab = np.array(
                        spec_data.get("intensities") or spec_data.get("absorbance") or [],
                        dtype=np.float32
                    )
                    if len(wn) < 2 or len(ab) < 2:
                        continue

                    interp_vec = self._interpolate_to_grid(wn, ab)
                    if interp_vec is None:
                        continue

                    mn, mx = np.min(interp_vec), np.max(interp_vec)
                    if mx - mn < 1e-10:
                        continue
                    norm_vec = (interp_vec - mn) / (mx - mn)

                    pks = detect_peaks_vectorized(FIXED_GRID, norm_vec, threshold=0.05)

                    matrix_rows.append(norm_vec)
                    metadata.append({
                        "spectrum_id": int(row[0]),
                        "sample_code": row[2],
                        "zeolite_name": row[3],
                        "equipment": row[4],
                        "measurement_date": str(row[5]) if row[5] else "N/A",
                    })
                    peaks_list.append(pks)
                except Exception as e:
                    logger.debug(f"DatasetMatrixCache: skip espectro {row[0]}: {e}")
                    continue

            if not matrix_rows:
                logger.warning("DatasetMatrixCache: ningún espectro válido")
                return False

            mat = np.array(matrix_rows, dtype=np.float32)         # (N, L)

            with self.lock:
                self.matrix = mat
                self.norms = np.linalg.norm(mat, axis=1)           # (N,)
                self.means = np.mean(mat, axis=1)                   # (N,)
                self.stds = np.std(mat, axis=1)                    # (N,)
                self.metadata = metadata
                self.peaks = peaks_list
                self.total_loaded = len(matrix_rows)
                self.load_time = datetime.now()
                self.loaded = True
                self.loading = False

            elapsed = time.time() - t0
            logger.info(
                f"DatasetMatrixCache: {self.total_loaded} espectros cargados en {elapsed:.2f}s "
                f"({mat.nbytes / 1024 / 1024:.1f} MB RAM)"
            )
            return True

        except Exception as e:
            logger.error(f"DatasetMatrixCache: error al cargar: {e}", exc_info=True)
            with self.lock:
                self.loading = False
            return False
        finally:
            if cursor:
                try: cursor.close()
                except: pass
            if connection and connection.is_connected():
                try: connection.close()
                except: pass

    def search(
        self,
        query_wn: np.ndarray,
        query_ab: np.ndarray,
        method: str = "pearson",
        min_similarity: float = 0.5,
        top_n: int = 10,
        tolerance: float = 4.0,
        family_filter: Optional[str] = None,
    ) -> List[Dict]:
        """
        Búsqueda vectorizada instantánea.
        1. Interpola el query al FIXED_GRID.
        2. Una sola operación matricial para todas las similitudes.
        3. Filtra + ordena + retorna top_n.
        """
        if not self.loaded or self.matrix is None:
            return []

        interp = self._interpolate_to_grid(query_wn, query_ab)
        if interp is None:
            return []
        mn, mx = np.min(interp), np.max(interp)
        if mx - mn < 1e-10:
            return []
        query_norm = (interp - mn) / (mx - mn)

        query_peaks = detect_peaks_vectorized(FIXED_GRID, query_norm, threshold=0.05)

        L = len(FIXED_GRID)

        if method == "cosine":
            q_norm_val = float(np.linalg.norm(query_norm))
            if q_norm_val < 1e-10:
                return []
            sims = (self.matrix @ query_norm) / (self.norms * q_norm_val + 1e-10)
            sims = np.clip((sims + 1.0) / 2.0, 0.0, 1.0)

        elif method == "pearson":
            q_centered = query_norm - float(np.mean(query_norm))
            q_std = float(np.std(query_norm))
            if q_std < 1e-10:
                return []
            mat_centered = self.matrix - self.means[:, np.newaxis]
            cov = (mat_centered @ q_centered) / L
            sims = np.clip((cov / (self.stds * q_std + 1e-10) + 1.0) / 2.0, 0.0, 1.0)

        elif method == "euclidean":
            diffs = self.matrix - query_norm
            distances = np.linalg.norm(diffs, axis=1) / (np.sqrt(L) + 1e-10)
            sims = 1.0 / (1.0 + distances)

        else:
            return []

        mask = sims >= min_similarity
        if family_filter:
            family_mask = np.array([m["zeolite_name"] == family_filter for m in self.metadata])
            mask = mask & family_mask

        valid_idx = np.where(mask)[0]
        if len(valid_idx) == 0:
            return []

        sorted_idx = valid_idx[np.argsort(sims[valid_idx])[::-1]][:top_n]

        results = []
        for idx in sorted_idx:
            peak_match = match_peaks_vectorized(query_peaks, self.peaks[idx], tolerance)
            results.append({
                **self.metadata[idx],
                "similarity": float(sims[idx]),
                "matching_peaks": peak_match["matched_count"],
                "total_peaks": peak_match["total"],
            })
        return results

    def reload(self):
        """Fuerza recarga del cache (en background thread)."""
        with self.lock:
            self.loaded = False
            self.loading = False
            self.matrix = None
        threading.Thread(target=self.load, daemon=True, name="dataset-cache-reload").start()


dataset_matrix_cache = DatasetMatrixCache()

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
    """
    ✅ Conectar a la base de datos del dataset
    """
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
        logger.debug(f"✅ Conexión exitosa a dataset: {config['host']}/{config['database']}")
        return connection
    except Error as e:
        logger.error(f"❌ Error en conexión dataset: {type(e).__name__}: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"❌ Error inesperado en conexión dataset: {type(e).__name__}: {str(e)}")
        return None

# ========================================
# FUNCIONES VECTORIZADAS
# ========================================

def normalize_spectrum(intensities: np.ndarray) -> np.ndarray:
    """Normalizar espectro 0-1"""
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
        logger.warning(f"⚠️ Error cálculo vectorizado: {e}")
        return np.array([0.0] * len(test_spectra))


# ========================================
# ✅ FIX CRÍTICO: detect_peaks_vectorized
# Antes usaba np.arange(len(absorbance)) como wavenumbers → INCORRECTO
# Ahora recibe wavenumbers REALES y los usa para reportar picos en cm⁻¹
# ========================================

def detect_peaks_vectorized(
    wavenumbers: np.ndarray,
    absorbance: np.ndarray,
    threshold: float = 0.05,
    min_distance_cm: float = 10.0
) -> List[float]:
    """
    ✅ FIX: Detectar picos usando wavenumbers REALES (cm⁻¹).

    Args:
        wavenumbers: Array de números de onda reales en cm⁻¹ (ej. 400-4000)
        absorbance:  Array de absorbancia correspondiente
        threshold:   Altura mínima normalizada (0-1) para considerar un pico
        min_distance_cm: Distancia mínima entre picos en cm⁻¹

    Returns:
        Lista de posiciones de pico en cm⁻¹ reales
    """
    wn = np.array(wavenumbers, dtype=np.float32)
    ab = np.array(absorbance, dtype=np.float32)

    if len(wn) < 3 or len(ab) < 3:
        return []

    n = min(len(wn), len(ab))
    wn = wn[:n]
    ab = ab[:n]

    try:
        # Normalizar absorbancia 0-1
        min_ab = np.min(ab)
        max_ab = np.max(ab)
        if max_ab == min_ab:
            return []

        norm_ab = (ab - min_ab) / (max_ab - min_ab)

        # Suavizado con ventana de 5 puntos para reducir ruido
        kernel = np.ones(5) / 5
        smoothed = np.convolve(norm_ab, kernel, mode='same')

        # Detectar máximos locales
        is_greater_left  = smoothed[1:-1] > smoothed[:-2]
        is_greater_right = smoothed[1:-1] > smoothed[2:]
        above_threshold  = smoothed[1:-1] > threshold
        is_peak = is_greater_left & is_greater_right & above_threshold

        peak_indices = np.where(is_peak)[0] + 1  # +1 por el offset del slice

        if len(peak_indices) == 0:
            return []

        # ✅ Usar wavenumbers REALES para las posiciones de los picos
        peak_wavenumbers_cm = wn[peak_indices].tolist()
        peak_heights = smoothed[peak_indices].tolist()

        # Ordenar por altura descendente para filtrar por distancia mínima
        sorted_peaks = sorted(
            zip(peak_wavenumbers_cm, peak_heights),
            key=lambda x: x[1],
            reverse=True
        )

        # Filtrar picos demasiado cercanos (mantener el más alto)
        filtered: List[float] = []
        for wn_val, _ in sorted_peaks:
            if all(abs(wn_val - existing) >= min_distance_cm for existing in filtered):
                filtered.append(wn_val)

        # Retornar ordenados por wavenumber ascendente
        filtered.sort()

        logger.debug(f"🔍 detect_peaks: {len(filtered)} picos encontrados en cm⁻¹: {filtered[:5]}...")
        return filtered

    except Exception as e:
        logger.debug(f"⚠️ Error detect_peaks: {e}")
        return []


def match_peaks_vectorized(
    peaks1: List[float],
    peaks2: List[float],
    tolerance: float = 4.0
) -> Dict:
    """
    ✅ Emparejar picos en cm⁻¹ con tolerancia en cm⁻¹.

    Args:
        peaks1:    Picos del espectro de consulta (cm⁻¹)
        peaks2:    Picos del espectro de referencia (cm⁻¹)
        tolerance: Tolerancia máxima para considerar picos coincidentes (cm⁻¹)

    Returns:
        Dict con matched, unmatched, total, matched_count
    """
    if not peaks1 or not peaks2:
        return {
            "matched": [],
            "unmatched": peaks1 or [],
            "total": len(peaks1) if peaks1 else 0,
            "matched_count": 0
        }

    peaks1_arr = np.array(peaks1, dtype=np.float32)
    peaks2_arr = np.array(peaks2, dtype=np.float32)

    # Matriz de distancias |peaks1[i] - peaks2[j]|
    distances = np.abs(peaks1_arr[:, np.newaxis] - peaks2_arr[np.newaxis, :])

    # Un pico de peaks1 es "matched" si existe algún pico en peaks2 a ≤ tolerance cm⁻¹
    matched_mask = np.any(distances <= tolerance, axis=1)
    matched_count = int(np.sum(matched_mask))

    return {
        "matched": peaks1_arr[matched_mask].tolist(),
        "unmatched": peaks1_arr[~matched_mask].tolist(),
        "total": len(peaks1),
        "matched_count": matched_count
    }


# ========================================
# ✅ FIX: BÚSQUEDA EN DATASET CON WAVENUMBERS REALES
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
    ✅ FIX: Usa wavenumbers reales para detección de picos
    """
    start_time = time.time()
    connection = None
    cursor = None

    try:
        connection = connect_dataset_db()
        if not connection:
            logger.warning("⚠️ No hay conexión al dataset")
            return []

        cursor = connection.cursor()

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
            return []

        try:
            ref_data = json.loads(ref_result[1]) if ref_result[1] else {}
            ref_intensities = np.array(
                ref_data.get("intensities") or ref_data.get("absorbance") or [],
                dtype=np.float32
            )
            # ✅ FIX: Cargar wavenumbers reales del espectro de referencia
            ref_wavenumbers = np.array(
                ref_data.get("wavenumbers") or list(range(len(ref_intensities))),
                dtype=np.float32
            )

            if len(ref_intensities) == 0:
                logger.warning("⚠️ Espectro de referencia vacío")
                return []
        except Exception as e:
            logger.error(f"❌ Error parseando espectro de referencia: {e}")
            return []

        ref_intensities_norm = normalize_spectrum(ref_intensities)

        # ✅ FIX: Pasar wavenumbers REALES a detect_peaks
        ref_peaks = detect_peaks_vectorized(ref_wavenumbers, ref_intensities_norm, threshold=0.05)
        logger.debug(f"📊 Picos detectados en referencia: {len(ref_peaks)} (en cm⁻¹)")

        cursor.execute("""
            SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment, fs.measurement_date
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            WHERE fs.id != %s
            LIMIT 5000
        """, (spectrum_id,))

        all_spectra = cursor.fetchall()

        if not all_spectra:
            logger.warning("⚠️ No hay espectros en el dataset para comparar")
            return []

        logger.info(f"📊 Procesando {len(all_spectra)} espectros del dataset")

        similarities = []
        batch_size = 250
        batches = [all_spectra[i:i+batch_size] for i in range(0, len(all_spectra), batch_size)]

        def process_batch(batch):
            batch_results = []
            try:
                intensities_list = []
                wavenumbers_list = []
                spec_info = []

                for spec_tuple in batch:
                    try:
                        spec_data = json.loads(spec_tuple[1]) if spec_tuple[1] else {}
                        intensities = np.array(
                            spec_data.get("intensities") or spec_data.get("absorbance") or [],
                            dtype=np.float32
                        )
                        # ✅ FIX: Cargar wavenumbers reales de cada espectro
                        wavenumbers = np.array(
                            spec_data.get("wavenumbers") or list(range(len(intensities))),
                            dtype=np.float32
                        )
                        if len(intensities) > 0:
                            intensities_list.append(intensities)
                            wavenumbers_list.append(wavenumbers)
                            spec_info.append(spec_tuple)
                    except Exception as e:
                        logger.debug(f"⚠️ Error procesando espectro {spec_tuple[0]}: {e}")
                        continue

                if not intensities_list:
                    return batch_results

                max_len = max(len(i) for i in intensities_list)
                intensities_array = np.array([
                    np.pad(i, (0, max_len - len(i)), 'constant')
                    for i in intensities_list
                ])
                normalized_batch = normalize_spectra_batch(intensities_array)

                similarities_batch = calculate_similarities_vectorized(
                    ref_intensities_norm,
                    [nb for nb in normalized_batch],
                    method
                )

                for idx, (similarity, spec_info_tuple) in enumerate(zip(similarities_batch, spec_info)):
                    if similarity >= min_similarity:
                        spec_intensities_norm = normalized_batch[idx]
                        # ✅ FIX: Usar wavenumbers reales del espectro comparado
                        spec_wn = wavenumbers_list[idx]
                        spec_peaks = detect_peaks_vectorized(
                            spec_wn, spec_intensities_norm, threshold=0.05
                        )
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
                logger.error(f"❌ Error procesando lote: {e}")

            return batch_results

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_batch, batch) for batch in batches]
            for future in as_completed(futures):
                try:
                    batch_results = future.result()
                    similarities.extend(batch_results)
                except Exception as e:
                    logger.error(f"❌ Error en future: {e}")

        similarities.sort(key=lambda x: x["similarity"], reverse=True)
        elapsed = time.time() - start_time
        logger.info(f"⚡ Dataset procesado en {elapsed:.2f}s - {len(similarities)} resultados")
        return similarities[:top_n]

    except Exception as e:
        logger.error(f"❌ Error búsqueda dataset: {type(e).__name__}: {str(e)}", exc_info=True)
        return []
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception as e:
                logger.warning(f"⚠️ Error cerrando cursor: {e}")
        if connection and connection.is_connected():
            try:
                connection.close()
            except Exception as e:
                logger.warning(f"⚠️ Error cerrando conexión: {e}")


# ========================================
# ENDPOINTS
# ========================================

@router.post("/search")
def search_similarity(
    request: SimilaritySearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """⚡ Búsqueda ultra-rápida de similitud"""
    start_time = time.time()

    try:
        logger.info(f"🔍 Búsqueda iniciada - Usuario: {current_user.id}")

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
                    logger.debug(f"⚠️ Error comparando espectro {spectrum.id}: {e}")

            results.extend(user_results)

        logger.info(f"⚡ Iniciando búsqueda en dataset...")

        # Parsear el espectro query para la búsqueda en dataset
        try:
            q_raw = json.loads(query_spectrum.wavenumber_data) if query_spectrum.wavenumber_data else {}
            q_wn = np.array(q_raw.get("wavenumbers") or [], dtype=np.float32)
            q_ab = np.array(
                q_raw.get("absorbance") or q_raw.get("intensities") or [],
                dtype=np.float32
            )
            if len(q_wn) == 0 and len(q_ab) > 0:
                q_wn = np.linspace(400, 4000, len(q_ab), dtype=np.float32)
        except Exception:
            q_wn, q_ab = np.array([]), np.array([])

        safe_method = method.lower() if method in ["euclidean", "cosine", "pearson"] else "pearson"

        if dataset_matrix_cache.loaded and len(q_wn) > 0 and len(q_ab) > 0:
            logger.info("⚡ Usando cache matricial (búsqueda instantánea)")
            dataset_results = dataset_matrix_cache.search(
                q_wn, q_ab,
                method=safe_method,
                min_similarity=0.5,
                top_n=top_n,
                tolerance=tolerance,
                family_filter=family_filter,
            )
        else:
            logger.info("⚠️ Cache no cargado, usando búsqueda tradicional")
            dataset_results = search_similar_in_dataset_ultra_fast(
                request.query_spectrum_id,
                method=safe_method,
                top_n=top_n,
                min_similarity=0.5,
                tolerance=tolerance,
                max_workers=12,
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
        logger.info(f"✅ Búsqueda completada en {execution_time_ms}ms")

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
        logger.error(f"❌ Error en búsqueda: {type(e).__name__}: {str(e)}", exc_info=True)
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
    logger.info(f"🔄 Comparación: Query={query_id}, Reference={reference_id}")

    try:
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

        # ✅ FIX: Calcular picos con wavenumbers reales antes de enviar al calculator
        try:
            q_data = json.loads(query_spectrum.wavenumber_data) if query_spectrum.wavenumber_data else {}
            r_data = json.loads(reference_spectrum.wavenumber_data) if reference_spectrum.wavenumber_data else {}

            q_wn   = np.array(q_data.get("wavenumbers") or [], dtype=np.float32)
            q_abs  = np.array(q_data.get("absorbance") or q_data.get("intensities") or [], dtype=np.float32)
            r_wn   = np.array(r_data.get("wavenumbers") or [], dtype=np.float32)
            r_abs  = np.array(r_data.get("absorbance") or r_data.get("intensities") or [], dtype=np.float32)

            # Fallback: si no hay wavenumbers guardados, generar un rango aproximado
            if len(q_wn) == 0 and len(q_abs) > 0:
                q_wn = np.linspace(400, 4000, len(q_abs))
            if len(r_wn) == 0 and len(r_abs) > 0:
                r_wn = np.linspace(400, 4000, len(r_abs))

            q_norm = normalize_spectrum(q_abs) if len(q_abs) > 0 else np.array([])
            r_norm = normalize_spectrum(r_abs) if len(r_abs) > 0 else np.array([])

            q_peaks = detect_peaks_vectorized(q_wn, q_norm, threshold=0.05) if len(q_wn) > 0 else []
            r_peaks = detect_peaks_vectorized(r_wn, r_norm, threshold=0.05) if len(r_wn) > 0 else []

            peak_match = match_peaks_vectorized(q_peaks, r_peaks, tolerance)

        except Exception as e:
            logger.warning(f"⚠️ Error calculando picos locales: {e}")
            q_peaks, r_peaks = [], []
            peak_match = {"matched": [], "unmatched": [], "total": 0, "matched_count": 0}

        similarity_score = calculator.calculate_similarity(
            spectrum1=query_spectrum,
            spectrum2=reference_spectrum,
            method=method,
            tolerance=tolerance
        )

        if not similarity_score:
            raise HTTPException(status_code=500, detail="Error calculando similitud")

        # ✅ Enriquecer con picos calculados correctamente si el calculator no los tiene
        matched_peaks = similarity_score.get("matched_peaks") or peak_match["matched"]
        unmatched_peaks = similarity_score.get("unmatched_peaks") or peak_match["unmatched"]
        total_peaks = similarity_score.get("total_peaks") or peak_match["total"]
        matching_peaks_count = similarity_score.get("matching_peaks_count") or peak_match["matched_count"]

        logger.info(f"✅ Comparación completada: Score={similarity_score.get('global_score', 0):.3f}, "
                    f"Picos={matching_peaks_count}/{total_peaks}")

        return {
            "success": True,
            "message": "Comparación completada",
            "data": {
                "global_score": similarity_score.get("global_score", 0),
                "all_scores": similarity_score.get("all_scores", {
                    "pearson": 0, "cosine": 0, "euclidean": 0
                }),
                "method_used": method,
                # ✅ Picos en cm⁻¹ reales
                "matched_peaks": matched_peaks,
                "unmatched_peaks": unmatched_peaks,
                "total_peaks": total_peaks,
                "matching_peaks_count": matching_peaks_count,
                "query_spectrum": {
                    "id": query_spectrum.id,
                    "filename": query_spectrum.filename,
                    "source": "user_database"
                },
                "reference_spectrum": {
                    "id": reference_spectrum.id,
                    "filename": reference_spectrum.filename,
                    "source": "user_database"
                },
                "window_scores": similarity_score.get("window_scores", [])
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error comparación: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========================================
# ENDPOINT UNIFICADO - GET SPECTRUM PARA COMPARACIÓN
# ========================================

@router.get("/spectrum-for-comparison/{spectrum_id}")
def get_spectrum_for_comparison(
    spectrum_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    ✅ Obtener espectro para comparación (busca en dataset + usuario DB)
    """
    logger.info(f"🔍 GET /spectrum-for-comparison/{spectrum_id} - Usuario: {current_user.id}")

    connection = None
    cursor = None

    try:
        connection = connect_dataset_db()
        if connection:
            try:
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

                if result:
                    wavenumbers = []
                    intensities = []
                    try:
                        spectrum_data = json.loads(result[1]) if result[1] else {}
                        wavenumbers = spectrum_data.get("wavenumbers") or []
                        intensities = (
                            spectrum_data.get("intensities")
                            or spectrum_data.get("absorbance")
                            or []
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Error parseando spectrum_data: {e}")

                    return {
                        "success": True,
                        "source": "dataset",
                        "spectrum": {
                            "id": result[0],
                            "filename": result[2],
                            "family": result[3],
                            "equipment": result[4] or "N/A",
                            "spectrum_data": {
                                "wavenumbers": wavenumbers,
                                "intensities": intensities
                            },
                            "source": "zeolite_dataset"
                        }
                    }

            except Exception as e:
                logger.error(f"❌ Error consultando dataset: {type(e).__name__}: {str(e)}")
            finally:
                if cursor:
                    try:
                        cursor.close()
                    except Exception as e:
                        logger.warning(f"⚠️ Error cerrando cursor: {e}")

        spectrum = db.query(Spectrum).filter(
            Spectrum.id == spectrum_id,
            Spectrum.user_id == current_user.id
        ).first()

        if spectrum:
            wavenumbers = []
            intensities = []
            if spectrum.wavenumber_data:
                try:
                    data = json.loads(spectrum.wavenumber_data)
                    wavenumbers = data.get("wavenumbers") or []
                    intensities = (
                        data.get("intensities")
                        or data.get("absorbance")
                        or []
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Error parseando wavenumber_data: {e}")

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

        raise HTTPException(status_code=404, detail=f"Espectro {spectrum_id} no encontrado")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        if connection and connection.is_connected():
            try:
                connection.close()
            except Exception as e:
                logger.warning(f"⚠️ Error cerrando conexión: {e}")


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
    """✅ Obtener todos los espectros del dataset"""
    connection = None
    cursor = None

    try:
        connection = connect_dataset_db()
        if not connection:
            raise HTTPException(status_code=500, detail="No se pudo conectar al dataset")

        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM ftir_spectra")
        total_result = cursor.fetchone()
        total = total_result[0] if total_result else 0

        cursor.execute("""
            SELECT fs.id, zs.sample_code, zt.name, fs.equipment, fs.measurement_date, fs.spectrum_data
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            ORDER BY fs.id DESC
            LIMIT %s OFFSET %s
        """, (limit, skip))

        results = cursor.fetchall()
        spectra = []

        for result in results:
            try:
                spectrum_data = json.loads(result[5]) if result[5] else {}
            except Exception as e:
                logger.warning(f"⚠️ Error parseando espectro {result[0]}: {e}")
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
            "pagination": {"skip": skip, "limit": limit, "total": total}
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error obteniendo dataset: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception: pass
        if connection and connection.is_connected():
            try:
                connection.close()
            except Exception: pass


# ========================================
# GET SPECTRUM INFO
# ========================================

@router.get("/spectrum/{spectrum_id}")
def get_spectrum_info(spectrum_id: int):
    """✅ Obtener espectro del dataset"""
    connection = None
    cursor = None

    try:
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

        if not result:
            raise HTTPException(status_code=404, detail=f"Espectro {spectrum_id} no existe en el dataset")

        try:
            spectrum_data = json.loads(result[1]) if result[1] else {}
        except Exception as e:
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
        logger.error(f"❌ Error obteniendo espectro: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception: pass
        if connection and connection.is_connected():
            try:
                connection.close()
            except Exception: pass


# ========================================
# ENDPOINTS DE CACHE MATRICIAL
# ========================================

@router.get("/cache/status")
def get_cache_status(current_user: User = Depends(get_current_user)):
    """Estado del cache matricial del dataset."""
    c = dataset_matrix_cache
    return {
        "loaded": c.loaded,
        "loading": c.loading,
        "total_spectra": c.total_loaded,
        "load_time": c.load_time.isoformat() if c.load_time else None,
        "matrix_shape": list(c.matrix.shape) if c.matrix is not None else None,
        "ram_mb": round(c.matrix.nbytes / 1024 / 1024, 2) if c.matrix is not None else 0,
    }


@router.post("/cache/reload")
def reload_cache(current_user: User = Depends(get_current_user)):
    """Fuerza la recarga del cache matricial en segundo plano."""
    dataset_matrix_cache.reload()
    return {"message": "Recarga del cache iniciada en segundo plano"}