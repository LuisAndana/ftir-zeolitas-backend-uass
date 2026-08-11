"""
Tests de regresión para app/routes/similarity.py: DatasetMatrixCache y el endpoint
/search unificado (usuario + dataset en el mismo pipeline, 503 sin ruta de respaldo).
"""
import json

import numpy as np
import pytest
from fastapi import HTTPException

from app.routes import similarity as sim_module
from app.schemas.similarity import SimilaritySearchRequest, SimilarityConfig
from tests.conftest import make_spectrum_row, make_user_spectrum


@pytest.fixture(autouse=True)
def reset_dataset_cache():
    """El caché matricial es un singleton a nivel de módulo — aislar cada test."""
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


# ---------------------------------------------------------------------------
# DatasetMatrixCache._process_row
# ---------------------------------------------------------------------------

def test_process_row_valid_spectrum(wn_grid, synthetic_lta_spectrum):
    row = make_spectrum_row(wn_grid, synthetic_lta_spectrum)
    result = sim_module.DatasetMatrixCache._process_row(row)
    assert result is not None
    vec, meta = result
    assert vec.shape == (len(sim_module.FIXED_GRID),)
    assert meta["spectrum_id"] == 1
    assert meta["zeolite_name"] == "LTA"


def test_process_row_too_few_points_returns_none():
    row = (1, json.dumps({"wavenumbers": [500.0], "intensities": [0.5]}), "S1", "LTA", "Eq", None)
    assert sim_module.DatasetMatrixCache._process_row(row) is None


def test_process_row_malformed_json_returns_none():
    row = (1, "not valid json{{{", "S1", "LTA", "Eq", None)
    assert sim_module.DatasetMatrixCache._process_row(row) is None


def test_process_row_empty_spectrum_data_returns_none():
    row = (1, None, "S1", "LTA", "Eq", None)
    assert sim_module.DatasetMatrixCache._process_row(row) is None


# ---------------------------------------------------------------------------
# DatasetMatrixCache.search — ponderación Flanigen y consistencia
# ---------------------------------------------------------------------------

def test_dataset_cache_search_ranks_similar_above_noise(wn_grid, synthetic_lta_spectrum):
    rng = np.random.RandomState(0)
    rows = [
        make_spectrum_row(wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)), 1, "S001", "LTA"),
        make_spectrum_row(wn_grid, 0.5 + rng.normal(0, 0.3, len(wn_grid)), 2, "S002", "RANDOM"),
    ]
    cache = _load_fake_cache(rows)

    results = cache.search(wn_grid, synthetic_lta_spectrum, method="pearson", min_similarity=0.0, top_n=10)
    assert len(results) == 2
    by_id = {r["spectrum_id"]: r for r in results}
    assert by_id[1]["similarity"] > by_id[2]["similarity"]
    assert "window_scores" in by_id[1] and len(by_id[1]["window_scores"]) > 0


def test_dataset_cache_search_not_loaded_returns_empty(wn_grid, synthetic_lta_spectrum):
    cache = sim_module.dataset_matrix_cache
    assert cache.loaded is False
    results = cache.search(wn_grid, synthetic_lta_spectrum, method="pearson")
    assert results == []


def test_dataset_cache_search_respects_min_similarity(wn_grid, synthetic_lta_spectrum):
    rng = np.random.RandomState(0)
    rows = [
        make_spectrum_row(wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)), 1, "S001", "LTA"),
        make_spectrum_row(wn_grid, 0.5 + rng.normal(0, 0.3, len(wn_grid)), 2, "S002", "RANDOM"),
    ]
    _load_fake_cache(rows)
    cache = sim_module.dataset_matrix_cache

    results = cache.search(wn_grid, synthetic_lta_spectrum, method="pearson", min_similarity=0.9, top_n=10)
    assert all(r["similarity"] >= 0.9 for r in results)


def test_dataset_cache_search_family_filter(wn_grid, synthetic_lta_spectrum):
    rng = np.random.RandomState(0)
    rows = [
        make_spectrum_row(wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)), 1, "S001", "LTA"),
        make_spectrum_row(wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)), 2, "S002", "FAU"),
    ]
    _load_fake_cache(rows)
    cache = sim_module.dataset_matrix_cache

    results = cache.search(wn_grid, synthetic_lta_spectrum, method="pearson", min_similarity=0.0,
                            top_n=10, family_filter="FAU")
    assert len(results) == 1
    assert results[0]["zeolite_name"] == "FAU"


# ---------------------------------------------------------------------------
# Endpoint /search unificado
# ---------------------------------------------------------------------------

