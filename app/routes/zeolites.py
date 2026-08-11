"""
Rutas para el catálogo de zeolitas
Información de referencia sobre familias de zeolitas
"""

import logging
from fastapi import APIRouter, Depends, Query, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional
from pathlib import Path

from app.core.database import get_db
from app.models.zeolite_family import ZeoliteFamily
from app.schemas.zeolite import ZeoliteFamilyResponse
from app.schemas.common import SuccessResponse, PaginatedResponse
from app.services.zeolite_dataset_loader import ZeoliteDatasetLoader

# Directorio de archivos CIF de estructuras cristalográficas (IZA Structure
# Database). 29/35 familias del catálogo ya tienen .cif real descargado
# (ver static/structures/README.md) — este directorio sirve los que existen
# y responde 404/cif_available=false para el resto.
CIF_STRUCTURES_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "structures"

# Códigos para los que NUNCA existirá un CIF — no es un pendiente, es una
# limitación real de los materiales (ver static/structures/README.md para
# el detalle y las fuentes de cada uno). Se expone al frontend para que
# muestre un mensaje honesto en vez de sugerir "todavía no descargado".
NO_CIF_POSSIBLE_REASONS = {
    code: (
        "Sílice mesoporosa amorfa: no tiene cristalinidad de largo alcance, "
        "por lo tanto no existe una estructura periódica que describir en un CIF."
    )
    for code in ZeoliteDatasetLoader.AMORPHOUS_MESOPOROUS_CODES
}
NO_CIF_POSSIBLE_REASONS["NU86"] = (
    "La IZA nunca le asignó un código de framework de 3 letras a NU-86 "
    "(confirmado en las patentes originales ICI/IFP US6165439 y US6337428) — "
    "no existe un CIF oficial que descargar."
)

logger = logging.getLogger(__name__)

# ✅ SIN PREFIX - El prefijo se agrega en main.py
router = APIRouter(tags=["zeolitas"])


# ========================================
# GET /
# Obtener catálogo de zeolitas
# ========================================

