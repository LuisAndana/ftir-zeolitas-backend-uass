"""
⚡ BÚSQUEDA DE SIMILITUD ULTRA-OPTIMIZADA
✅ FIXES v2:
- detect_peaks_vectorized ahora usa wavenumbers REALES (no índices)
- match_peaks_vectorized usa tolerancia en cm⁻¹ correctamente
- Mejor manejo de conexiones MySQL con try-finally
✅ P2: pipeline unificado — espectros de usuario y dataset comparten
  interpolate_and_preprocess + vectorized_similarity (mismo preprocesamiento y
  misma fórmula de score); se retiró la ruta de respaldo que comparaba espectros
  por índice de array sin usar los números de onda.
"""

import logging
import json
import os
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
import numpy as np
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Dict, List, Tuple, Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.spectrum import Spectrum
from app.models.user import User
from app.routes.admin import require_admin
from app.schemas.similarity import SimilaritySearchRequest
from app.services.similarity_calculator import SimilarityCalculator
from app.services.spectral_preprocessing import (
    interpolate_and_preprocess, weighted_matrix_similarity,
    compute_window_scores, structural_region_mask, ALGORITHM_VERSION,
)
from app.models.similarity_result import SimilarityResult as SimilarityResultModel
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

# Máscara de la región estructural (huella dactilar, 400-1300 cm⁻¹) sobre FIXED_GRID,
# usada para ponderar el score global (ver STRUCTURAL_WEIGHT en spectral_preprocessing).
STRUCT_MASK = structural_region_mask(FIXED_GRID)

# ========================================
# CACHE MATRICIAL DEL DATASET (PRELOADED)
# Carga todo el dataset en RAM como matriz numpy normalizada.
# Búsqueda = una sola operación matricial → prácticamente instantánea.
# ========================================

_CACHE_DIR = Path("./cache")
_CACHE_NPZ = _CACHE_DIR / "dataset_matrix.npz"
_CACHE_META = _CACHE_DIR / "dataset_meta.json"


