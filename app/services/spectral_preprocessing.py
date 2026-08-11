"""
Preprocesamiento espectral FTIR compartido.

Aplica la secuencia estándar en quimiometría antes de calcular cualquier métrica de
similitud, para que el score mida forma de banda y no artefactos de medición:

  1. Corrección de línea base (arPLS) — elimina la deriva por dispersión (scattering)
     y offsets instrumentales, la principal fuente de varianza no química en FTIR de
     zeolitas medidas en KBr/ATR.
  2. Suavizado Savitzky-Golay — reduce ruido de alta frecuencia sin ensanchar bandas
     (a diferencia de un promedio móvil / boxcar).
  3. Normalización SNV (Standard Normal Variate) — (y - media) / desviación estándar.
     Más robusta que min-max, que depende únicamente de los dos valores extremos y en
     zeolitas hidratadas suele quedar fijada por la banda O-H de agua adsorbida.

Usado tanto por SimilarityCalculator (espectros subidos por usuarios) como por
DatasetMatrixCache (dataset de referencia), para que ambas rutas produzcan scores
sobre la misma base y sean comparables entre sí.
"""

import logging
from typing import Optional

import numpy as np
from scipy.signal import savgol_filter

logger = logging.getLogger(__name__)

# Identifica QUÉ versión de este pipeline produjo un score — persistido junto a
# cada búsqueda guardada (SimilarityResult.algorithm_version) para que los
# resultados históricos sean interpretables cuando el pipeline cambie más
# adelante (reproducibilidad: un score de 0.8 con la v1 y otro con la v2 no
# necesariamente significan lo mismo). Incrementar el número mayor ante
# cualquier cambio que altere los scores existentes (nueva ponderación, nueva
# fórmula, nuevo preprocesamiento); el menor para cambios que no deberían
# alterar scores ya calculados (refactors, optimizaciones).
ALGORITHM_VERSION = "2.0.0"  # v2: preprocesamiento arPLS+SavGol+SNV, HQI=r², ventanas Flanigen 0.7/0.3

# ---------------------------------------------------------------------------
# Ventanas diagnósticas de zeolitas (clasificación Flanigen-Khatami-Szymanski)
# ---------------------------------------------------------------------------
# Bandas de red en la región de "huella dactilar" (400-1300 cm⁻¹): son las que
# identifican la topología del framework (anillos dobles D4R/D6R, conectividad
# T-O-T). Fuera de esa región (p.ej. 1300-4000 cm⁻¹, donde vive la banda O-H de
# agua adsorbida ~1640/3600 cm⁻¹) el espectro refleja sobre todo el estado de
# hidratación de la muestra, no su estructura — por eso pesa menos en el score.
FLANIGEN_WINDOWS = [
    {"code": "pore_opening", "label": "Apertura de poro", "min": 300.0, "max": 420.0},
    {"code": "oto_bending", "label": "Flexión O-T-O (interna)", "min": 420.0, "max": 500.0},
    {"code": "double_ring", "label": "Anillos dobles (D4R/D6R)", "min": 500.0, "max": 650.0},
    {"code": "sym_stretch", "label": "Estiramiento simétrico T-O", "min": 650.0, "max": 820.0},
    {"code": "asym_stretch", "label": "Estiramiento asimétrico T-O", "min": 950.0, "max": 1250.0},
]

STRUCTURAL_REGION = (400.0, 1300.0)
STRUCTURAL_WEIGHT = 0.7
NON_STRUCTURAL_WEIGHT = round(1.0 - STRUCTURAL_WEIGHT, 2)

# Por debajo de este número de puntos, arPLS y Savitzky-Golay no tienen suficiente
# soporte para ajustar de forma fiable — se aplica solo SNV.
MIN_POINTS_FOR_BASELINE_AND_SMOOTHING = 15

DEFAULT_BASELINE_LAM = 1e5
DEFAULT_SAVGOL_WINDOW = 11
DEFAULT_SAVGOL_POLYORDER = 3


def correct_baseline_arpls(absorbance: np.ndarray, lam: float = DEFAULT_BASELINE_LAM) -> np.ndarray:
    """
    Corrección de línea base con arPLS (Asymmetrically Reweighted Penalized Least
    Squares, Baek et al. 2015) vía pybaselines. `lam` controla la suavidad de la
    línea base estimada: mayor lam -> línea base más rígida/suave.

    Puede lanzar excepciones de pybaselines/numpy con espectros degenerados
    (constantes, con NaN); el llamador decide cómo manejarlo.
    """
    from pybaselines import Baseline  # import perezoso: pybaselines es pesado de cargar

    baseline_fitter = Baseline()
    baseline, _ = baseline_fitter.arpls(absorbance, lam=lam)
    return absorbance - baseline


