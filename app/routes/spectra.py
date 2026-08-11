"""
Rutas para carga y gestión de espectros - CON MANEJO DE ERRORES MEJORADO Y LOGS DE DEBUG
"""

import logging
import json
from fastapi import APIRouter, Depends, File, Form, UploadFile, Query, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.spectrum import Spectrum
from app.schemas.spectrum import SpectrumResponse, SpectrumDetailResponse
from app.schemas.common import SuccessResponse, PaginatedResponse

logger = logging.getLogger(__name__)

# ✅ SIN PREFIX - El prefijo se agrega en main.py
router = APIRouter(tags=["espectros"])


# ========================================
# GET /
# Obtener lista de espectros
# ========================================

@router.get(
    "",
    response_model=PaginatedResponse,
    summary="Obtener lista de espectros"
)
def get_spectra(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtener lista de espectros del usuario autenticado
    Retorna los datos completos incluyendo wavenumbers y absorbance
    """

    logger.info(f"📊 GET /spectra - Usuario: {current_user.id}, skip={skip}, limit={limit}")

    try:
        # ✅ Validar parámetros
        if skip < 0:
            logger.warning(f"⚠️  skip negativo: {skip}")
            skip = 0

        if limit < 1:
            logger.warning(f"⚠️  limit < 1: {limit}")
            limit = 1
        elif limit > 100:
            logger.warning(f"⚠️  limit > 100: {limit}, usando 100")
            limit = 100

        logger.debug(f"🔍 Parámetros validados: skip={skip}, limit={limit}")

        # ✅ Query con mejor manejo
        try:
            query = db.query(Spectrum).filter(Spectrum.user_id == current_user.id)
            logger.debug(f"✅ Query creada para usuario {current_user.id}")
        except SQLAlchemyError as e:
            logger.error(f"❌ Error creando query: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error en base de datos"
            )

        # ✅ Contar total
        try:
            total = query.count()
            logger.debug(f"📈 Total de espectros: {total}")
        except SQLAlchemyError as e:
            logger.error(f"❌ Error contando espectros: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error contando espectros"
            )

        # ✅ Aplicar paginación
        try:
            spectra = query.offset(skip).limit(limit).all()
            logger.debug(f"✅ Espectros obtenidos: {len(spectra)}")
        except SQLAlchemyError as e:
            logger.error(f"❌ Error en paginación: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error en paginación"
            )

        # Calcular página
        page = (skip // limit) + 1 if limit > 0 else 1
        total_pages = (total + limit - 1) // limit if limit > 0 else 1

        logger.info(f"✅ Retornando página {page}/{total_pages} con {len(spectra)} espectros")

        # ✅ Convertir a SpectrumDetailResponse para incluir datos parseados
        spectra_data = []
        for i, spectrum in enumerate(spectra):
            try:
                spectrum_response = SpectrumResponse.model_validate(spectrum)
                spectrum_detail = SpectrumDetailResponse.from_spectrum(spectrum_response)
                spectra_data.append(spectrum_detail.model_dump())
            except Exception as e:
                logger.error(f"❌ Error convirtiendo espectro {i}: {e}", exc_info=True)
                # Continuar con los demás
                continue

        logger.info(f"✅ {len(spectra_data)} espectros convertidos exitosamente")

        return PaginatedResponse(
            success=True,
            data=spectra_data,
            pagination={"skip": skip, "limit": limit, "total": total},
            total=total,
            page=page,
            page_size=limit,
            total_pages=total_pages
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error general obteniendo espectros: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error obteniendo espectros"
        )


# ========================================
# POST /upload
# Cargar nuevo espectro
# ========================================

@router.post(
    "/upload",
    response_model=SuccessResponse,
    summary="Cargar nuevo espectro",
    status_code=status.HTTP_201_CREATED
)
async def upload_spectrum(
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
    material: Optional[str] = Form(None),
    technique: Optional[str] = Form(None),
    hydration_state: Optional[str] = Form(None),
    temperature: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Cargar un nuevo archivo de espectro
    """

    logger.info(f"📤 POST /upload - Usuario: {current_user.id}, Archivo: {file.filename}")

    # ✅ LOGS DE DEBUG PARA VER QUÉ SE RECIBE
    logger.info(f"   📋 Parámetros recibidos:")
    logger.info(f"      - material: '{material}' (tipo: {type(material).__name__})")
    logger.info(f"      - technique: '{technique}' (tipo: {type(technique).__name__})")
    logger.info(f"      - hydration_state: '{hydration_state}' (tipo: {type(hydration_state).__name__})")
    logger.info(f"      - temperature: '{temperature}' (tipo: {type(temperature).__name__})")

    try:
        # Leer contenido del archivo
        content = await file.read()
        logger.debug(f"📄 Archivo leído: {len(content)} bytes")

        # Procesar archivo (parsear datos)
        wavenumber_data = parse_spectrum_file(content, file.filename or "")
        logger.debug(f"✅ Archivo parseado: {len(wavenumber_data.get('wavenumbers', []))} puntos")

        # ✅ DEFINIR VALORES POR DEFECTO
        final_material = material if material and material.strip() else "Desconocido"
        final_technique = technique if technique and technique.strip() else "ATR"
        final_hydration = hydration_state if hydration_state and hydration_state.strip() else "As-synthesized"
        final_temperature = temperature if temperature and temperature.strip() else "25°C"

        # ✅ LOGS DE LOS VALORES FINALES
        logger.info(f"   ✅ Valores finales a guardar:")
        logger.info(f"      - material final: '{final_material}'")
        logger.info(f"      - technique final: '{final_technique}'")
        logger.info(f"      - hydration final: '{final_hydration}'")
        logger.info(f"      - temperature final: '{final_temperature}'")

        # Crear espectro en BD
        spectrum = Spectrum(
            filename=file.filename or "spectrum",
            user_id=current_user.id,
            material=final_material,
            technique=final_technique,
            hydration_state=final_hydration,
            temperature=final_temperature
        )

        # Guardar datos de wavenumber en JSON
        spectrum.wavenumber_data = json.dumps({
            "wavenumbers": wavenumber_data.get("wavenumbers", []),
            "absorbance": wavenumber_data.get("absorbance", [])
        })

        try:
            db.add(spectrum)
            db.commit()
            db.refresh(spectrum)
            logger.info(f"✅ Espectro guardado en BD: ID {spectrum.id}")
            logger.info(f"   Datos guardados:")
            logger.info(f"      - filename: {spectrum.filename}")
            logger.info(f"      - material: {spectrum.material}")
            logger.info(f"      - technique: {spectrum.technique}")
            logger.info(f"      - hydration_state: {spectrum.hydration_state}")
            logger.info(f"      - temperature: {spectrum.temperature}")
        except SQLAlchemyError as e:
            logger.error(f"❌ Error guardando en BD: {e}", exc_info=True)
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error guardando espectro en BD"
            )

        # ✅ Retornar datos completos
        spectrum_response = SpectrumResponse.model_validate(spectrum)
        spectrum_detail = SpectrumDetailResponse.from_spectrum(spectrum_response)

        logger.info(f"✅ Espectro cargado exitosamente")

        return SuccessResponse(
            success=True,
            message="Espectro cargado exitosamente",
            data={
                "spectrum": spectrum_detail.model_dump()
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error cargando espectro: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al cargar espectro"
        )


# ========================================
# GET /{spectrum_id}
# Obtener espectro por ID (con detalles)
# ========================================

@router.get(
    "/{spectrum_id}",
    response_model=SuccessResponse,
    summary="Obtener espectro por ID con detalles"
)
def get_spectrum(
    spectrum_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Obtener un espectro específico con datos completos
    """

    logger.info(f"🔍 GET /spectra/{spectrum_id} - Usuario: {current_user.id}")

    try:
        spectrum = db.query(Spectrum).filter(
            Spectrum.id == spectrum_id,
            Spectrum.user_id == current_user.id
        ).first()

        if not spectrum:
            logger.warning(f"⚠️  Espectro {spectrum_id} no encontrado para usuario {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Espectro no encontrado"
            )

        # ✅ Retornar datos completos
        spectrum_response = SpectrumResponse.model_validate(spectrum)
        spectrum_detail = SpectrumDetailResponse.from_spectrum(spectrum_response)

        logger.info(f"✅ Espectro obtenido: {spectrum.filename}")

        return SuccessResponse(
            success=True,
            message="Espectro obtenido",
            data={
                "spectrum": spectrum_detail.model_dump()
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error obteniendo espectro: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error obteniendo espectro"
        )


# ========================================
# DELETE /{spectrum_id}
# Eliminar espectro
# ========================================

@router.delete(
    "/{spectrum_id}",
    response_model=SuccessResponse,
    summary="Eliminar espectro"
)
def delete_spectrum(
    spectrum_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Eliminar un espectro
    """

    logger.info(f"🗑️  DELETE /spectra/{spectrum_id} - Usuario: {current_user.id}")

    try:
        spectrum = db.query(Spectrum).filter(
            Spectrum.id == spectrum_id,
            Spectrum.user_id == current_user.id
        ).first()

        if not spectrum:
            logger.warning(f"⚠️  Espectro {spectrum_id} no encontrado para usuario {current_user.id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Espectro no encontrado"
            )

        try:
            db.delete(spectrum)
            db.commit()
            logger.info(f"✅ Espectro eliminado: {spectrum.filename}")
        except SQLAlchemyError as e:
            logger.error(f"❌ Error eliminando de BD: {e}", exc_info=True)
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error eliminando espectro"
            )

        return SuccessResponse(
            success=True,
            message="Espectro eliminado"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en delete: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error eliminando espectro"
        )


# ========================================
# FUNCIONES AUXILIARES
# ========================================

def parse_spectrum_file(content: bytes, filename: str) -> dict:
    """
    Parsear archivo de espectro FTIR. Formatos soportados, en orden de detección:
      1. JCAMP-DX (.jdx/.dx/.jcm, o contenido que empieza por '##') — estándar
         IUPAC de intercambio para espectroscopía, vía la librería `jcamp`.
      2. CSV/TSV (.csv/.tsv, o contenido con comas/punto-y-coma detectado) — con
         sniffer de delimitador (csv.Sniffer).
      3. Texto plano de dos columnas separadas por espacios (formato original,
         fallback final — nunca se deja de soportar).
    Retorna: {"wavenumbers": [...], "absorbance": [...]}
    """
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''

    try:
        if ext in ('jdx', 'dx', 'jcm'):
            return _parse_jcamp_dx(content)

        text_content = content.decode('utf-8', errors='ignore')

        if text_content.lstrip().startswith('##'):
            # No tiene extensión JCAMP-DX pero el contenido sí lo es
            return _parse_jcamp_dx(content)

        if ext in ('csv', 'tsv'):
            return _parse_delimited_text(text_content)

        # Sniff: ¿las primeras líneas de datos usan coma o punto y coma?
        sample_lines = [l for l in text_content.split('\n')[:20] if l.strip() and not l.strip().startswith('#')]
        if sample_lines and any(',' in l or ';' in l for l in sample_lines[:3]):
            try:
                return _parse_delimited_text(text_content)
            except ValueError:
                pass  # no era CSV válido pese a tener comas -> cae al parser de espacios

        result = _parse_whitespace_columns(text_content)
        logger.info(f"✅ Archivo parseado (texto plano): {len(result['wavenumbers'])} puntos")
        return result

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"❌ Error parseando archivo: {e}", exc_info=True)
        raise ValueError(f"Error al parsear archivo: {str(e)}")


