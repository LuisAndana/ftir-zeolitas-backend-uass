"""
Rutas de administración
Gestión de usuarios: activar, cambiar rol, eliminar
Solo accesible por administradores
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserResponse, UserAdminUpdate
from app.schemas.common import SuccessResponse
from app.core.security import get_current_user
from app.core.email_utils import send_activation_email

logger = logging.getLogger(__name__)

router = APIRouter(tags=["administración"])


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Dependencia: solo permite administradores."""
    if current_user.role != "administrador":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador"
        )
    return current_user


# ========================================
# GET /users — Listar todos los usuarios
# ========================================

@router.get(
    "/users",
    response_model=SuccessResponse,
    summary="Listar todos los usuarios",
)
def list_users(
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return SuccessResponse(
        success=True,
        message="Usuarios obtenidos",
        data=[UserResponse.model_validate(u).model_dump() for u in users]
    )


# ========================================
# PATCH /users/{user_id} — Actualizar usuario
# ========================================

@router.patch(
    "/users/{user_id}",
    response_model=SuccessResponse,
    summary="Actualizar estado o rol de un usuario",
)
def update_user(
    user_id: int,
    body: UserAdminUpdate,
    background_tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes modificar tu propia cuenta desde aquí"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    was_inactive = not user.is_active

    if body.is_active is not None:
        user.is_active = body.is_active

    if body.role is not None:
        if body.role not in ("investigador", "administrador"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rol inválido. Usa 'investigador' o 'administrador'"
            )
        user.role = body.role

    db.commit()
    db.refresh(user)

    # Notificar al usuario cuando el admin activa su cuenta
    if was_inactive and user.is_active and user.is_verified:
        background_tasks.add_task(send_activation_email, user.email, user.name)

    logger.info(f"✅ Admin {admin.email} actualizó usuario {user.email}")

    return SuccessResponse(
        success=True,
        message="Usuario actualizado",
        data=UserResponse.model_validate(user).model_dump()
    )


# ========================================
# DELETE /users/{user_id} — Eliminar usuario
# ========================================

@router.delete(
    "/users/{user_id}",
    response_model=SuccessResponse,
    summary="Eliminar un usuario",
)
def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes eliminar tu propia cuenta"
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    db.delete(user)
    db.commit()

    logger.info(f"✅ Admin {admin.email} eliminó usuario {user.email}")

    return SuccessResponse(success=True, message="Usuario eliminado")
