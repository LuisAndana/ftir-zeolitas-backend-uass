"""
Tests de regresión numérica para app/services/spectral_preprocessing.py.

Estos protegen los fixes de la sesión 2026-08-09: corrección de línea base,
normalización SNV, máscara de CO2, HQI = r² (no satura a 0/1), y la ponderación
0.7/0.3 de las ventanas Flanigen.
"""
import numpy as np
import pytest

from app.services.spectral_preprocessing import (
    correct_baseline_arpls,
    mask_atmospheric_co2,
    normalize_snv,
    preprocess_spectrum,
    smooth_savgol,
    interpolate_and_preprocess,
    vectorized_similarity,
    compute_window_scores,
    weighted_matrix_similarity,
    structural_region_mask,
    FLANIGEN_WINDOWS,
    STRUCTURAL_WEIGHT,
)


# ---------------------------------------------------------------------------
# normalize_snv
# ---------------------------------------------------------------------------

def test_normalize_snv_centers_and_scales():
    rng = np.random.RandomState(0)
    y = rng.normal(5, 2, 500)
    out = normalize_snv(y)
    assert abs(np.mean(out)) < 1e-9
    assert abs(np.std(out) - 1.0) < 1e-9


def test_normalize_snv_constant_signal_no_division_by_zero():
    y = np.full(100, 3.5)
    out = normalize_snv(y)
    assert np.all(out == 0.0)
    assert not np.any(np.isnan(out))


# ---------------------------------------------------------------------------
# arPLS baseline correction
# ---------------------------------------------------------------------------

def test_arpls_reduces_linear_drift(wn_grid):
    x = np.linspace(0, 10, len(wn_grid))
    signal = np.sin(x) * 0.4
    drift = 0.2 + 0.0003 * (wn_grid - wn_grid.min())
    raw = signal + drift
    corrected = correct_baseline_arpls(raw)
    slope_before = np.polyfit(wn_grid, raw, 1)[0]
    slope_after = np.polyfit(wn_grid, corrected, 1)[0]
    assert abs(slope_after) < abs(slope_before) * 0.5


# ---------------------------------------------------------------------------
# Savitzky-Golay smoothing
# ---------------------------------------------------------------------------

def test_smooth_savgol_reduces_noise_variance():
    rng = np.random.RandomState(1)
    x = np.linspace(0, 10, 500)
    clean = np.sin(x)
    noisy = clean + rng.normal(0, 0.15, 500)
    smoothed = smooth_savgol(noisy)
    err_noisy = np.mean((noisy - clean) ** 2)
    err_smoothed = np.mean((smoothed - clean) ** 2)
    assert err_smoothed < err_noisy


def test_smooth_savgol_short_spectrum_no_crash():
    y = np.array([0.1, 0.5, 0.9, 0.3])
    out = smooth_savgol(y, window_length=11, polyorder=3)
    assert len(out) == len(y)


# ---------------------------------------------------------------------------
# preprocess_spectrum (pipeline completo)
# ---------------------------------------------------------------------------

def test_preprocess_spectrum_full_pipeline(synthetic_lta_spectrum):
    out = preprocess_spectrum(synthetic_lta_spectrum)
    assert out.shape == synthetic_lta_spectrum.shape
    assert not np.any(np.isnan(out))
    assert abs(np.mean(out)) < 1.0  # SNV centra cerca de 0


def test_preprocess_spectrum_short_spectrum_uses_only_snv():
    short = np.array([0.1, 0.5, 0.9, 0.3, 0.2, 0.6, 0.8])
    out = preprocess_spectrum(short)
    assert len(out) == len(short)
    assert abs(np.mean(out)) < 1e-6


# ---------------------------------------------------------------------------
# mask_atmospheric_co2
# ---------------------------------------------------------------------------

def test_mask_atmospheric_co2_removes_spike(wn_grid):
    baseline = np.full(len(wn_grid), 0.1)
    co2_region = (wn_grid >= 2300) & (wn_grid <= 2400)
    spiky = baseline.copy()
    spiky[co2_region] = 5.0
    masked = mask_atmospheric_co2(wn_grid, spiky)
    assert np.max(masked[co2_region]) < 1.0
    # Fuera de la región de CO2 no debe tocarse
    assert np.allclose(masked[~co2_region], baseline[~co2_region])


