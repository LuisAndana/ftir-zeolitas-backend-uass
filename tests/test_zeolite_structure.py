"""
Tests para el catálogo de familias (seed_data.py) y el endpoint
GET /api/zeolites/{code}/structure (Fase 0-1 del visor 3D banda↔estructura).
"""
import sys

import pytest
from fastapi import HTTPException

import seed_data
from app.models.zeolite_family import ZeoliteFamily
from app.routes import zeolites as zeolites_module
from app.schemas.zeolite import ZeoliteFamilyResponse


# ---------------------------------------------------------------------------
# CIF reales descargados de la IZA Structure Database (2026-08-09/10, via el
# proyecto separado C:\Users\luis_\iza-cif-downloader\descargar_iza.py)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("code", [
    "LTA", "FAU", "MFI", "MOR", "CHA", "FER", "HEU", "GIS", "SOD",
    "AEI", "ATN", "EAB", "MER", "NAT", "GON", "LAU", "BRE", "STI",
    "MEL", "MTT", "TON", "AFI", "LTL", "MWW", "ERI",
])
def test_downloaded_cif_exists_and_is_valid(code):
    """Protege los CIF reales descargados de europe.iza-structure.org
    (download_cif.php?ID=...) para los códigos de framework IZA "directos"
    (donde el código de catálogo coincide con el nombre real del framework)
    — deben seguir presentes, con el data_ tag correcto y los campos mínimos
    de un CIF de la IZA-SC Database."""
    cif_path = zeolites_module.CIF_STRUCTURES_DIR / f"{code}.cif"
    assert cif_path.is_file(), f"falta {cif_path}"
    content = cif_path.read_text(encoding="utf-8")
    assert content.startswith(f"data_{code}")
    assert "IZA-SC Database of Zeolite Structures" in content
    assert "_cell_length_a" in content
    assert "_symmetry_space_group_name_H-M" in content
    assert "_atom_site_fract_x" in content
    assert "T1" in content  # al menos un sitio T (Si/Al) presente


@pytest.mark.parametrize("code,expected_data_tag", [
    # BEA no tiene CIF idealizado propio (es un intercrecimiento de
    # polimorfos, ver DO_structures/DO_family.php?ID=1 en la IZA) — se usa
    # el polimorfo mayoritario Beta_A como representación 3D razonable.
    ("BEA", "data_Beta_A"),
    # LEO/HAR/NU10 no son códigos de framework IZA independientes (ver
    # confidence_note de cada uno en seed_data.py) — reutilizan el CIF del
    # framework real del que son alias (LAU/PHI/TON respectivamente).
    ("LEO", "data_LAU"),
    ("HAR", "data_PHI"),
    ("NU10", "data_TON"),
])
def test_aliased_cif_exists_and_is_valid(code, expected_data_tag):
    """Protege los 4 CIF "alias" (mismo archivo físico que otro framework,
    ver static/structures/README.md) — deben seguir presentes y apuntar al
    framework real correcto, no al código de catálogo literal."""
    cif_path = zeolites_module.CIF_STRUCTURES_DIR / f"{code}.cif"
    assert cif_path.is_file(), f"falta {cif_path}"
    content = cif_path.read_text(encoding="utf-8")
    assert content.startswith(expected_data_tag)
    assert "_cell_length_a" in content
    # BEA (Beta_A) viene de la base de datos de estructuras desordenadas, que
    # etiqueta los sitios T como SI<n> en vez de T<n> — no aplicar el mismo
    # chequeo de "T1" que los CIF de framework ordenado.
    if code != "BEA":
        assert "T1" in content


@pytest.mark.parametrize("code", ["NU86", "MCM41", "SBA15", "FDU12", "HMS", "KIT6"])
def test_amorphous_or_unassigned_codes_have_no_cif(code):
    """Estos 6 códigos NUNCA deben tener .cif: 5 son sílices mesoporosas
    amorfas (sin cristalinidad de largo alcance, no hay estructura que
    descargar) y NU-86 no tiene código de framework IZA asignado (confirmado
    en patentes ICI/IFP, ver seed_data.py). Si algún día alguno aparece con
    .cif en disco, revisar por qué antes de asumir que es una mejora."""
    cif_path = zeolites_module.CIF_STRUCTURES_DIR / f"{code}.cif"
    assert not cif_path.is_file(), (
        f"{cif_path} existe pero {code} no debería tener CIF real — "
        "revisar antes de continuar, puede ser una descarga incorrecta"
    )