class DatasetMatrixCache:
    """
    Cache vectorial del dataset completo con persistencia en disco.

    Estrategia de velocidad:
      - 1ª carga: BD → numpy matrix → guarda .npz en disco.
      - Reinicios siguientes: carga .npz desde disco (<1s, sin tocar la BD).
      - Búsqueda: una operación matricial numpy (<15ms para 9000 espectros).
      - Picos: solo para los top_n resultados finales, nunca para los N totales.
      - Pearson: usa mat_centered pre-computado (no recalcula en cada búsqueda).
    """

    def __init__(self):
        self.matrix: Optional[np.ndarray] = None       # (N, L) float32
        self.mat_centered: Optional[np.ndarray] = None # (N, L) centrado por fila (pearson)
        self.norms: Optional[np.ndarray] = None        # (N,)
        self.means: Optional[np.ndarray] = None        # (N,)
        self.stds: Optional[np.ndarray] = None         # (N,)
        self.metadata: List[Dict] = []
        self.loaded: bool = False
        self.loading: bool = False
        self.lock = Lock()
        self.load_time: Optional[datetime] = None
        self.total_loaded: int = 0

    # ------------------------------------------------------------------
    # Proceso de una fila (ejecutado en threads)
    # ------------------------------------------------------------------
    @staticmethod
    def _process_row(row) -> Optional[tuple]:
        try:
            spec_data = json.loads(row[1]) if row[1] else {}
            wn = spec_data.get("wavenumbers") or []
            ab = spec_data.get("intensities") or spec_data.get("absorbance") or []

            norm_vec = interpolate_and_preprocess(wn, ab, FIXED_GRID)
            if norm_vec is None:
                return None

            meta = {
                "spectrum_id": int(row[0]),
                "sample_code": row[2],
                "zeolite_name": row[3],
                "equipment": row[4],
                "measurement_date": str(row[5]) if row[5] else "N/A",
                # Código IZA del framework (p.ej. "LTA") — permite al frontend
                # enlazar cada resultado con GET /api/zeolites/{code}/structure
                # sin tener que adivinarlo a partir de zeolite_name (que no
                # siempre incluye el código, p.ej. "Mordenita", "Sodalita").
                "framework_code": row[6] if len(row) > 6 else None,
            }
            return (norm_vec, meta)
        except Exception as e:
            logger.debug(f"DatasetMatrixCache._process_row: error procesando fila {row[0] if row else '?'}: {e}")
            return None

    # ------------------------------------------------------------------
    # Persistencia en disco
    # ------------------------------------------------------------------
    def _save_to_disk(self, mat: np.ndarray, metadata: List[Dict]) -> None:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                str(_CACHE_NPZ),
                matrix=mat,
                norms=np.linalg.norm(mat, axis=1),
                means=np.mean(mat, axis=1),
                stds=np.std(mat, axis=1),
                mat_centered=(mat - np.mean(mat, axis=1, keepdims=True)),
            )
            with open(_CACHE_META, "w") as f:
                json.dump(metadata, f)
            logger.info(f"DatasetMatrixCache: guardado en disco ({_CACHE_NPZ})")
        except Exception as e:
            logger.warning(f"DatasetMatrixCache: no se pudo guardar en disco: {e}")

    def _load_from_disk(self) -> bool:
        try:
            if not _CACHE_NPZ.with_suffix(".npz").exists() and not Path(str(_CACHE_NPZ) + ".npz").exists():
                # np.savez_compressed agrega .npz automáticamente si no está
                npz_path = Path(str(_CACHE_NPZ) + ".npz") if not str(_CACHE_NPZ).endswith(".npz") else _CACHE_NPZ
                if not npz_path.exists():
                    return False
            else:
                npz_path = _CACHE_NPZ if _CACHE_NPZ.exists() else Path(str(_CACHE_NPZ) + ".npz")

            if not _CACHE_META.exists():
                return False

            t0 = time.time()
            data = np.load(str(npz_path))
            with open(_CACHE_META) as f:
                metadata = json.load(f)

            mat = data["matrix"]

            with self.lock:
                self.matrix = mat
                self.norms = data["norms"]
                self.means = data["means"]
                self.stds = data["stds"]
                self.mat_centered = data["mat_centered"]
                self.metadata = metadata
                self.total_loaded = len(metadata)
                self.load_time = datetime.now()
                self.loaded = True
                self.loading = False

            elapsed = time.time() - t0
            logger.info(
                f"DatasetMatrixCache: {self.total_loaded} espectros cargados desde disco "
                f"en {elapsed:.2f}s ({mat.nbytes / 1024 / 1024:.1f} MB RAM)"
            )
            return True
        except Exception as e:
            logger.warning(f"DatasetMatrixCache: no se pudo cargar desde disco: {e}")
            return False

    # ------------------------------------------------------------------
    # Carga principal
    # ------------------------------------------------------------------
    def load(self) -> bool:
        """
        1. Intenta cargar desde disco (rápido, <1s).
        2. Si no hay disco, carga desde BD en paralelo y guarda al disco.
        """
        with self.lock:
            if self.loaded or self.loading:
                return self.loaded
            self.loading = True

        # Intento rápido desde disco
        if self._load_from_disk():
            return True

        # Carga desde BD (costosa, una sola vez)
        t0 = time.time()
        connection = None
        cursor = None
        try:
            connection = connect_dataset_db()
            if not connection:
                logger.warning("DatasetMatrixCache: no hay conexión al dataset")
                with self.lock:
                    self.loading = False
                return False

            cursor = connection.cursor()
            cursor.execute("""
                SELECT fs.id, fs.spectrum_data, zs.sample_code, zt.name, fs.equipment, fs.measurement_date, zt.structure_type
                FROM ftir_spectra fs
                JOIN zeolite_samples zs ON fs.sample_id = zs.id
                JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            """)
            rows = cursor.fetchall()
            logger.info(f"DatasetMatrixCache: {len(rows)} filas de BD, procesando en paralelo...")

        except Exception as e:
            logger.error(f"DatasetMatrixCache: error leyendo BD: {e}", exc_info=True)
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

        if not rows:
            logger.warning("DatasetMatrixCache: dataset vacío")
            with self.lock:
                self.loading = False
            return False

        try:
            with ThreadPoolExecutor(max_workers=8) as executor:
                processed = list(executor.map(self._process_row, rows))

            valid = [r for r in processed if r is not None]
            if not valid:
                logger.warning("DatasetMatrixCache: ningún espectro válido")
                with self.lock:
                    self.loading = False
                return False

            mat = np.array([r[0] for r in valid], dtype=np.float32)
            metadata = [r[1] for r in valid]

            with self.lock:
                self.matrix = mat
                self.norms = np.linalg.norm(mat, axis=1)
                self.means = np.mean(mat, axis=1)
                self.stds = np.std(mat, axis=1)
                self.mat_centered = (mat - np.mean(mat, axis=1, keepdims=True)).astype(np.float32)
                self.metadata = metadata
                self.total_loaded = len(valid)
                self.load_time = datetime.now()
                self.loaded = True
                self.loading = False

            elapsed = time.time() - t0
            logger.info(
                f"DatasetMatrixCache: {self.total_loaded} espectros listos en {elapsed:.2f}s "
                f"({mat.nbytes / 1024 / 1024:.1f} MB RAM) — guardando en disco..."
            )
            # Guardar en background para no bloquear
            threading.Thread(
                target=self._save_to_disk, args=(mat, metadata), daemon=True, name="cache-save"
            ).start()
            return True

        except Exception as e:
            logger.error(f"DatasetMatrixCache: error procesando: {e}", exc_info=True)
            with self.lock:
                self.loading = False
            return False

    # ------------------------------------------------------------------
    # Búsqueda vectorizada
    # ------------------------------------------------------------------
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
        1. Interpola query al FIXED_GRID (np.interp) + preprocesamiento científico.
        2. Dos operaciones matriciales (región estructural + resto) → score global
           ponderado (STRUCTURAL_WEIGHT/1-STRUCTURAL_WEIGHT) para los N espectros.
        3. Calcula picos y el desglose por ventana Flanigen solo para los top_n
           candidatos finales, nunca para los N totales (caro de otro modo).
        """
        if not self.loaded or self.matrix is None:
            return []

        # Mismo preprocesamiento (interpolación a FIXED_GRID + máscara CO2 + arPLS +
        # Savitzky-Golay + SNV) que _process_row aplica al dataset de referencia, y
        # misma fórmula de similitud — para que query y matriz sean comparables.
        query_norm = interpolate_and_preprocess(query_wn, query_ab, FIXED_GRID)
        if query_norm is None:
            return []

        if method not in ("cosine", "pearson", "euclidean"):
            return []

        sims = weighted_matrix_similarity(query_norm, self.matrix, method, struct_mask=STRUCT_MASK)

        mask = sims >= min_similarity
        if family_filter:
            family_mask = np.array([m["zeolite_name"] == family_filter for m in self.metadata])
            mask = mask & family_mask

        valid_idx = np.where(mask)[0]
        if len(valid_idx) == 0:
            return []

        sorted_idx = valid_idx[np.argsort(sims[valid_idx])[::-1]][:top_n]

        query_peaks = detect_peaks_vectorized(FIXED_GRID, query_norm, threshold=0.05)
        results = []
        for idx in sorted_idx:
            spec_peaks = detect_peaks_vectorized(FIXED_GRID, self.matrix[idx], threshold=0.05)
            peak_match = match_peaks_vectorized(query_peaks, spec_peaks, tolerance)
            windowed = compute_window_scores(FIXED_GRID, query_norm, self.matrix[idx], method=method)
            results.append({
                **self.metadata[idx],
                "similarity": float(sims[idx]),
                "window_scores": windowed["window_scores"],
                "matching_peaks": peak_match["matched_count"],
                "total_peaks": peak_match["total"],
            })
        return results

    def reload(self):
        """Borra caché de disco y recarga desde BD en background."""
        try:
            for p in [_CACHE_NPZ, Path(str(_CACHE_NPZ) + ".npz"), _CACHE_META]:
                if p.exists():
                    p.unlink()
        except Exception as e:
            logger.warning(f"DatasetMatrixCache: error borrando disco: {e}")
        with self.lock:
            self.loaded = False
            self.loading = False
            self.matrix = None
            self.mat_centered = None
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
        top_n = config.top_n or 10
        min_similarity = config.min_similarity if config.min_similarity is not None else 0.5
        family_filter = config.family_filter
        # Nota: config.range_min/range_max ya no recortan la comparación — el
        # pipeline unificado siempre trabaja sobre el grid completo FIXED_GRID
        # (400-4000 cm⁻¹); se aceptan en el request por compatibilidad de API.

        results = []

        # Parsear y preprocesar el espectro de consulta UNA vez — se reutiliza tanto
        # para comparar contra los espectros de usuario como contra el dataset.
        try:
            q_raw = json.loads(query_spectrum.wavenumber_data) if query_spectrum.wavenumber_data else {}
            q_wn = np.array(q_raw.get("wavenumbers") or [], dtype=np.float64)
            q_ab = np.array(
                q_raw.get("absorbance") or q_raw.get("intensities") or [],
                dtype=np.float64
            )
            if len(q_wn) == 0 and len(q_ab) > 0:
                q_wn = np.linspace(400, 4000, len(q_ab))
        except Exception:
            q_wn, q_ab = np.array([]), np.array([])

        safe_method = method.lower() if method in ["euclidean", "cosine", "pearson"] else "pearson"
        query_processed = (
            interpolate_and_preprocess(q_wn, q_ab, FIXED_GRID)
            if len(q_wn) > 0 and len(q_ab) > 0 else None
        )

        # ── Espectros de usuario: MISMO pipeline (FIXED_GRID + preprocesamiento +
        # vectorized_similarity) que el dataset de referencia, para que ambas
        # fuentes produzcan scores en la misma escala y sean comparables en un
        # único ranking. ──
        if len(spectra_to_search) > 0 and query_processed is not None:
            logger.info(f"⚡ Buscando en {len(spectra_to_search)} espectros del usuario...")
            user_vectors, user_specs = [], []

            for spectrum in spectra_to_search:
                if family_filter and spectrum.material != family_filter:
                    continue
                try:
                    s_raw = json.loads(spectrum.wavenumber_data) if spectrum.wavenumber_data else {}
                    s_wn = np.array(s_raw.get("wavenumbers") or [], dtype=np.float64)
                    s_ab = np.array(
                        s_raw.get("absorbance") or s_raw.get("intensities") or [],
                        dtype=np.float64
                    )
                    if len(s_wn) == 0 and len(s_ab) > 0:
                        s_wn = np.linspace(400, 4000, len(s_ab))
                    vec = interpolate_and_preprocess(s_wn, s_ab, FIXED_GRID)
                    if vec is None:
                        continue
                    user_vectors.append(vec)
                    user_specs.append(spectrum)
                except Exception as e:
                    logger.debug(f"⚠️ Error procesando espectro de usuario {spectrum.id}: {e}")

            if user_vectors:
                user_matrix = np.array(user_vectors, dtype=np.float32)
                # Score ponderado por ventanas Flanigen (mismo criterio que el dataset)
                user_sims = weighted_matrix_similarity(query_processed, user_matrix, safe_method, struct_mask=STRUCT_MASK)
                query_peaks = detect_peaks_vectorized(FIXED_GRID, query_processed, threshold=0.05)
                for spectrum, vec, sim in zip(user_specs, user_vectors, user_sims):
                    spec_peaks = detect_peaks_vectorized(FIXED_GRID, vec, threshold=0.05)
                    peak_match = match_peaks_vectorized(query_peaks, spec_peaks, tolerance)
                    windowed = compute_window_scores(FIXED_GRID, query_processed, vec, method=safe_method)
                    # Best-effort: si el usuario escribió directamente un código IZA
                    # (p.ej. "LTA") en material, lo pasamos tal cual — el endpoint de
                    # estructura simplemente devuelve 404 si no matchea nada real.
                    material = (spectrum.material or "").strip()
                    guessed_code = material.upper() if material.isalpha() and 2 <= len(material) <= 6 else None
                    results.append({
                        "spectrum_id": spectrum.id,
                        "filename": spectrum.filename,
                        "family": spectrum.material or "N/D",
                        "framework_code": guessed_code,
                        "global_score": float(sim),
                        "window_scores": windowed["window_scores"],
                        "matching_peaks": peak_match["matched_count"],
                        "total_peaks": peak_match["total"],
                        "source": "user_database",
                        "rank": 0
                    })

        logger.info(f"⚡ Iniciando búsqueda en dataset...")

        # ── Dataset de referencia: siempre vía el caché matricial. Si aún no ha
        # terminado de cargar, se responde 503+Retry-After en vez de recaer en una
        # ruta de respaldo que comparaba espectros por índice de array (ignorando
        # los números de onda) — resultados que no eran científicamente válidos. ──
        if not dataset_matrix_cache.loaded:
            logger.warning("⚠️ Cache matricial no cargado todavía")
            if not results:
                raise HTTPException(
                    status_code=503,
                    detail="El motor de búsqueda del dataset todavía está cargando. Reintenta en unos segundos.",
                    headers={"Retry-After": "5"},
                )
            dataset_results = []
        elif query_processed is None:
            logger.warning("⚠️ Espectro de consulta sin datos válidos para buscar en el dataset")
            dataset_results = []
        else:
            logger.info("⚡ Usando cache matricial (búsqueda instantánea)")
            dataset_results = dataset_matrix_cache.search(
                q_wn, q_ab,
                method=safe_method,
                min_similarity=min_similarity,
                top_n=top_n,
                tolerance=tolerance,
                family_filter=family_filter,
            )

        for result in dataset_results:
            results.append({
                "spectrum_id": result["spectrum_id"],
                "filename": f"{result['sample_code']} ({result['zeolite_name']})",
                "family": result["zeolite_name"],
                "framework_code": result.get("framework_code"),
                "global_score": result["similarity"],
                "window_scores": result.get("window_scores", []),
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

        # Persistir el historial de búsqueda (best-effort: un fallo aquí no debe
        # impedir devolver los resultados ya calculados al usuario).
        try:
            db.add(SimilarityResultModel(
                user_id=current_user.id,
                query_spectrum_id=request.query_spectrum_id,
                search_method=safe_method,
                tolerance=tolerance,
                top_n=top_n,
                min_similarity=min_similarity,
                family_filter=family_filter,
                results=results,
                total_spectra_searched=len(spectra_to_search) + len(dataset_results),
                execution_time_ms=float(execution_time_ms),
                results_found=len(results),
                algorithm_version=ALGORITHM_VERSION,
            ))
            db.commit()
        except Exception as e:
            logger.warning(f"⚠️ No se pudo persistir el historial de búsqueda: {e}")
            db.rollback()

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
                "searched_at": datetime.now().isoformat(),
                "min_similarity": min_similarity,
                "algorithm_version": ALGORITHM_VERSION,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en búsqueda: {type(e).__name__}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error en búsqueda")


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
        logger.error(f"❌ Error comparación: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error en comparación de espectros")


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
        raise HTTPException(status_code=500, detail="Error obteniendo espectro para comparación")
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
    """
    Obtener metadatos de los espectros del dataset.
    Sirve desde el cache en RAM cuando está disponible (instantáneo).
    spectrum_data se omite en el listado; usar GET /spectrum/{id} para datos completos.
    """
    # ── Camino rápido: cache en RAM ya disponible ──────────────────────
    if dataset_matrix_cache.loaded:
        all_meta = dataset_matrix_cache.metadata
        total = len(all_meta)
        page = all_meta[skip: skip + limit]
        spectra = [
            {
                "id": m["spectrum_id"],
                "sample_code": m["sample_code"],
                "zeolite_name": m["zeolite_name"],
                "equipment": m["equipment"],
                "measurement_date": m["measurement_date"],
                "filename": f"{m['sample_code']} ({m['zeolite_name']})",
                "spectrum_data": {},          # carga bajo demanda con /spectrum/{id}
            }
            for m in page
        ]
        return {
            "success": True,
            "data": spectra,
            "total": total,
            "pagination": {"skip": skip, "limit": limit, "total": total},
            "source": "cache",
        }

    # ── Camino lento: cache no listo → consulta BD solo metadatos ──────
    connection = None
    cursor = None
    try:
        connection = connect_dataset_db()
        if not connection:
            raise HTTPException(status_code=500, detail="No se pudo conectar al dataset")

        cursor = connection.cursor()
        cursor.execute("SELECT COUNT(*) FROM ftir_spectra")
        total = (cursor.fetchone() or [0])[0]

        # SIN spectrum_data para evitar transferir cientos de MB
        cursor.execute("""
            SELECT fs.id, zs.sample_code, zt.name, fs.equipment, fs.measurement_date
            FROM ftir_spectra fs
            JOIN zeolite_samples zs ON fs.sample_id = zs.id
            JOIN zeolite_types zt ON zs.zeolite_type_id = zt.id
            ORDER BY fs.id DESC
            LIMIT %s OFFSET %s
        """, (limit, skip))

        spectra = [
            {
                "id": r[0],
                "sample_code": r[1],
                "zeolite_name": r[2],
                "equipment": r[3],
                "measurement_date": str(r[4]) if r[4] else None,
                "filename": f"{r[1]} ({r[2]})",
                "spectrum_data": {},
            }
            for r in cursor.fetchall()
        ]

        return {
            "success": True,
            "data": spectra,
            "total": total,
            "pagination": {"skip": skip, "limit": limit, "total": total},
            "source": "database",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error obteniendo dataset: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error obteniendo dataset")
    finally:
        if cursor:
            try: cursor.close()
            except: pass
        if connection and connection.is_connected():
            try: connection.close()
            except: pass


# ========================================
# GET SPECTRUM INFO
# ========================================

@router.get("/spectrum/{spectrum_id}")
def get_spectrum_info(spectrum_id: int, current_user: User = Depends(get_current_user)):
    """
    Obtener datos completos de un espectro del dataset.
    Sirve desde cache en RAM cuando disponible (sin BD); recae en BD si no.
    """
    # Camino rápido: buscar en el cache por spectrum_id
    if dataset_matrix_cache.loaded:
        for i, meta in enumerate(dataset_matrix_cache.metadata):
            if meta["spectrum_id"] == spectrum_id:
                return {
                    "success": True,
                    "spectrum": {
                        "id": spectrum_id,
                        "spectrum_data": {
                            "wavenumbers": FIXED_GRID.tolist(),
                            "intensities": dataset_matrix_cache.matrix[i].tolist(),
                        },
                        "sample_code": meta["sample_code"],
                        "zeolite_name": meta["zeolite_name"],
                        "equipment": meta["equipment"],
                        "measurement_date": meta["measurement_date"],
                    },
                    "source": "cache",
                }

    # Camino BD (fallback)
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
        raise HTTPException(status_code=500, detail="Error obteniendo espectro")
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
    npz = Path(str(_CACHE_NPZ) + ".npz") if not str(_CACHE_NPZ).endswith(".npz") else _CACHE_NPZ
    disk_cached = npz.exists() and _CACHE_META.exists()
    return {
        "loaded": c.loaded,
        "loading": c.loading,
        "total_spectra": c.total_loaded,
        "load_time": c.load_time.isoformat() if c.load_time else None,
        "matrix_shape": list(c.matrix.shape) if c.matrix is not None else None,
        "ram_mb": round(c.matrix.nbytes / 1024 / 1024, 2) if c.matrix is not None else 0,
        "disk_cache_exists": disk_cached,
    }


@router.post("/cache/reload")
def reload_cache(current_user: User = Depends(require_admin)):
    """Fuerza la recarga del cache matricial en segundo plano. Solo administradores."""
    dataset_matrix_cache.reload()
    return {"message": "Recarga del cache iniciada en segundo plano"}