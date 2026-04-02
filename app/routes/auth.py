"""
Rutas de autenticación
Login, registro, verificación de correo, refresh token
"""

import logging
import secrets
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
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
from app.core.email_utils import send_verification_email

logger = logging.getLogger(__name__)

router = APIRouter(tags=["autenticación"])


# ========================================
# POST /register
# ========================================

@router.post(
    "/register",
    response_model=SuccessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario",
)
def register(
    user_data: UserRegister,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    try:
        existing_user = db.query(User).filter(
            User.email == user_data.email.lower()
        ).first()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este email ya está registrado"
            )

        verification_token = secrets.token_urlsafe(48)

        db_user = User(
            name=user_data.name,
            email=user_data.email.lower(),
            password_hash=hash_password(user_data.password),
            role="investigador",
            is_active=False,       # El admin debe activar la cuenta
            is_verified=False,     # El usuario debe verificar su correo
            verification_token=verification_token,
        )

        db.add(db_user)
        db.commit()
        db.refresh(db_user)

        background_tasks.add_task(
            send_verification_email,
            db_user.email,
            db_user.name,
            verification_token,
        )

        logger.info(f"✅ Usuario registrado: {user_data.email}")

        return SuccessResponse(
            success=True,
            message="Cuenta creada. Revisa tu correo para verificar tu dirección.",
            data=None
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
# GET /verify-email
# ========================================

@router.get(
    "/verify-email",
    response_model=SuccessResponse,
    summary="Verificar correo con token",
)
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.verification_token == token).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de verificación inválido o ya utilizado"
        )

    if user.is_verified:
        return SuccessResponse(
            success=True,
            message="Tu correo ya fue verificado previamente"
        )

    user.is_verified = True
    user.verification_token = None
    db.commit()

    logger.info(f"✅ Correo verificado: {user.email}")

    return SuccessResponse(
        success=True,
        message="Correo verificado exitosamente. Un administrador activará tu cuenta pronto."
    )


# ========================================
# POST /login
# ========================================

@router.post(
    "/login",
    response_model=SuccessResponse,
    summary="Iniciar sesión",
)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    try:
        user = db.query(User).filter(
            User.email == user_data.email.lower()
        ).first()

        if not user or not verify_password(user_data.password, user.password_hash):
            logger.warning(f"❌ Login fallido: {user_data.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Email o contraseña incorrectos"
            )

        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="EMAIL_NOT_VERIFIED"
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="ACCOUNT_PENDING_APPROVAL"
            )

        tokens = generate_tokens(user.id)

        logger.info(f"✅ Login exitoso: {user.email}")

        return SuccessResponse(
            success=True,
            message="Login exitoso",
            data={
                "user": UserResponse.model_validate(user).model_dump(),
                **tokens,
                "expires_in": 3600
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
    try:
        refresh_token = refresh_token_data.get("refresh_token")

        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Refresh token requerido"
            )

        payload = TokenManager.verify_token(refresh_token)
        user_id = payload.get("sub")

        user = db.query(User).filter(User.id == int(user_id)).first()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario no encontrado o inactivo"
            )

        new_access_token = TokenManager.create_access_token(data={"sub": user.id})

        logger.info(f"✅ Token refrescado: {user.email}")

        return SuccessResponse(
            success=True,
            message="Token refrescado",
            data={
                "access_token": new_access_token,
                "token_type": "bearer",
                "expires_in": 3600
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
# ========================================

@router.get(
    "/me",
    response_model=SuccessResponse,
    summary="Obtener usuario actual",
)
def get_me(current_user: User = Depends(get_current_user)):
    return SuccessResponse(
        success=True,
        message="Usuario obtenido",
        data={"user": UserResponse.model_validate(current_user).model_dump()}
    )


# ========================================
# POST /logout
# ========================================

@router.post(
    "/logout",
    response_model=SuccessResponse,
    summary="Cerrar sesión",
)
def logout(current_user: User = Depends(get_current_user)):
    logger.info(f"✅ Logout: {current_user.email}")
    return SuccessResponse(success=True, message="Sesión cerrada exitosamente")
