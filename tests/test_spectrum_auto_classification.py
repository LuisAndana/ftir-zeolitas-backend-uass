"""
Tests para la auto-clasificación de familia al subir un espectro sin
material especificado (app/routes/spectra.py::_suggest_family) — compara
contra el dataset de referencia con el mismo motor que usa /search, para
que el visor 3D quede disponible sin que el usuario tenga que escribir el
código IZA manualmente.
"""
import numpy as np
import pytest

from app.routes import similarity as sim_module
from app.routes.spectra import _suggest_family
from tests.conftest import make_spectrum_row


@pytest.fixture(autouse=True)
def reset_dataset_cache():
    """El caché matricial es un singleton a nivel de módulo — aislar cada test
    (mismo patrón que tests/test_similarity_routes.py)."""
    cache = sim_module.dataset_matrix_cache
    cache.loaded = False
    cache.loading = False
    cache.matrix = None
    cache.mat_centered = None
    cache.norms = None
    cache.stds = None
    cache.metadata = []
    yield
    cache.loaded = False
    cache.matrix = None


def _load_fake_cache(rows):
    """Puebla dataset_matrix_cache con filas sintéticas sin tocar MySQL."""
    processed = [sim_module.DatasetMatrixCache._process_row(r) for r in rows]
    processed = [p for p in processed if p is not None]
    assert processed, "todas las filas sintéticas deberían procesarse correctamente"
    mat = np.array([p[0] for p in processed], dtype=np.float32)
    meta = [p[1] for p in processed]
    cache = sim_module.dataset_matrix_cache
    cache.matrix = mat
    cache.norms = np.linalg.norm(mat, axis=1)
    cache.means = np.mean(mat, axis=1)
    cache.stds = np.std(mat, axis=1)
    cache.mat_centered = (mat - np.mean(mat, axis=1, keepdims=True)).astype(np.float32)
    cache.metadata = meta
    cache.loaded = True
    cache.total_loaded = len(meta)
    return cache


def test_suggest_family_returns_none_when_cache_not_loaded(synthetic_lta_spectrum, wn_grid):
    """Best-effort: si el caché todavía no cargó (arranque reciente), no debe
    fallar — simplemente no hay sugerencia, y el llamador cae a 'Desconocido'."""
    assert not sim_module.dataset_matrix_cache.loaded
    result = _suggest_family(wn_grid.tolist(), synthetic_lta_spectrum.tolist())
    assert result is None


def test_suggest_family_matches_closest_reference(wn_grid, synthetic_lta_spectrum):
    """Con el caché poblado por una sola familia (LTA), el espectro sintético
    con las bandas típicas de LTA debe sugerir 'LTA' con confianza > 0."""
    row = make_spectrum_row(wn_grid, synthetic_lta_spectrum, spectrum_id=1, structure_type="LTA")
    _load_fake_cache([row])

    result = _suggest_family(wn_grid.tolist(), synthetic_lta_spectrum.tolist())

    assert result is not None
    assert result["code"] == "LTA"
    assert result["zeolite_name"] == "LTA"
    assert 0.0 < result["confidence"] <= 1.0


def test_suggest_family_picks_the_more_similar_of_two_families(wn_grid, synthetic_lta_spectrum):
    """Con dos familias en el caché, debe sugerir la más parecida al
    espectro consultado, no simplemente la primera de la lista."""
    unrelated = np.full_like(wn_grid, 0.02)  # espectro plano, sin ninguna banda real
    rows = [
        make_spectrum_row(wn_grid, synthetic_lta_spectrum, spectrum_id=1, structure_type="LTA"),
        make_spectrum_row(wn_grid, unrelated, spectrum_id=2, sample_code="S002",
                           zeolite_name="Faujasita", structure_type="FAU"),
    ]
    _load_fake_cache(rows)

    result = _suggest_family(wn_grid.tolist(), synthetic_lta_spectrum.tolist())

    assert result is not None
    assert result["code"] == "LTA"


def test_suggest_family_returns_none_on_empty_spectrum(wn_grid, synthetic_lta_spectrum):
    """Espectro vacío (parseo fallido, por ejemplo) no debe lanzar excepción."""
    row = make_spectrum_row(wn_grid, synthetic_lta_spectrum, spectrum_id=1, structure_type="LTA")
    _load_fake_cache([row])

    assert _suggest_family([], []) is None