def smooth_savgol(
    absorbance: np.ndarray,
    window_length: int = DEFAULT_SAVGOL_WINDOW,
    polyorder: int = DEFAULT_SAVGOL_POLYORDER,
) -> np.ndarray:
    """
    Suavizado Savitzky-Golay. `window_length` se ajusta automáticamente para ser
    impar y no exceder el tamaño del espectro; si queda demasiado pequeño para el
    orden del polinomio pedido, se omite el suavizado (mejor no suavizar que fallar).
    """
    n = len(absorbance)
    window = window_length if window_length % 2 == 1 else window_length + 1
    window = min(window, n if n % 2 == 1 else n - 1)
    if window <= polyorder:
        logger.debug(
            f"smooth_savgol: espectro de {n} puntos insuficiente para "
            f"window={window_length}/polyorder={polyorder} — se omite suavizado"
        )
        return absorbance
    return savgol_filter(absorbance, window_length=window, polyorder=polyorder)


def normalize_snv(absorbance: np.ndarray) -> np.ndarray:
    """
    Standard Normal Variate: (y - media) / desviación estándar.
    Si el espectro es (casi) constante, solo se centra (evita división por ~0).
    """
    std = float(np.std(absorbance))
    mean = float(np.mean(absorbance))
    if std < 1e-10:
        return absorbance - mean
    return (absorbance - mean) / std


def preprocess_spectrum(
    absorbance,
    baseline_lam: float = DEFAULT_BASELINE_LAM,
    savgol_window: int = DEFAULT_SAVGOL_WINDOW,
    savgol_polyorder: int = DEFAULT_SAVGOL_POLYORDER,
    apply_baseline: bool = True,
) -> np.ndarray:
    """
    Pipeline completo: arPLS -> Savitzky-Golay -> SNV.

    Con menos de MIN_POINTS_FOR_BASELINE_AND_SMOOTHING puntos se omiten los dos
    primeros pasos (no tienen soporte suficiente) y se aplica solo SNV.
    Si arPLS falla (espectro degenerado, NaN, etc.) se registra la causa concreta y
    se continúa sin corrección de línea base — nunca se enmascara como score 0.0.
    """
    arr = np.asarray(absorbance, dtype=np.float64)

    if len(arr) < MIN_POINTS_FOR_BASELINE_AND_SMOOTHING:
        logger.debug(
            f"preprocess_spectrum: {len(arr)} puntos "
            f"(<{MIN_POINTS_FOR_BASELINE_AND_SMOOTHING}) — solo SNV"
        )
        return normalize_snv(arr)

    if apply_baseline:
        try:
            arr = correct_baseline_arpls(arr, lam=baseline_lam)
        except (ValueError, np.linalg.LinAlgError, FloatingPointError) as e:
            logger.warning(
                f"preprocess_spectrum: arPLS falló ({type(e).__name__}: {e}); "
                "continuando sin corrección de línea base"
            )

    arr = smooth_savgol(arr, window_length=savgol_window, polyorder=savgol_polyorder)
    arr = normalize_snv(arr)
    return arr


def interpolate_and_preprocess(
    wavenumbers,
    absorbance,
    grid: np.ndarray,
    min_grid_points: int = 50,
) -> Optional[np.ndarray]:
    """
    Interpola (wavenumbers, absorbance) a `grid` y aplica el pipeline de
    preprocesamiento (máscara CO2 + arPLS + Savitzky-Golay + SNV) solo sobre los
    puntos dentro del rango medido — aplicarlo al vector completo con relleno de
    ceros generaría artefactos de suavizado en ese salto abrupto.

    Devuelve un vector float32 del mismo tamaño que `grid`, con 0.0 fuera del rango
    medido, o None si el espectro no tiene soporte suficiente (muy corto, sin
    solapamiento con `grid`, o degenerado/constante).

    Función compartida: la usan tanto el dataset de referencia (DatasetMatrixCache)
    como los espectros de usuario, para que ambas fuentes produzcan vectores
    comparables entre sí y con las mismas métricas.
    """
    wn = np.asarray(wavenumbers, dtype=np.float64)
    ab = np.asarray(absorbance, dtype=np.float64)
    n = min(len(wn), len(ab))
    if n < 2:
        return None
    wn, ab = wn[:n], ab[:n]

    sort_idx = np.argsort(wn)
    wn, ab = wn[sort_idx], ab[sort_idx]

    wn_min, wn_max = float(wn[0]), float(wn[-1])
    grid_mask = (grid >= wn_min) & (grid <= wn_max)
    if int(np.sum(grid_mask)) < min_grid_points:
        return None

    interp_vals = np.interp(grid[grid_mask], wn, ab)
    mn, mx = float(interp_vals.min()), float(interp_vals.max())
    if mx - mn < 1e-10:
        return None

    interp_vals = mask_atmospheric_co2(grid[grid_mask], interp_vals)
    interp_vals = preprocess_spectrum(interp_vals)

    out = np.zeros(len(grid), dtype=np.float32)
    out[grid_mask] = interp_vals.astype(np.float32)
    return out


