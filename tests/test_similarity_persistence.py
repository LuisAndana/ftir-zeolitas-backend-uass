"""
Tests para la persistencia de búsquedas en SimilarityResult (antes código
muerto: el modelo existía pero ninguna ruta lo instanciaba).
"""
import json

import numpy as np
import pytest

from app.models.similarity_result import SimilarityResult
from app.routes import similarity as sim_module
from app.schemas.similarity import SimilaritySearchRequest, SimilarityConfig
from app.services.spectral_preprocessing import ALGORITHM_VERSION
from tests.conftest import make_spectrum_row, make_user_spectrum


@pytest.fixture(autouse=True)
def reset_dataset_cache():
    cache = sim_module.dataset_matrix_cache
    cache.loaded = False
    cache.matrix = None
    yield
    cache.loaded = False
    cache.matrix = None


def test_search_persists_similarity_result(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    rng = np.random.RandomState(0)
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.005, len(wn_grid)), "q.txt")
    similar = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum + rng.normal(0, 0.01, len(wn_grid)), "sim.txt")
    db_session.add_all([query, similar])
    db_session.commit()
    db_session.refresh(query)

    assert db_session.query(SimilarityResult).count() == 0

    request = SimilaritySearchRequest(
        query_spectrum_id=query.id,
        config=SimilarityConfig(method="pearson", top_n=10, min_similarity=0.3),
    )
    sim_module.search_similarity(request, db=db_session, current_user=test_user)

    saved = db_session.query(SimilarityResult).all()
    assert len(saved) == 1
    row = saved[0]
    assert row.user_id == test_user.id
    assert row.query_spectrum_id == query.id
    assert row.search_method == "pearson"
    assert row.min_similarity == 0.3
    assert row.algorithm_version == ALGORITHM_VERSION
    assert row.results_found >= 1
    assert isinstance(row.results, list)
    assert row.results[0]["spectrum_id"] is not None
    assert row.execution_time_ms is not None and row.execution_time_ms >= 0


def test_search_response_includes_algorithm_version(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "q.txt")
    similar = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "sim.txt")
    db_session.add_all([query, similar])
    db_session.commit()
    db_session.refresh(query)

    request = SimilaritySearchRequest(query_spectrum_id=query.id, config=SimilarityConfig(method="pearson"))
    result = sim_module.search_similarity(request, db=db_session, current_user=test_user)

    assert result["data"]["algorithm_version"] == ALGORITHM_VERSION
    assert result["data"]["min_similarity"] == 0.5  # default del schema


def test_min_similarity_configurable_filters_dataset_results(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    """Regresión: min_similarity estaba hardcodeado a 0.5 e ignoraba lo que
    pidiera el cliente. Ahora debe respetarse."""
    rng = np.random.RandomState(0)
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "q.txt")
    db_session.add(query)
    db_session.commit()
    db_session.refresh(query)

    # Dataset: un espectro con correlación baja/moderada
    weak_match = 0.4 + rng.normal(0, 0.15, len(wn_grid))
    rows = [make_spectrum_row(wn_grid, weak_match, 101, "S101", "LTA")]
    processed = sim_module.DatasetMatrixCache._process_row(rows[0])
    mat = np.array([processed[0]], dtype=np.float32)
    cache = sim_module.dataset_matrix_cache
    cache.matrix = mat
    cache.norms = np.linalg.norm(mat, axis=1)
    cache.stds = np.std(mat, axis=1)
    cache.mat_centered = (mat - np.mean(mat, axis=1, keepdims=True)).astype(np.float32)
    cache.metadata = [processed[1]]
    cache.loaded = True
    cache.total_loaded = 1

    # Con min_similarity muy alto, no debería aparecer el resultado del dataset
    request_strict = SimilaritySearchRequest(
        query_spectrum_id=query.id,
        config=SimilarityConfig(method="pearson", min_similarity=0.99),
    )
    result_strict = sim_module.search_similarity(request_strict, db=db_session, current_user=test_user)
    assert result_strict["data"]["dataset_results"] == 0

    # Con min_similarity=0.0, el resultado del dataset debe aparecer
    request_loose = SimilaritySearchRequest(
        query_spectrum_id=query.id,
        config=SimilarityConfig(method="pearson", min_similarity=0.0),
    )
    result_loose = sim_module.search_similarity(request_loose, db=db_session, current_user=test_user)
    assert result_loose["data"]["dataset_results"] == 1


def test_persistence_failure_does_not_break_search(db_session, test_user, wn_grid, synthetic_lta_spectrum, monkeypatch):
    """Si guardar el historial falla, la búsqueda debe seguir devolviendo
    resultados (best-effort, no debe romper la respuesta al usuario)."""
    query = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "q.txt")
    similar = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "sim.txt")
    db_session.add_all([query, similar])
    db_session.commit()
    db_session.refresh(query)

    def broken_add(obj):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(db_session, "add", broken_add)

    request = SimilaritySearchRequest(query_spectrum_id=query.id, config=SimilarityConfig(method="pearson"))
    result = sim_module.search_similarity(request, db=db_session, current_user=test_user)

    assert result["success"] is True
    assert result["data"]["results_found"] >= 1