def test_get_structure_serves_real_cif_for_lta(db_session):
    """End-to-end: el endpoint debe servir el CIF real descargado, no un mock."""
    seed_data.seed(db_session)
    result = zeolites_module.get_zeolite_structure(code="LTA", format="json", db=db_session)
    assert result.data["cif_available"] is True
    assert "data_LTA" in result.data["cif_content"]
    assert "11.9190" in result.data["cif_content"]  # cell_length_a de la IZA


# ---------------------------------------------------------------------------
# seed_data.seed()
# ---------------------------------------------------------------------------

def test_seed_inserts_all_families(db_session):
    inserted = seed_data.seed(db_session)
    assert inserted == len(seed_data.FAMILIES)

    codes = {f.code for f in db_session.query(ZeoliteFamily).all()}
    expected_codes = {f[0] for f in seed_data.FAMILIES}
    assert codes == expected_codes


def test_seed_is_idempotent(db_session):
    seed_data.seed(db_session)
    second_run = seed_data.seed(db_session)
    assert second_run == 0
    assert db_session.query(ZeoliteFamily).count() == len(seed_data.FAMILIES)


def test_seed_lta_fau_have_distinct_typical_bands(db_session):
    """Regresión directa: el catálogo debe reflejar bandas distintas por
    familia, no un valor genérico repetido."""
    seed_data.seed(db_session)
    lta = db_session.query(ZeoliteFamily).filter(ZeoliteFamily.code == "LTA").first()
    fau = db_session.query(ZeoliteFamily).filter(ZeoliteFamily.code == "FAU").first()
    assert lta.typical_bands != fau.typical_bands
    assert 592.0 in lta.typical_bands
    assert 555.0 in fau.typical_bands


def test_seed_families_validate_against_response_schema(db_session):
    """Regresión del bug original: ZeoliteFamilyResponse exigía columnas que el
    modelo no tenía -> ValidationError en cuanto hubiera filas. Debe validar limpio."""
    seed_data.seed(db_session)
    families = db_session.query(ZeoliteFamily).all()
    assert len(families) > 0
    for family in families:
        # No debe lanzar ValidationError
        response = ZeoliteFamilyResponse.model_validate(family)
        assert response.code == family.code


def test_seed_data_fields_fit_column_limits(db_session):
    """Regresión 2026-08-10: MFI tenía channel_dimensionality='3D (canales
    rectos+sinusoidales)' (32 chars) contra VARCHAR(20) — SQLite (usado en
    tests) no valida longitud de VARCHAR y dejó pasar el bug en silencio; solo
    se manifestó como DataError 1406 contra MySQL real. Verificar longitudes
    explícitamente aquí para que este tipo de bug no vuelva a pasar los tests
    y solo se descubra contra una base de datos real."""
    column_limits = {
        "code": 50, "name": 255, "category": 100, "chemical_formula": 255,
        "si_al_ratio": 50, "pore_size": 100, "ring_size": 50,
        "channel_dimensionality": 20, "description": 512,
    }
    for code, name, category, formula, si_al_ratio, pore_size, ring_size, channel_dim, _, _, description in seed_data.FAMILIES:
        values = {
            "code": code, "name": name, "category": category, "chemical_formula": formula,
            "si_al_ratio": si_al_ratio, "pore_size": pore_size, "ring_size": ring_size,
            "channel_dimensionality": channel_dim, "description": description,
        }
        for field, value in values.items():
            limit = column_limits[field]
            assert len(value) <= limit, (
                f"{code}.{field} tiene {len(value)} caracteres, excede VARCHAR({limit}): {value!r}"
            )


