"""
Tests de regresión para app/services/similarity_calculator.py.
"""
import json

import numpy as np
import pytest

from app.services.similarity_calculator import SimilarityCalculator


class FakeSpectrum:
    """Objeto mínimo con el atributo wavenumber_data que espera calculate_similarity."""
    def __init__(self, id_, wn, ab):
        self.id = id_
        self.wavenumber_data = json.dumps({"wavenumbers": wn.tolist(), "absorbance": ab.tolist()})


@pytest.fixture()
def calculator():
    return SimilarityCalculator()


def test_pearson_correlation_is_hqi_r_squared(calculator):
    """Regresión: (r+1)/2 hacía que r=0 diera 0.5 ('50% de similitud' engañoso).
    r² da correctamente 0 cuando no hay relación lineal."""
    rng = np.random.RandomState(0)
    a = list(rng.normal(0, 1, 500))
    b = list(rng.normal(0, 1, 500))
    score = calculator.pearson_correlation(a, b)
    assert 0.0 <= score <= 1.0
    assert score < 0.1  # sin relación real -> cerca de 0, no de 0.5


def test_pearson_correlation_identical_series_is_one(calculator):
    a = list(np.sin(np.linspace(0, 10, 500)))
    score = calculator.pearson_correlation(a, a)
    assert score > 0.999


def test_pearson_correlation_constant_series_returns_zero_not_nan(calculator):
    a = [1.0] * 100
    b = list(np.random.RandomState(0).normal(0, 1, 100))
    score = calculator.pearson_correlation(a, b)
    assert score == 0.0


def test_calculate_similarity_end_to_end(calculator, wn_grid, synthetic_lta_spectrum):
    rng = np.random.RandomState(1)
    s1 = FakeSpectrum(1, wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.005, len(wn_grid)))
    s2 = FakeSpectrum(2, wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)))

    result = calculator.calculate_similarity(s1, s2, method="pearson")

    assert result is not None
    assert 0.0 <= result["global_score"] <= 1.0
    assert result["global_score"] > 0.7  # espectros muy similares
    assert isinstance(result["window_scores"], list)
    assert len(result["window_scores"]) > 0
    assert "matching_peaks" in result and "total_peaks" in result


def test_calculate_similarity_dissimilar_spectra_scores_low(calculator, wn_grid, synthetic_lta_spectrum):
    rng = np.random.RandomState(2)
    s1 = FakeSpectrum(1, wn_grid, synthetic_lta_spectrum)
    noise_spectrum = 0.5 + rng.normal(0, 0.3, len(wn_grid))
    s2 = FakeSpectrum(2, wn_grid, noise_spectrum)

    result = calculator.calculate_similarity(s1, s2, method="pearson")
    assert result is not None
    assert result["global_score"] < 0.3


def test_calculate_similarity_no_overlap_returns_none(calculator):
    wn1 = np.linspace(400, 1000, 100)
    wn2 = np.linspace(3000, 4000, 100)
    s1 = FakeSpectrum(1, wn1, np.random.RandomState(0).normal(0, 1, 100))
    s2 = FakeSpectrum(2, wn2, np.random.RandomState(1).normal(0, 1, 100))

    result = calculator.calculate_similarity(s1, s2, method="pearson")
    assert result is None


def test_calculate_similarity_empty_data_returns_none(calculator):
    s1 = FakeSpectrum(1, np.array([]), np.array([]))
    s2 = FakeSpectrum(2, np.array([400.0, 500.0]), np.array([0.1, 0.2]))
    result = calculator.calculate_similarity(s1, s2)
    assert result is None


def test_align_spectra_returns_matching_wavenumber_axis():
    wn1 = [400.0, 500.0, 600.0, 700.0]
    abs1 = [0.1, 0.5, 0.3, 0.2]
    wn2 = [400.0, 500.0, 600.0, 700.0]
    abs2 = [0.15, 0.45, 0.35, 0.25]

    aligned1, aligned2, aligned_wn = SimilarityCalculator.align_spectra(wn1, abs1, wn2, abs2, tolerance=4)

    assert len(aligned1) == len(aligned2) == len(aligned_wn)
    assert len(aligned_wn) > 0
    assert min(aligned_wn) >= 400.0
    assert max(aligned_wn) <= 700.0


def test_align_spectra_no_overlap_returns_empty_lists():
    aligned1, aligned2, aligned_wn = SimilarityCalculator.align_spectra(
        [400.0, 500.0], [0.1, 0.2], [3000.0, 3100.0], [0.1, 0.2], tolerance=4
    )
    assert aligned1 == [] and aligned2 == [] and aligned_wn == []