def vectorized_similarity(
    query_vec: np.ndarray,
    matrix: np.ndarray,
    method: str = "pearson",
    norms: Optional[np.ndarray] = None,
    mat_centered: Optional[np.ndarray] = None,
    stds: Optional[np.ndarray] = None,
) -> np.ndarray:
    """
    Similitud entre `query_vec` (ya interpolado+preprocesado por
    interpolate_and_preprocess) y cada fila de `matrix` (mismo preprocesamiento),
    con una única fórmula por método — la misma que usa el caché matricial del
    dataset, para que espectros de usuario y de referencia sean comparables.

    `norms`/`mat_centered`/`stds` pueden pasarse precomputados (como hace
    DatasetMatrixCache para sus miles de filas); si se omiten, se calculan al
    vuelo — barato para matrices pequeñas como los espectros de un usuario.
    """
    n_rows, L = matrix.shape
    if n_rows == 0:
        return np.zeros(0, dtype=np.float32)

    if method == "cosine":
        if norms is None:
            norms = np.linalg.norm(matrix, axis=1)
        q_norm_val = float(np.linalg.norm(query_vec))
        if q_norm_val < 1e-10:
            return np.zeros(n_rows, dtype=np.float32)
        sims = (matrix @ query_vec) / (norms * q_norm_val + 1e-10)
        return np.clip((sims + 1.0) / 2.0, 0.0, 1.0)

    elif method == "pearson":
        if mat_centered is None:
            mat_centered = matrix - np.mean(matrix, axis=1, keepdims=True)
        if stds is None:
            stds = np.std(matrix, axis=1)
        q_centered = (query_vec - float(np.mean(query_vec))).astype(np.float32)
        q_std = float(np.std(query_vec))
        if q_std < 1e-10:
            return np.zeros(n_rows, dtype=np.float32)
        cov = (mat_centered @ q_centered) / L
        correlations = cov / (stds * q_std + 1e-10)
        return np.clip(correlations ** 2, 0.0, 1.0)  # HQI = r²

    elif method == "euclidean":
        diffs = matrix - query_vec
        distances = np.linalg.norm(diffs, axis=1) / (np.sqrt(L) + 1e-10)
        return 1.0 / (1.0 + distances)

    return np.zeros(n_rows, dtype=np.float32)


def structural_region_mask(
    grid: np.ndarray,
    structural_range: tuple = STRUCTURAL_REGION,
) -> np.ndarray:
    """Máscara booleana sobre `grid`: True dentro de la región estructural
    (huella dactilar, 400-1300 cm⁻¹ por defecto)."""
    lo, hi = structural_range
    return (grid >= lo) & (grid < hi)