def test_search_endpoint_user_spectra_no_cache_no_503(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    """Sin caché cargado pero con espectros de usuario disponibles: debe devolver
    resultados de usuario sin lanzar 503 (regresión de la unificación de pipeline)."""
    rng = np.random.RandomState(0)
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.005, len(wn_grid)), "q.txt")
    similar = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)), "sim.txt")
    noise = make_user_spectrum(test_user.id, wn_grid, 0.5 + rng.normal(0, 0.3, len(wn_grid)), "noise.txt", material="RANDOM")
    db_session.add_all([query, similar, noise])
    db_session.commit()
    db_session.refresh(query)

    request = SimilaritySearchRequest(query_spectrum_id=query.id, config=SimilarityConfig(method="pearson", top_n=10))
    result = sim_module.search_similarity(request, db=db_session, current_user=test_user)

    assert result["success"] is True
    data = result["data"]
    assert data["user_results"] == 2
    assert data["dataset_results"] == 0
    scores = {r["filename"]: r["global_score"] for r in data["results"]}
    assert scores["sim.txt"] > scores["noise.txt"]
    assert all(0.0 <= s <= 1.0 for s in scores.values())
    assert all(len(r["window_scores"]) > 0 for r in data["results"])


def test_search_endpoint_no_cache_no_user_spectra_returns_503(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    """Sin caché y sin espectros de usuario: 503 + Retry-After, NUNCA la antigua
    ruta de respaldo que comparaba por índice de array."""
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "q.txt")
    db_session.add(query)
    db_session.commit()
    db_session.refresh(query)

    request = SimilaritySearchRequest(query_spectrum_id=query.id, config=SimilarityConfig(method="pearson", top_n=10))

    with pytest.raises(HTTPException) as exc_info:
        sim_module.search_similarity(request, db=db_session, current_user=test_user)

    assert exc_info.value.status_code == 503
    assert exc_info.value.headers.get("Retry-After") == "5"


def test_search_endpoint_combines_user_and_dataset_sources(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    rng = np.random.RandomState(0)
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.005, len(wn_grid)), "q.txt")
    similar_user = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)), "sim.txt")
    db_session.add_all([query, similar_user])
    db_session.commit()
    db_session.refresh(query)

    rows = [make_spectrum_row(wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)), 101, "S101", "LTA")]
    _load_fake_cache(rows)

    request = SimilaritySearchRequest(query_spectrum_id=query.id, config=SimilarityConfig(method="pearson", top_n=10))
    result = sim_module.search_similarity(request, db=db_session, current_user=test_user)

    data = result["data"]
    assert data["user_results"] >= 1
    assert data["dataset_results"] >= 1
    scores = [r["global_score"] for r in data["results"]]
    assert scores == sorted(scores, reverse=True), "los resultados deben venir ordenados por score descendente"
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_search_endpoint_query_not_found_raises_404(db_session, test_user):
    request = SimilaritySearchRequest(query_spectrum_id=99999, config=SimilarityConfig(method="pearson"))
    with pytest.raises(HTTPException) as exc_info:
        sim_module.search_similarity(request, db=db_session, current_user=test_user)
    assert exc_info.value.status_code == 404


def test_search_endpoint_dataset_results_include_framework_code(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    """Regresión 2026-08-10: el frontend necesita el código IZA (framework_code)
    para enlazar cada resultado con GET /api/zeolites/{code}/structure — el
    campo 'family' por sí solo no basta (p.ej. 'Mordenita', 'Sodalita' no
    incluyen el código entre paréntesis)."""
    rng = np.random.RandomState(0)
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "q.txt")
    db_session.add(query)
    db_session.commit()
    db_session.refresh(query)

    row = make_spectrum_row(wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)),
                             101, "S101", "Mordenita", structure_type="MOR")
    processed = sim_module.DatasetMatrixCache._process_row(row)
    assert processed[1]["framework_code"] == "MOR"

    mat = np.array([processed[0]], dtype=np.float32)
    cache = sim_module.dataset_matrix_cache
    cache.matrix = mat
    cache.norms = np.linalg.norm(mat, axis=1)
    cache.stds = np.std(mat, axis=1)
    cache.mat_centered = (mat - np.mean(mat, axis=1, keepdims=True)).astype(np.float32)
    cache.metadata = [processed[1]]
    cache.loaded = True
    cache.total_loaded = 1

    request = SimilaritySearchRequest(query_spectrum_id=query.id, config=SimilarityConfig(method="pearson", min_similarity=0.0))
    result = sim_module.search_similarity(request, db=db_session, current_user=test_user)

    dataset_result = next(r for r in result["data"]["results"] if r["source"] == "zeolite_dataset")
    assert dataset_result["framework_code"] == "MOR"
    assert dataset_result["family"] == "Mordenita"  # confirma que 'family' seguía sin el código
