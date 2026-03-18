"""
Rutas de autenticación
Login, registro, refresh token
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import datetime

from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserRegister, UserLogin, UserResponse
from app.schemas.common import Token, SuccessResponse
from app.core.security import (
    hash_password,
    verify_password,
    generate_tokens,
    get_current_user,
    TokenManager
)

logger = logging.getLogger(__name__)

# ✅ SIN PREFIX - El prefijo se agrega en main.py
router = APIRouter(tags=["autenticación"])


# ========================================
# POST /register
# Registrar nuevo usuario
# ========================================

@router.post(
    "/register",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    """
    Registrar un nuevo usuario en el sistema
    """

    try:
        # Verificar si email ya existe
        existing_user = db.query(User).filter(
            User.email == user_data.email.lower()
        ).first()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este email ya está registrado"
            )

        # Crear nuevo usuario
        db_user = User(
            name=user_data.name,
            email=user_data.email.lower(),
            password_hash=hash_password(user_data.password)
        )

        # Guardar en BD
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        # Generar tokens
        tokens = generate_tokens(db_user.id)

        logger.info(f"✅ Usuario registrado: {user_data.email}")

        return SuccessResponse(
            success=True,
            message="Usuario registrado exitosamente",
            data={
                "user": UserResponse.model_validate(db_user).model_dump(),
                **tokens
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registrando usuario: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al registrar usuario"
        )


# ========================================
# POST /login
# Iniciar sesión
# ========================================

@router.post(
    "/login",
    response_model=SuccessResponse,
    summary="Iniciar sesión",
)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    """
    Iniciar sesión con email y contraseña
    """

    try:
        # Buscar usuario por email
        user = db.query(User).filter(
            User.email == user_data.email.lower()
        ).first()

        # Validar usuario y contraseña
        if not user or not verify_password(user_data.password, user.password_hash):
            logger.warning(f"❌ Intento de login fallido: {user_data.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email o contraseña incorrectos"
            )

        # Validar que el usuario esté activo
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario inactivo"
            )

        # Actualizar último login
        user.last_login = datetime.utcnow()
        db.commit()
        db.refresh(user)

        # Generar tokens
        tokens = generate_tokens(user.id)

        logger.info(f"✅ Login exitoso: {user.email}")

        return SuccessResponse(
            success=True,
            message="Login exitoso",
            data={
                "user": UserResponse.model_validate(user).model_dump(),
                **tokens
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en login: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al iniciar sesión"
        )


# ========================================
# POST /refresh
# Refrescar access token
# ========================================

@router.post(
    "/refresh",
    response_model=SuccessResponse,
    summary="Refrescar access token",
)
def refresh_access_token(
        refresh_token_data: dict,
        db: Session = Depends(get_db)
):
    """
    Usar refresh token para obtener nuevo access token
    """

    try:
        refresh_token = refresh_token_data.get("refresh_token")

        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Refresh token requerido"
            )

        # Verificar refresh token
        payload = TokenManager.verify_token(refresh_token)
        user_id = payload.get("sub")

        # Obtener usuario
        user = db.query(User).filter(User.id == int(user_id)).first()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario no encontrado o inactivo"
            )

        # Generar nuevo access token
        new_access_token = TokenManager.create_access_token(
            data={"sub": user.id}
        )

        logger.info(f"✅ Token refrescado para usuario: {user.email}")

        return SuccessResponse(
            success=True,
            message="Token refrescado",
            data={
                "access_token": new_access_token,
                "token_type": "bearer",
                "expires_in": 60 * 60
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refrescando token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido"
        )


# ========================================
# GET /me
# Obtener usuario actual
# ========================================

@router.get(
    "/me",
    response_model=SuccessResponse,
    summary="Obtener usuario actual",
)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Obtener información del usuario autenticado
    """

    return SuccessResponse(
        success=True,
        message="Usuario obtenido",
        data={
            "user": UserResponse.model_validate(current_user).model_dump()
        }
    )


# ========================================
# POST /logout
# Logout
# ========================================

@router.post(
    "/logout",
    response_model=SuccessResponse,
    summary="Cerrar sesión",
)
def logout(current_user: User = Depends(get_current_user)):
    """
    Cerrar sesión
    """

    logger.info(f"✅ Logout: {current_user.email}")

    return SuccessResponse(
        success=True,
        message="Sesión cerrada exitosamente"
    )