def test_mask_atmospheric_co2_no_region_present():
    wn = np.linspace(400, 1500, 100)  # no cubre 2300-2400
    ab = np.random.RandomState(0).normal(0, 1, 100)
    out = mask_atmospheric_co2(wn, ab)
    assert np.allclose(out, ab)


# ---------------------------------------------------------------------------
# interpolate_and_preprocess
# ---------------------------------------------------------------------------

def test_interpolate_and_preprocess_basic(wn_grid, synthetic_lta_spectrum):
    out = interpolate_and_preprocess(wn_grid, synthetic_lta_spectrum, wn_grid)
    assert out is not None
    assert out.shape == wn_grid.shape
    assert out.dtype == np.float32


def test_interpolate_and_preprocess_insufficient_points(wn_grid):
    out = interpolate_and_preprocess(np.array([500.0]), np.array([0.5]), wn_grid)
    assert out is None


def test_interpolate_and_preprocess_no_overlap(wn_grid):
    wn = np.linspace(5000, 6000, 50)
    ab = np.random.RandomState(0).normal(0, 1, 50)
    out = interpolate_and_preprocess(wn, ab, wn_grid)
    assert out is None


def test_interpolate_and_preprocess_constant_spectrum_is_none(wn_grid):
    wn = np.linspace(400, 4000, 100)
    ab = np.full(100, 0.5)
    out = interpolate_and_preprocess(wn, ab, wn_grid)
    assert out is None


def test_interpolate_and_preprocess_partial_range_fills_zero_outside(wn_grid, synthetic_lta_spectrum):
    # Espectro medido solo en 400-2000 cm-1
    partial_mask = wn_grid <= 2000
    out = interpolate_and_preprocess(wn_grid[partial_mask], synthetic_lta_spectrum[partial_mask], wn_grid)
    assert out is not None
    outside_mask = wn_grid > 2000
    assert np.all(out[outside_mask] == 0.0)


# ---------------------------------------------------------------------------
# vectorized_similarity — HQI = r², no debe saturar a 0/1 (regresión del bug)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("method", ["cosine", "pearson", "euclidean"])
def test_vectorized_similarity_identical_vectors_near_one(method):
    rng = np.random.RandomState(0)
    v = rng.normal(0, 1, 1801).astype(np.float32)
    matrix = np.array([v], dtype=np.float32)
    sims = vectorized_similarity(v, matrix, method)
    assert sims[0] > 0.99, f"{method}: {sims[0]}"


def test_vectorized_similarity_pearson_does_not_saturate_for_moderate_correlation():
    """Regresión directa del bug del 2026-08-09: cov sin dividir por N saturaba
    cualquier correlación positiva a 1.0 y cualquiera negativa a 0.0."""
    rng = np.random.RandomState(2)
    n = 1801
    x = np.linspace(0, 10, n)
    ref = np.sin(x) + rng.normal(0, 0.05, n)
    moderately_correlated = np.sin(x) + rng.normal(0, 0.3, n)

    true_r = np.corrcoef(ref, moderately_correlated)[0, 1]
    expected_hqi = true_r ** 2

    sims = vectorized_similarity(
        ref.astype(np.float32), np.array([moderately_correlated], dtype=np.float32), "pearson"
    )
    assert 0.0 < sims[0] < 1.0, f"HQI saturado a un extremo: {sims[0]}"
    assert abs(float(sims[0]) - expected_hqi) < 1e-3


def test_vectorized_similarity_uncorrelated_near_zero():
    rng = np.random.RandomState(3)
    a = rng.normal(0, 1, 1801).astype(np.float32)
    b = rng.normal(0, 1, 1801).astype(np.float32)
    sims = vectorized_similarity(a, np.array([b], dtype=np.float32), "pearson")
    assert sims[0] < 0.05


