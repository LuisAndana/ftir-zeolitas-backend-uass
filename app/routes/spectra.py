"""
Rutas para carga y gestión de espectros - CON MANEJO DE ERRORES MEJORADO Y LOGS DE DEBUG
"""

import logging
import json
from fastapi import APIRouter, Depends, File, UploadFile, Query, HTTPException, status
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
            detail=f"Error obteniendo espectros: {str(e)}"
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
    filename: Optional[str] = None,
    material: Optional[str] = None,
    technique: Optional[str] = None,
    hydration_state: Optional[str] = None,
    temperature: Optional[str] = None,
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
            detail=f"Error al cargar espectro: {str(e)}"
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
    Parsear archivo de espectro en múltiples formatos
    Retorna: {"wavenumbers": [...], "absorbance": [...]}
    """

    try:
        # Intentar como texto
        text_content = content.decode('utf-8', errors='ignore')
        lines = text_content.split('\n')

        wavenumbers = []
        absorbance = []

        for line in lines:
            line = line.strip()

            # Saltar líneas vacías o comentarios
            if not line or line.startswith('#'):
                continue

            # Parsear números
            parts = line.split()

            if len(parts) >= 2:
                try:
                    # Intentar parsear últimos 2 números
                    wn = float(parts[-2])
                    abs_val = float(parts[-1])

                    # Validar rangos razonables
                    if 0 < wn < 5000 and (0 <= abs_val <= 1 or 0 <= abs_val <= 100):
                        wavenumbers.append(wn)
                        absorbance.append(abs_val)
                except (ValueError, IndexError):
                    continue

        if not wavenumbers or not absorbance:
            raise ValueError("No se encontraron datos válidos en el archivo")

        logger.info(f"✅ Archivo parseado: {len(wavenumbers)} puntos")

        return {
            "wavenumbers": wavenumbers,
            "absorbance": absorbance
        }

    except Exception as e:
        logger.error(f"❌ Error parseando archivo: {e}", exc_info=True)
        raise ValueError(f"Error al parsear archivo: {str(e)}")