def _transmittance_to_absorbance(values, is_percent: bool) -> list:
    """A = -log10(T). Acepta T en [0,1] (is_percent=False) o %T en [0,100]."""
    import math
    out = []
    for v in values:
        t = (v / 100.0) if is_percent else v
        t = max(t, 1e-6)  # evita log10(0)/log10(negativo) con ruido de medida
        out.append(-math.log10(t))
    return out


def _parse_jcamp_dx(content: bytes) -> dict:
    """
    Parsea JCAMP-DX (formatos XY comprimidos X++(Y..Y), SQZ/DIF/DUP, y XY simple)
    vía la librería `jcamp`, que ya implementa el estándar completo (evita
    reinventar un parser de compresión de caracteres propenso a errores).
    Convierte a absorbancia si el archivo reporta %Transmitancia/Transmitancia.
    """
    import io
    import jcamp as jcamp_lib

    try:
        data = jcamp_lib.read(io.BytesIO(content))
    except Exception as e:
        raise ValueError(f"Error parseando JCAMP-DX: {e}")

    x = data.get('x')
    y = data.get('y')
    if x is None or y is None or len(x) == 0 or len(x) != len(y):
        raise ValueError("El archivo JCAMP-DX no contiene un bloque XYDATA/XYPOINTS válido")

    wavenumbers = [float(v) for v in x]
    absorbance = [float(v) for v in y]

    yunits = str(data.get('yunits', '')).upper()
    if 'TRANSMITTANCE' in yunits:
        is_percent = '%' in yunits or (max(absorbance, default=0.0) > 1.5)
        absorbance = _transmittance_to_absorbance(absorbance, is_percent)
        logger.info(f"   Convertido {'%' if is_percent else ''}Transmitancia -> Absorbancia")

    logger.info(f"✅ JCAMP-DX parseado: {len(wavenumbers)} puntos "
                f"(xunits={data.get('xunits','?')}, yunits={data.get('yunits','?')})")
    return {"wavenumbers": wavenumbers, "absorbance": absorbance}