@router.get(
    "",
    response_model=PaginatedResponse,
    summary="Obtener catálogo de zeolitas"
)
def get_zeolites(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Obtener lista de familias de zeolitas
    """

    try:
        query = db.query(ZeoliteFamily)

        if category:
            query = query.filter(ZeoliteFamily.category == category)

        if search:
            search_term = f"%{search.upper()}%"
            query = query.filter(
                (ZeoliteFamily.code.ilike(search_term)) |
                (ZeoliteFamily.name.ilike(search_term))
            )

        total = query.count()
        zeolites = query.offset(skip).limit(limit).all()

        page = skip // limit + 1
        total_pages = (total + limit - 1) // limit

        logger.info(f"📊 Zeolitas obtenidas: {len(zeolites)} de {total}")

        return PaginatedResponse(
            success=True,
            data=[ZeoliteFamilyResponse.model_validate(z).model_dump() for z in zeolites],
            pagination={"skip": skip, "limit": limit, "total": total},
            total=total,
            page=page,
            page_size=limit,
            total_pages=total_pages
        )

    except Exception as e:
        logger.error(f"Error obteniendo zeolitas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error obteniendo zeolitas"
        )


# ========================================
# GET /{code}
# Obtener zeolita por código
# ========================================

@router.get(
    "/{code}",
    response_model=SuccessResponse,
    summary="Obtener zeolita por código"
)
def get_zeolite_by_code(
    code: str,
    db: Session = Depends(get_db)
):
    """
    Obtener información de una familia de zeolita por su código IZA
    """

    try:
        zeolite = db.query(ZeoliteFamily).filter(
            ZeoliteFamily.code == code.upper()
        ).first()

        if not zeolite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Familia de zeolita '{code}' no encontrada"
            )

        logger.info(f"✅ Zeolita obtenida: {code}")

        return SuccessResponse(
            success=True,
            message="Zeolita obtenida",
            data={
                "zeolite": ZeoliteFamilyResponse.model_validate(zeolite).model_dump()
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo zeolita: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error obteniendo zeolita"
        )


# ========================================
# GET /{code}/structure
# Estructura cristalográfica (CIF) + bandas diagnósticas para el visor 3D
# Fase 0-1 de la hoja de ruta banda↔estructura (ver CLAUDE.md).
# ========================================

@router.get(
    "/{code}/structure",
    summary="Obtener estructura cristalográfica (CIF) y bandas diagnósticas",
)
def get_zeolite_structure(
    code: str,
    format: str = Query("json", pattern="^(json|cif)$"),
    db: Session = Depends(get_db),
):
    """
    Metadatos estructurales de la familia (bandas típicas Flanigen, Si/Al,
    tamaño de anillo, dimensionalidad de canal) y, si ya se descargó
    localmente, el contenido del archivo CIF (IZA Structure Database) para
    alimentar el visor 3D banda↔estructura.

    - format=json (default): metadatos + CIF embebido como texto si existe.
    - format=cif: el archivo CIF crudo (Content-Type: chemical/x-cif); 404 con
      instrucciones si aún no se ha descargado.

    Los .cif reales NO se descargan automáticamente (requieren permiso
    explícito, ver Fase 0 de la hoja de ruta) — deben colocarse manualmente en
    static/structures/{code}.cif, obtenidos de la IZA Structure Database.
    """
    code_upper = code.upper()
    zeolite = db.query(ZeoliteFamily).filter(ZeoliteFamily.code == code_upper).first()
    if not zeolite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Familia de zeolita '{code}' no encontrada")

    cif_filename = zeolite.cif_filename or f"{code_upper}.cif"
    cif_path = CIF_STRUCTURES_DIR / cif_filename
    cif_content = None
    cif_available = cif_path.is_file()
    if cif_available:
        try:
            cif_content = cif_path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning(f"⚠️ No se pudo leer CIF {cif_path}: {e}")
            cif_available = False

    if format == "cif":
        if not cif_available:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"CIF no disponible localmente para '{code_upper}'. Descargar de la IZA "
                    f"Structure Database (https://europe.iza-structure.org/IZA-SC/ftc_table.php, "
                    f"buscar el código '{code_upper}') y guardar en static/structures/{cif_filename}."
                ),
            )
        return PlainTextResponse(cif_content, media_type="chemical/x-cif")

    no_cif_reason = None if cif_available else NO_CIF_POSSIBLE_REASONS.get(code_upper)

    return SuccessResponse(
        success=True,
        message="Estructura obtenida" if cif_available else "Metadatos obtenidos (CIF aún no descargado)",
        data={
            "code": zeolite.code,
            "name": zeolite.name,
            "si_al_ratio": zeolite.si_al_ratio,
            "pore_size": zeolite.pore_size,
            "ring_size": zeolite.ring_size,
            "channel_dimensionality": zeolite.channel_dimensionality,
            "typical_bands": zeolite.typical_bands,
            "cif_available": cif_available,
            "cif_content": cif_content,
            # True cuando NO existe (ni existirá) un CIF real para este código
            # — sílice amorfa o framework sin código IZA asignado (ver
            # NO_CIF_POSSIBLE_REASONS). El frontend usa esto para mostrar un
            # mensaje honesto ("nunca tendrá modelo 3D") en vez de sugerir que
            # falta descargarlo.
            "cif_permanently_unavailable": no_cif_reason is not None,
            "cif_unavailable_reason": no_cif_reason,
            # Solo la URL limpia — el código a buscar se muestra aparte en el
            # frontend (structure.code), nunca concatenado dentro del href:
            # antes el string completo "url (buscar 'CODE')" se usaba tal
            # cual como [href], y el navegador URL-codificaba el paréntesis
            # como parte de la ruta -> 404 en el sitio de la IZA.
            "cif_source_hint": None if (cif_available or no_cif_reason) else (
                "https://europe.iza-structure.org/IZA-SC/ftc_table.php"
            ),
        },
    )


# ========================================
# GET /data/categories
# Obtener categorías
# ========================================

@router.get(
    "/data/categories",
    response_model=SuccessResponse,
    summary="Obtener categorías disponibles"
)
def get_categories(db: Session = Depends(get_db)):
    """
    Obtener todas las categorías de zeolitas disponibles
    """

    try:
        categories = db.query(ZeoliteFamily.category).distinct().all()
        category_list = sorted([cat[0] for cat in categories if cat[0]])

        logger.info(f"📊 Categorías obtenidas: {len(category_list)}")

        return SuccessResponse(
            success=True,
            message="Categorías obtenidas",
            data={
                "categories": category_list,
                "total": len(category_list)
            }
        )

    except Exception as e:
        logger.error(f"Error obteniendo categorías: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error obteniendo categorías"
        )


# ========================================
# GET /data/statistics
# Estadísticas del catálogo
# ========================================

@router.get(
    "/data/statistics",
    response_model=SuccessResponse,
    summary="Estadísticas del catálogo"
)
def get_statistics(db: Session = Depends(get_db)):
    """
    Obtener estadísticas generales del catálogo de zeolitas
    """

    try:
        total_families = db.query(ZeoliteFamily).count()

        categories_data = db.query(
            ZeoliteFamily.category,
            func.count(ZeoliteFamily.id).label('count')
        ).group_by(ZeoliteFamily.category).all()

        categories_by_count = {
            category: count for category, count in categories_data if category
        }

        logger.info(f"📊 Estadísticas: {total_families} familias")

        return SuccessResponse(
            success=True,
            message="Estadísticas obtenidas",
            data={
                "total_families": total_families,
                "total_categories": len(categories_by_count),
                "categories_by_count": categories_by_count
            }
        )

    except Exception as e:
        logger.error(f"Error obteniendo estadísticas: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error obteniendo estadísticas"
        )