"""
Tests para el parser de archivos de espectro (app/routes/spectra.py:
parse_spectrum_file) — JCAMP-DX, CSV/TSV, y el formato original de texto plano.
"""
import pytest

from app.routes.spectra import parse_spectrum_file


# ---------------------------------------------------------------------------
# Texto plano de dos columnas (formato original — nunca debe romperse)
# ---------------------------------------------------------------------------

def test_whitespace_columns_still_works():
    content = b"400.0 0.10\n500.0 0.25\n600.0 0.40\n"
    result = parse_spectrum_file(content, "spectrum.txt")
    assert result["wavenumbers"] == [400.0, 500.0, 600.0]
    assert result["absorbance"] == [0.10, 0.25, 0.40]


def test_whitespace_columns_skips_comments_and_blank_lines():
    content = b"# comentario\n\n400.0 0.10\n# otro comentario\n500.0 0.25\n"
    result = parse_spectrum_file(content, "spectrum.txt")
    assert result["wavenumbers"] == [400.0, 500.0]


def test_empty_file_raises_value_error():
    with pytest.raises(ValueError):
        parse_spectrum_file(b"", "spectrum.txt")


def test_garbage_content_raises_value_error():
    with pytest.raises(ValueError):
        parse_spectrum_file(b"esto no tiene ningun numero valido\nni esta linea tampoco\n", "spectrum.txt")


# ---------------------------------------------------------------------------
# CSV / TSV
# ---------------------------------------------------------------------------

def test_csv_comma_delimited():
    content = b"wavenumber,absorbance\n400.0,0.10\n500.0,0.25\n600.0,0.40\n"
    result = parse_spectrum_file(content, "spectrum.csv")
    assert result["wavenumbers"] == [400.0, 500.0, 600.0]
    assert result["absorbance"] == [0.10, 0.25, 0.40]


def test_csv_semicolon_delimited_with_decimal_comma():
    """CSV europeo: ';' como delimitador, ',' como separador decimal."""
    content = "wavenumber;absorbance\n400,5;0,10\n500,0;0,25\n".encode("utf-8")
    result = parse_spectrum_file(content, "spectrum.csv")
    assert result["wavenumbers"] == [400.5, 500.0]
    assert result["absorbance"] == [0.10, 0.25]


def test_tsv_tab_delimited():
    content = b"400.0\t0.10\n500.0\t0.25\n"
    result = parse_spectrum_file(content, "spectrum.tsv")
    assert result["wavenumbers"] == [400.0, 500.0]


def test_csv_sniffed_without_csv_extension():
    """Aunque el archivo se suba con extensión .txt, si el contenido tiene
    comas debe detectarse como delimitado, no fallar como texto plano."""
    content = b"400.0,0.10\n500.0,0.25\n600.0,0.40\n"
    result = parse_spectrum_file(content, "espectro_exportado.txt")
    assert result["wavenumbers"] == [400.0, 500.0, 600.0]


def test_csv_no_valid_numeric_data_raises():
    with pytest.raises(ValueError):
        parse_spectrum_file(b"col1,col2\nfoo,bar\nbaz,qux\n", "spectrum.csv")


# ---------------------------------------------------------------------------
# JCAMP-DX
# ---------------------------------------------------------------------------

JCAMP_XY_COMPRESSED = b"""##TITLE=Test Zeolite Spectrum
##JCAMP-DX=5.01
##DATA TYPE=INFRARED SPECTRUM
##XUNITS=1/CM
##YUNITS=ABSORBANCE
##FIRSTX=400.0
##LASTX=410.0
##NPOINTS=6
##DELTAX=2.0
##XFACTOR=1.0
##YFACTOR=0.001
##XYDATA=(X++(Y..Y))
400.0 100 150 200 250 300
410.0 350
##END=
"""

JCAMP_TRANSMITTANCE_PERCENT = b"""##TITLE=Test Transmittance Spectrum
##JCAMP-DX=5.01
##DATA TYPE=INFRARED SPECTRUM
##XUNITS=1/CM
##YUNITS=TRANSMITTANCE
##FIRSTX=400.0
##LASTX=402.0
##NPOINTS=2
##DELTAX=2.0
##XFACTOR=1.0
##YFACTOR=1.0
##XYDATA=(X++(Y..Y))
400.0 50 100
##END=
"""


def test_jcamp_dx_by_extension():
    result = parse_spectrum_file(JCAMP_XY_COMPRESSED, "spectrum.jdx")
    assert result["wavenumbers"] == [400.0, 402.0, 404.0, 406.0, 408.0, 410.0]
    assert result["absorbance"] == pytest.approx([0.1, 0.15, 0.2, 0.25, 0.3, 0.35])


def test_jcamp_dx_detected_without_extension():
    """Aunque se suba como .txt, el contenido '##...' debe detectarse como JCAMP-DX."""
    result = parse_spectrum_file(JCAMP_XY_COMPRESSED, "spectrum.txt")
    assert len(result["wavenumbers"]) == 6


def test_jcamp_dx_transmittance_converted_to_absorbance():
    """A = -log10(T). %T=50 -> A=-log10(0.5)=0.301; %T=100 -> A=-log10(1.0)=0.0."""
    result = parse_spectrum_file(JCAMP_TRANSMITTANCE_PERCENT, "spectrum.jdx")
    assert result["absorbance"][0] == pytest.approx(0.30103, abs=1e-4)
    assert result["absorbance"][1] == pytest.approx(0.0, abs=1e-6)


def test_jcamp_dx_malformed_raises_value_error():
    with pytest.raises(ValueError):
        parse_spectrum_file(b"##TITLE=broken\n##NOT A VALID JCAMP FILE AT ALL\n", "spectrum.jdx")
