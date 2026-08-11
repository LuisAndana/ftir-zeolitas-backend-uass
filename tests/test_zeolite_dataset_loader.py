"""
Tests de regresión para la generación paramétrica de bandas por familia
(app/services/zeolite_dataset_loader.py, 2026-08-09).

Protegen la corrección científica central: ANTES, CHARACTERISTIC_PEAKS era un
único diccionario de 8 picos aplicado a las 44 familias sin distinción — dos
espectros de familias distintas eran estadísticamente indistinguibles salvo
ruido. Estos tests verifican que generate_family_bands() sí discrimina entre
familias y respeta las tendencias físicas conocidas (Flanigen-Khatami-Szymanski).
"""
import numpy as np
import pytest

from app.services.zeolite_dataset_loader import ZeoliteDatasetLoader


# ---------------------------------------------------------------------------
# ring_band_for_framework
# ---------------------------------------------------------------------------

def test_ring_band_verified_values():
    """LTA y FAU tienen bandas verificadas contra literatura (ver docstring del
    módulo): LTA (D4R) ~592 cm-1, FAU (D6R) ~555 cm-1."""
    assert ZeoliteDatasetLoader.ring_band_for_framework("LTA") == 592.0
    assert ZeoliteDatasetLoader.ring_band_for_framework("FAU") == 555.0


def test_ring_band_different_frameworks_give_different_bands():
    """Regresión directa del problema central: ANTES todos los frameworks caían
    en 600 cm-1 fijo. Ahora deben distinguirse entre sí."""
    frameworks = ["LTA", "FAU", "MFI", "MOR", "CHA", "BEA", "FER", "HEU", "GIS", "SOD"]
    bands = {fw: ZeoliteDatasetLoader.ring_band_for_framework(fw) for fw in frameworks}
    assert len(set(bands.values())) > 1, f"todas las bandas son iguales: {bands}"
    # LTA y FAU deben ser distintos entre sí (valores verificados)
    assert bands["LTA"] != bands["FAU"]


def test_ring_band_within_iza_range():
    """Toda banda de anillo doble debe caer en el rango IZA 500-650 cm-1
    ('double ring vibrations', iza-online.org)."""
    frameworks = ["LTA", "FAU", "MFI", "MOR", "CHA", "BEA", "FER", "HEU", "GIS",
                  "SOD", "OFF", "MER", "NAT", "STI", "ERI", "MWW", "TON", "MTT",
                  "AFI", "AEI", "ATN", "LTL", "MEL", "LAU", "HAR", "BRE"]
    for fw in frameworks:
        band = ZeoliteDatasetLoader.ring_band_for_framework(fw)
        assert 500.0 <= band <= 650.0, f"{fw}: {band} fuera de rango IZA [500,650]"


def test_ring_band_is_deterministic():
    """El mismo framework debe dar siempre la misma banda (reproducibilidad)."""
    a = ZeoliteDatasetLoader.ring_band_for_framework("MFI")
    b = ZeoliteDatasetLoader.ring_band_for_framework("MFI")
    assert a == b


# ---------------------------------------------------------------------------
# asymmetric_stretch_cm1 — desplazamiento con Si/Al
# ---------------------------------------------------------------------------

def test_asymmetric_stretch_increases_with_si_al_ratio():
    """'Clear-cut linear relationships... between the frequency of νasym...
    and the atom fraction of Al' (IZA) — a MAYOR Si/Al (MENOS Al), la banda se
    desplaza a MAYOR número de onda."""
    low = ZeoliteDatasetLoader.asymmetric_stretch_cm1(1.0)
    mid = ZeoliteDatasetLoader.asymmetric_stretch_cm1(15.0)
    high = ZeoliteDatasetLoader.asymmetric_stretch_cm1(100.0)
    assert low < mid < high


def test_asymmetric_stretch_within_iza_range():
    """Rango IZA verificado: 'internal tetrahedra asymmetrical stretch 1250-920 cm-1'."""
    for ratio in [1.0, 2.0, 5.0, 15.0, 50.0, 100.0, 500.0]:
        band = ZeoliteDatasetLoader.asymmetric_stretch_cm1(ratio)
        assert 920.0 <= band <= 1250.0, f"Si/Al={ratio}: {band} fuera de rango IZA"


def test_asymmetric_stretch_clamps_below_one():
    """Si/Al < 1 no tiene sentido físico (no puede haber más Al que Si en un
    framework aluminosilicato estable, regla de Löwenstein) — debe acotarse."""
    a = ZeoliteDatasetLoader.asymmetric_stretch_cm1(0.1)
    b = ZeoliteDatasetLoader.asymmetric_stretch_cm1(1.0)
    assert a == b


# ---------------------------------------------------------------------------
# pore_opening_cm1
# ---------------------------------------------------------------------------