def _parse_delimited_text(text_content: str) -> dict:
    """CSV/TSV con sniffer de delimitador (coma, punto y coma, tabulador). Ignora
    líneas de cabecera no numéricas y comentarios (#)."""
    import csv
    import io

    lines = [l for l in text_content.split('\n') if l.strip() and not l.strip().startswith('#')]
    if not lines:
        raise ValueError("Archivo vacío o sin datos")

    try:
        dialect = csv.Sniffer().sniff('\n'.join(lines[:10]), delimiters=',;\t')
    except csv.Error:
        dialect = csv.excel  # fallback: coma

    wavenumbers, absorbance = [], []
    for row in csv.reader(lines, dialect):
        if len(row) < 2:
            continue
        try:
            # Con delimitador ';' es común la coma como separador decimal (CSV europeo)
            wn_raw = row[0].strip()
            ab_raw = row[-1].strip()
            if dialect.delimiter != ',':
                wn_raw = wn_raw.replace(',', '.')
                ab_raw = ab_raw.replace(',', '.')
            wn = float(wn_raw)
            ab = float(ab_raw)
        except ValueError:
            continue  # fila de cabecera u otro contenido no numérico

        if 0 < wn < 5000:
            wavenumbers.append(wn)
            absorbance.append(ab)

    if not wavenumbers:
        raise ValueError("No se encontraron datos numéricos válidos en el CSV/TSV")

    logger.info(f"✅ CSV/TSV parseado (delimitador '{dialect.delimiter}'): {len(wavenumbers)} puntos")
    return {"wavenumbers": wavenumbers, "absorbance": absorbance}


def _parse_whitespace_columns(text_content: str) -> dict:
    """Texto plano de dos columnas separadas por espacios — formato original,
    se mantiene como fallback final para no romper archivos ya soportados."""
    wavenumbers, absorbance = [], []
    for line in text_content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) >= 2:
            try:
                wn = float(parts[-2])
                abs_val = float(parts[-1])
                if 0 < wn < 5000 and (0 <= abs_val <= 1 or 0 <= abs_val <= 100):
                    wavenumbers.append(wn)
                    absorbance.append(abs_val)
            except (ValueError, IndexError):
                continue

    if not wavenumbers or not absorbance:
        raise ValueError("No se encontraron datos válidos en el archivo")

    return {"wavenumbers": wavenumbers, "absorbance": absorbance}