# ---------------------------------------------------------------------------
# GET /{code}/structure
# ---------------------------------------------------------------------------

def test_get_structure_returns_metadata_without_cif(db_session):
    """NU86 nunca tendrá .cif: la IZA no le asigna código de framework propio
    (confirmado en patentes ICI/IFP, ver seed_data.py) — permanentemente sin
    CIF, a diferencia de las 29/35 familias que sí tienen .cif en
    static/structures/. Por ser permanente, cif_source_hint debe ser None
    (no tiene sentido enlazar a la IZA a buscar algo que no existe) y en su
    lugar debe traer cif_unavailable_reason con la explicación."""
    seed_data.seed(db_session)
    result = zeolites_module.get_zeolite_structure(code="NU86", format="json", db=db_session)

    assert result.success is True
    data = result.data
    assert data["code"] == "NU86"
    assert data["cif_available"] is False
    assert data["cif_content"] is None
    assert data["cif_permanently_unavailable"] is True
    assert data["cif_unavailable_reason"] is not None
    assert "IZA" in data["cif_unavailable_reason"]
    assert data["cif_source_hint"] is None
    assert isinstance(data["typical_bands"], list) and len(data["typical_bands"]) > 0


def test_get_structure_amorphous_codes_are_permanently_unavailable(db_session):
    """Las 5 sílices mesoporosas amorfas nunca tendrán CIF (sin cristalinidad
    de largo alcance) — mismo contrato que NU86."""
    seed_data.seed(db_session)
    for code in ("MCM41", "SBA15", "FDU12", "HMS", "KIT6"):
        result = zeolites_module.get_zeolite_structure(code=code, format="json", db=db_session)
        data = result.data
        assert data["cif_available"] is False, code
        assert data["cif_permanently_unavailable"] is True, code
        assert "amorfa" in data["cif_unavailable_reason"].lower(), code
        assert data["cif_source_hint"] is None, code


def test_get_structure_lowercase_code_normalizes_to_upper(db_session):
    seed_data.seed(db_session)
    result = zeolites_module.get_zeolite_structure(code="lta", format="json", db=db_session)
    assert result.data["code"] == "LTA"


def test_get_structure_unknown_code_raises_404(db_session):
    seed_data.seed(db_session)
    with pytest.raises(HTTPException) as exc_info:
        zeolites_module.get_zeolite_structure(code="ZZZ", format="json", db=db_session)
    assert exc_info.value.status_code == 404


def test_get_structure_cif_format_404_with_instructions_when_missing(db_session):
    seed_data.seed(db_session)
    with pytest.raises(HTTPException) as exc_info:
        zeolites_module.get_zeolite_structure(code="NU86", format="cif", db=db_session)
    assert exc_info.value.status_code == 404
    assert "static/structures" in exc_info.value.detail


def test_get_structure_reads_cif_when_present(db_session, tmp_path, monkeypatch):
    """Si el .cif existe en el directorio esperado, debe leerse y devolverse."""
    seed_data.seed(db_session)
    fake_cif = "data_LTA\n_cell_length_a 11.919\n"
    (tmp_path / "LTA.cif").write_text(fake_cif, encoding="utf-8")
    monkeypatch.setattr(zeolites_module, "CIF_STRUCTURES_DIR", tmp_path)

    result = zeolites_module.get_zeolite_structure(code="LTA", format="json", db=db_session)
    assert result.data["cif_available"] is True
    assert result.data["cif_content"] == fake_cif

    cif_response = zeolites_module.get_zeolite_structure(code="LTA", format="cif", db=db_session)
    assert cif_response.body.decode("utf-8") == fake_cif
    assert cif_response.media_type == "chemical/x-cif"


def test_get_categories_endpoint_works_after_func_fix(db_session):
    """Regresión del bug db.func.count (AttributeError, Session no tiene .func)."""
    seed_data.seed(db_session)
    result = zeolites_module.get_statistics(db=db_session)
    assert result.success is True
    assert result.data["total_families"] == len(seed_data.FAMILIES)
    assert result.data["total_categories"] > 0