def test_vectorized_similarity_empty_matrix():
    v = np.zeros(1801, dtype=np.float32)
    sims = vectorized_similarity(v, np.zeros((0, 1801), dtype=np.float32), "pearson")
    assert len(sims) == 0


def test_vectorized_similarity_unknown_method_returns_zeros():
    v = np.ones(10, dtype=np.float32)
    matrix = np.ones((3, 10), dtype=np.float32)
    sims = vectorized_similarity(v, matrix, "not_a_real_method")
    assert np.all(sims == 0.0)


# ---------------------------------------------------------------------------
# compute_window_scores / weighted_matrix_similarity — ventanas Flanigen 0.7/0.3
# ---------------------------------------------------------------------------

def test_compute_window_scores_identical_spectra(wn_grid, synthetic_lta_spectrum):
    result = compute_window_scores(wn_grid, synthetic_lta_spectrum, synthetic_lta_spectrum, method="pearson")
    assert result["global_score"] > 0.99
    assert len(result["window_scores"]) == len(FLANIGEN_WINDOWS) + 2
    codes = {w["code"] for w in result["window_scores"]}
    assert "structural_region" in codes
    assert "non_structural_region" in codes
    for w in result["window_scores"]:
        if w["score"] is not None:
            assert 0.0 <= w["score"] <= 1.0


def test_compute_window_scores_weighting_favors_structural_region(wn_grid, synthetic_lta_spectrum):
    """Dos espectros idénticos en la región estructural (400-1300) pero distintos
    fuera de ella deben dar un score dominado por STRUCTURAL_WEIGHT, no un 50/50."""
    struct_mask = structural_region_mask(wn_grid)
    a = synthetic_lta_spectrum.copy()
    b = synthetic_lta_spectrum.copy()
    rng = np.random.RandomState(42)
    b[~struct_mask] = rng.normal(0, 1, size=int((~struct_mask).sum()))

    result = compute_window_scores(wn_grid, a, b, method="pearson")
    struct_score = next(w["score"] for w in result["window_scores"] if w["code"] == "structural_region")
    nonstruct_score = next(w["score"] for w in result["window_scores"] if w["code"] == "non_structural_region")

    assert struct_score > 0.95
    expected = STRUCTURAL_WEIGHT * struct_score + (1 - STRUCTURAL_WEIGHT) * nonstruct_score
    assert abs(result["global_score"] - expected) < 1e-6

    naive_average = 0.5 * struct_score + 0.5 * nonstruct_score
    # La ponderación 0.7/0.3 debe acercar el score al valor de la región estructural
    # más que un promedio ingenuo 50/50 (a menos que ambas regiones ya coincidan).
    if abs(struct_score - nonstruct_score) > 0.1:
        assert abs(result["global_score"] - struct_score) < abs(naive_average - struct_score)


def test_weighted_matrix_similarity_matches_compute_window_scores(wn_grid, synthetic_lta_spectrum):
    """Las dos rutas de cálculo (par individual vs. matriz vectorizada) deben
    coincidir — es la garantía de que el pipeline está unificado."""
    struct_mask = structural_region_mask(wn_grid)
    a = synthetic_lta_spectrum.astype(np.float32)
    rng = np.random.RandomState(7)
    b = synthetic_lta_spectrum.copy()
    b[~struct_mask] = rng.normal(0, 1, size=int((~struct_mask).sum()))
    b = b.astype(np.float32)

    pair_result = compute_window_scores(wn_grid, a, b, method="pearson")
    matrix_sims = weighted_matrix_similarity(a, np.array([b]), "pearson", struct_mask=struct_mask)

    assert abs(float(matrix_sims[0]) - pair_result["global_score"]) < 1e-4


@pytest.mark.parametrize("method", ["cosine", "pearson", "euclidean"])
def test_compute_window_scores_all_methods_return_valid_range(wn_grid, synthetic_lta_spectrum, method):
    rng = np.random.RandomState(9)
    other = synthetic_lta_spectrum + rng.normal(0, 0.5, len(wn_grid))
    result = compute_window_scores(wn_grid, synthetic_lta_spectrum, other, method=method)
    assert 0.0 <= result["global_score"] <= 1.0