def compute_window_scores(
    grid: np.ndarray,
    vec_a: np.ndarray,
    vec_b: np.ndarray,
    method: str = "pearson",
    structural_range: tuple = STRUCTURAL_REGION,
    structural_weight: float = STRUCTURAL_WEIGHT,
) -> dict:
    """
    Compara dos espectros ya interpolados+preprocesados (mismo `grid`) ventana por
    ventana según la clasificación Flanigen-Khatami-Szymanski, y compone un score
    global ponderando `structural_weight` la región estructural (400-1300 cm⁻¹,
    donde viven las bandas diagnósticas de topología: anillos dobles, T-O-T) y
    `1-structural_weight` el resto del espectro (p.ej. OH/H2O, que depende del
    estado de hidratación y no de la estructura).

    Uso: comparaciones de un par de espectros (SimilarityCalculator, /compare).
    Para el dataset completo (miles de filas), ver weighted_matrix_similarity.

    Retorna {"global_score": float, "window_scores": [...]}.
    """
    def region_score(mask: np.ndarray) -> Optional[float]:
        if int(np.sum(mask)) < 3:
            return None
        sims = vectorized_similarity(vec_a[mask], vec_b[mask].reshape(1, -1), method)
        return float(sims[0])

    windows = []
    for w in FLANIGEN_WINDOWS:
        mask = (grid >= w["min"]) & (grid < w["max"])
        windows.append({
            "code": w["code"], "label": w["label"],
            "range_cm1": [w["min"], w["max"]], "score": region_score(mask),
        })

    struct_mask = structural_region_mask(grid, structural_range)
    structural_score = region_score(struct_mask)
    non_structural_score = region_score(~struct_mask)

    if structural_score is not None and non_structural_score is not None:
        global_score = structural_weight * structural_score + (1 - structural_weight) * non_structural_score
    elif structural_score is not None:
        global_score = structural_score
    elif non_structural_score is not None:
        global_score = non_structural_score
    else:
        global_score = 0.0

    lo, hi = structural_range
    windows.append({
        "code": "structural_region",
        "label": f"Región estructural ({lo:.0f}-{hi:.0f} cm⁻¹)",
        "range_cm1": [lo, hi], "score": structural_score, "weight": structural_weight,
    })
    windows.append({
        "code": "non_structural_region",
        "label": "Resto del espectro (OH/H2O — refleja hidratación, no estructura)",
        "range_cm1": None, "score": non_structural_score,
        "weight": round(1 - structural_weight, 2),
    })

    return {
        "global_score": float(np.clip(global_score, 0.0, 1.0)),
        "window_scores": windows,
    }


def weighted_matrix_similarity(
    query_vec: np.ndarray,
    matrix: np.ndarray,
    method: str,
    struct_mask: np.ndarray,
    struct_norms: Optional[np.ndarray] = None,
    struct_mat_centered: Optional[np.ndarray] = None,
    struct_stds: Optional[np.ndarray] = None,
    nonstruct_norms: Optional[np.ndarray] = None,
    nonstruct_mat_centered: Optional[np.ndarray] = None,
    nonstruct_stds: Optional[np.ndarray] = None,
    structural_weight: float = STRUCTURAL_WEIGHT,
) -> np.ndarray:
    """
    Score global ponderado (0.7 región estructural / 0.3 resto) para TODAS las
    filas de `matrix` de una sola vez — dos operaciones matriciales (una por
    submatriz de columnas) en vez de iterar fila a fila, para mantener la
    búsqueda contra el dataset completo prácticamente instantánea.

    Los `*_norms`/`*_mat_centered`/`*_stds` de cada submatriz pueden precomputarse
    una vez al cargar el dataset (ver DatasetMatrixCache.load) y pasarse aquí para
    evitar recalcularlos en cada búsqueda.
    """
    sims_struct = vectorized_similarity(
        query_vec[struct_mask], matrix[:, struct_mask], method,
        norms=struct_norms, mat_centered=struct_mat_centered, stds=struct_stds,
    )
    sims_nonstruct = vectorized_similarity(
        query_vec[~struct_mask], matrix[:, ~struct_mask], method,
        norms=nonstruct_norms, mat_centered=nonstruct_mat_centered, stds=nonstruct_stds,
    )
    return np.clip(
        structural_weight * sims_struct + (1 - structural_weight) * sims_nonstruct,
        0.0, 1.0,
    )


def mask_atmospheric_co2(
    wavenumbers: np.ndarray,
    absorbance: np.ndarray,
    co2_min: float = 2300.0,
    co2_max: float = 2400.0,
) -> np.ndarray:
    """
    Devuelve una copia de `absorbance` con la región de CO2 atmosférico
    (2300-2400 cm-1 por defecto) interpolada linealmente entre sus bordes, para que
    no contribuya a las métricas de similitud. Esta banda depende de la purga del
    espectrómetro en el momento de la medida, no de la muestra.
    """
    wn = np.asarray(wavenumbers, dtype=np.float64)
    ab = np.asarray(absorbance, dtype=np.float64).copy()

    mask = (wn >= co2_min) & (wn <= co2_max)
    if not np.any(mask) or np.all(mask):
        return ab

    idx = np.where(mask)[0]
    lo, hi = idx[0], idx[-1]
    left = lo - 1 if lo > 0 else lo
    right = hi + 1 if hi < len(ab) - 1 else hi
    if left == right:
        return ab

    ab[idx] = np.interp(wn[idx], [wn[left], wn[right]], [ab[left], ab[right]])
    return ab
