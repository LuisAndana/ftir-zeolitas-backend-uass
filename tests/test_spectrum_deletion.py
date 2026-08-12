"""
Tests para DELETE /spectra/{id} — regresión del bug donde borrar un espectro
que ya tenía una búsqueda de similitud guardada (tabla similarity_results)
fallaba con IntegrityError 500 (FK sin ON DELETE definido). Ver migración
f20fcc4f3e94 y app/models/similarity_result.py.
"""
import json

import pytest
from sqlalchemy import text

from app.models.similarity_result import SimilarityResult
from app.routes.spectra import delete_spectrum
from tests.conftest import make_user_spectrum


def _enable_fk_enforcement(db_session):
    """SQLite no aplica FKs por defecto; hay que activarlo por conexión para
    que ON DELETE CASCADE se comporte igual que en MySQL."""
    db_session.execute(text("PRAGMA foreign_keys=ON"))


def test_delete_spectrum_cascades_similarity_results(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    _enable_fk_enforcement(db_session)

    spectrum = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "q.txt")
    db_session.add(spectrum)
    db_session.commit()
    db_session.refresh(spectrum)

    result = SimilarityResult(
        user_id=test_user.id,
        query_spectrum_id=spectrum.id,
        search_method="pearson",
        results=[],
    )
    db_session.add(result)
    db_session.commit()

    assert db_session.query(SimilarityResult).count() == 1

    response = delete_spectrum(spectrum.id, db=db_session, current_user=test_user)

    assert response.success is True
    assert db_session.query(SimilarityResult).count() == 0


def test_delete_spectrum_without_history_still_works(db_session, test_user, wn_grid, synthetic_lta_spectrum):
    _enable_fk_enforcement(db_session)

    spectrum = make_user_spectrum(test_user.id, wn_grid, synthetic_lta_spectrum, "q.txt")
    db_session.add(spectrum)
    db_session.commit()
    db_session.refresh(spectrum)

    response = delete_spectrum(spectrum.id, db=db_session, current_user=test_user)

    assert response.success is True
