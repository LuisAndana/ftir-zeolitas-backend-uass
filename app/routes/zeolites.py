"""
Rutas para el catálogo de zeolitas
Información de referencia sobre familias de zeolitas
"""

import logging
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.models.zeolite_family import ZeoliteFamily
from app.schemas.zeolite import ZeoliteFamilyResponse
from app.schemas.common import SuccessResponse, PaginatedResponse

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
            db.func.count(ZeoliteFamily.id).label('count')
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