def test_pore_opening_within_iza_range():
    """Rango IZA: 'pore opening vibrations 420-300 cm-1'."""
    for pore in [2.0, 4.0, 7.4, 13.0, 20.0]:
        band = ZeoliteDatasetLoader.pore_opening_cm1(pore)
        assert 300.0 <= band <= 420.0


def test_pore_opening_decreases_with_pore_size():
    small = ZeoliteDatasetLoader.pore_opening_cm1(3.0)
    large = ZeoliteDatasetLoader.pore_opening_cm1(15.0)
    assert large < small


# ---------------------------------------------------------------------------
# generate_family_bands — discriminación entre familias
# ---------------------------------------------------------------------------

def test_generate_family_bands_lta_vs_fau_differ():
    """Dos familias con Si/Al y bandas de anillo distintas deben producir
    conjuntos de bandas distintos (la regresión central de esta sesión)."""
    lta_bands = ZeoliteDatasetLoader.generate_family_bands("LTA", si_al_ratio=1.0, pore_max=4.0)
    fau_bands = ZeoliteDatasetLoader.generate_family_bands("FAU", si_al_ratio=1.23, pore_max=7.4)

    lta_ring = lta_bands["Anillos dobles (D4R/D6R)"][0]
    fau_ring = fau_bands["Anillos dobles (D4R/D6R)"][0]
    assert lta_ring != fau_ring
    assert lta_ring == 592.0
    assert fau_ring == 555.0


def test_generate_family_bands_si_al_shifts_asymmetric_band():
    low_si_al = ZeoliteDatasetLoader.generate_family_bands("MFI", si_al_ratio=1.0, pore_max=5.5)
    high_si_al = ZeoliteDatasetLoader.generate_family_bands("MFI", si_al_ratio=100.0, pore_max=5.5)
    assert low_si_al["Asym. stretch T-O (interno)"][0] < high_si_al["Asym. stretch T-O (interno)"][0]


def test_generate_family_bands_amorphous_mesoporous_has_no_ring_band():
    """Sílices mesoporosas amorfas (MCM-41, SBA-15...) no tienen cristalinidad
    de largo alcance — no deben mostrar una banda de anillo D4R/D6R ficticia."""
    bands = ZeoliteDatasetLoader.generate_family_bands("MCM41", si_al_ratio=5.0, pore_max=100.0)
    assert "Anillos dobles (D4R/D6R)" not in bands
    assert any("amorfa" in name.lower() for name in bands)


@pytest.mark.parametrize("code", sorted(ZeoliteDatasetLoader.AMORPHOUS_MESOPOROUS_CODES))
def test_all_amorphous_codes_use_amorphous_profile(code):
    bands = ZeoliteDatasetLoader.generate_family_bands(code, si_al_ratio=5.0, pore_max=100.0)
    assert "Anillos dobles (D4R/D6R)" not in bands


def test_generate_family_bands_crystalline_has_seven_bands():
    bands = ZeoliteDatasetLoader.generate_family_bands("CHA", si_al_ratio=1.5, pore_max=3.8)
    assert len(bands) == 7
    assert "Anillos dobles (D4R/D6R)" in bands
    assert "Asym. stretch T-O (interno)" in bands


# ---------------------------------------------------------------------------
# generate_spectrum_data — end-to-end: dos familias producen espectros distintos
# ---------------------------------------------------------------------------

def test_generate_spectrum_data_lta_vs_random_noise_family_are_distinguishable():
    """El test de fuego: dos espectros generados para familias distintas ya NO
    deben ser estadísticamente indistinguibles (el problema original)."""
    import json

    loader = ZeoliteDatasetLoader.__new__(ZeoliteDatasetLoader)  # sin conexión a BD
    np.random.seed(0)
    lta_json = loader.generate_spectrum_data(structure_type="LTA", si_al_ratio=1.0, pore_max=4.0, points=1801)
    np.random.seed(1)
    fau_json = loader.generate_spectrum_data(structure_type="FAU", si_al_ratio=1.23, pore_max=7.4, points=1801)

    lta_data = json.loads(lta_json)
    fau_data = json.loads(fau_json)
    lta_intensities = np.array(lta_data["intensities"])
    fau_intensities = np.array(fau_data["intensities"])
    wavenumbers = np.array(lta_data["wavenumbers"])

    # La banda de anillo de LTA (592) debe tener más intensidad relativa ahí
    # que el espectro de FAU (cuya banda de anillo está en 555, no en 592).
    idx_592 = np.argmin(np.abs(wavenumbers - 592))
    idx_555 = np.argmin(np.abs(wavenumbers - 555))
    # LTA tiene pico propio en 592; FAU no (su pico está en 555) -> LTA[592] > FAU[592]
    assert lta_intensities[idx_592] > fau_intensities[idx_592]
    # FAU tiene pico propio en 555; LTA no -> FAU[555] > LTA[555]
    assert fau_intensities[idx_555] > lta_intensities[idx_555]
