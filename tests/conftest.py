"""
Fixtures compartidas de pytest.

IMPORTANTE: las variables de entorno deben fijarse ANTES de importar cualquier
módulo de `app` — Settings() se instancia a nivel de módulo en app/core/config.py.
"""
import os

os.environ.setdefault("DB_PASSWORD", "test_only_not_a_real_password")
os.environ.setdefault("SECRET_KEY", "test_only_secret_key_1234567890_min_32_chars")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEBUG", "False")

import json

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.user import User
from app.models.spectrum import Spectrum


@pytest.fixture()
def db_session():
    """Sesión SQLAlchemy sobre SQLite en memoria con el esquema real de la app."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def test_user(db_session):
    user = User(
        email="test@example.com",
        password_hash="x",
        name="Test User",
        role="investigador",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def wn_grid():
    """Rejilla de números de onda 400-4000 cm⁻¹, 1801 puntos (igual a FIXED_GRID)."""
    return np.linspace(400, 4000, 1801)


@pytest.fixture()
def synthetic_lta_spectrum(wn_grid):
    """
    Espectro FTIR sintético con picos en posiciones realistas de zeolita LTA:
    anillos dobles D4R (~550), estiramiento asimétrico T-O (~1000), banda O-H
    (~3600) y H2O adsorbida (~1640) — cubre región estructural y no estructural.
    """
    peak_asym = 0.6 * np.exp(-((wn_grid - 1000) ** 2) / (2 * 40 ** 2))
    peak_d4r = 0.4 * np.exp(-((wn_grid - 550) ** 2) / (2 * 20 ** 2))
    oh_band = 0.5 * np.exp(-((wn_grid - 3600) ** 2) / (2 * 80 ** 2))
    h2o_band = 0.3 * np.exp(-((wn_grid - 1640) ** 2) / (2 * 30 ** 2))
    return 0.3 + peak_asym + peak_d4r + oh_band + h2o_band


def make_spectrum_row(wn, ab, spectrum_id=1, sample_code="S001", zeolite_name="LTA",
                       equipment="TestEquip", structure_type="LTA"):
    """Fila cruda tal como la devolvería el cursor de mysql.connector para ftir_spectra
    (JOIN con zeolite_types) — el 7mo elemento es zt.structure_type (código IZA)."""
    return (
        spectrum_id,
        json.dumps({"wavenumbers": wn.tolist(), "intensities": ab.tolist()}),
        sample_code, zeolite_name, equipment, None, structure_type,
    )


def make_user_spectrum(user_id, wn, ab, filename, material="LTA", technique="ATR"):
    """Instancia de app.models.spectrum.Spectrum (no persistida) con datos sintéticos."""
    return Spectrum(
        user_id=user_id, filename=filename, material=material, technique=technique,
        wavenumber_data=json.dumps({"wavenumbers": wn.tolist(), "absorbance": ab.tolist()}),
    )
