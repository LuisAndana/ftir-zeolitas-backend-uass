"""
Seguridad y autenticación
Gestión de contraseñas, JWT tokens y autenticación
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)

# ========================================
# CONFIGURACIÓN DE SEGURIDAD
# ========================================

# Contexto para hash de contraseñas
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)


# ========================================
# FUNCIONES DE CONTRASEÑA
# ========================================

def hash_password(password: str) -> str:
    """
    Hashear contraseña con bcrypt

    Args:
        password: Contraseña sin encriptar

    Returns:
        str: Hash bcrypt de la contraseña
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verificar que una contraseña coincide con su hash

    Args:
        plain_password: Contraseña sin encriptar
        hashed_password: Hash bcrypt almacenado

    Returns:
        bool: True si coincide, False si no
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        logger.error(f"Error verificando contraseña: {e}")
        return False


# ========================================
# GESTOR DE TOKENS JWT
# ========================================

class TokenManager:
    """Clase para gestionar tokens JWT"""

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """
        Crear access token JWT

        Args:
            data: Datos a incluir en el token (debe incluir "sub")
            expires_delta: Tiempo de expiración personalizado

        Returns:
            str: Token JWT codificado
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                minutes=settings.access_token_expire_minutes
            )

        # Convertir a timestamp unix (número)
        to_encode.update({"exp": int(expire.timestamp())})

        # El subject DEBE ser string
        if "sub" in to_encode:
            to_encode["sub"] = str(to_encode["sub"])

        try:
            encoded_jwt = jwt.encode(
                to_encode,
                settings.secret_key,
                algorithm=settings.algorithm
            )
            return encoded_jwt
        except Exception as e:
            logger.error(f"Error creando token: {e}")
            raise


    @staticmethod
    def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """
        Crear refresh token JWT

        Args:
            data: Datos a incluir en el token (debe incluir "sub")
            expires_delta: Tiempo de expiración personalizado

        Returns:
            str: Token JWT codificado
        """
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(
                days=settings.refresh_token_expire_days
            )

        # Convertir a timestamp unix
        to_encode.update({"exp": int(expire.timestamp())})

        # El subject DEBE ser string
        if "sub" in to_encode:
            to_encode["sub"] = str(to_encode["sub"])

        try:
            encoded_jwt = jwt.encode(
                to_encode,
                settings.secret_key,
                algorithm=settings.algorithm
            )
            return encoded_jwt
        except Exception as e:
            logger.error(f"Error creando refresh token: {e}")
            raise


    @staticmethod
    def verify_token(token: str) -> Dict:
        """
        Verificar y decodificar token JWT

        Args:
            token: Token JWT a verificar

        Returns:
            dict: Payload decodificado del token

        Raises:
            JWTError: Si el token es inválido
        """
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm]
            )
            return payload
        except JWTError as e:
            logger.error(f"Token inválido: {e}")
            raise JWTError(f"Token inválido: {str(e)}")
        except Exception as e:
            logger.error(f"Error verificando token: {e}")
            raise JWTError(f"Error verificando token: {str(e)}")


# ========================================
# DEPENDENCIA DE AUTENTICACIÓN
# ========================================

async def get_current_user(
    token: str = None,
    db: Session = Depends(get_db)
) -> User:
    """
    Obtener usuario actual a partir del token JWT

    Uso en rutas:
        @router.get("/")
        def my_route(current_user: User = Depends(get_current_user)):
            ...

    Args:
        token: Token JWT del header Authorization
        db: Sesión de base de datos

    Returns:
        User: Usuario autenticado

    Raises:
        HTTPException: Si el token es inválido o el usuario no existe
    """

    # Credenciales inválidas
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Obtener token del header si no está en parámetro
    from fastapi import Header

    auth_header = None

    # Intentar obtener del header directamente (esto no funcionará en Depends)
    # Por eso usamos un enfoque alternativo con un middleware o parámetro

    if not token:
        raise credentials_exception

    try:
        # Verificar token
        payload = TokenManager.verify_token(token)
        user_id = payload.get("sub")

        if user_id is None:
            logger.error("Token sin subject")
            raise credentials_exception

        # Convertir a int si es string
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            logger.error(f"User ID inválido: {user_id}")
            raise credentials_exception

    except JWTError as e:
        logger.error(f"Error en token JWT: {e}")
        raise credentials_exception

    # Obtener usuario de BD
    try:
        user = db.query(User).filter(User.id == user_id).first()

        if user is None:
            logger.error(f"Usuario no encontrado: {user_id}")
            raise credentials_exception

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario inactivo"
            )

        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo usuario: {e}")
        raise credentials_exception


# ========================================
# DEPENDENCIA MEJORADA CON HEADER
# ========================================

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def get_current_user_v2(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Obtener usuario actual a partir del token JWT (mejorado)

    Usa el header Authorization: Bearer <token>

    Args:
        credentials: Credenciales del header
        db: Sesión de base de datos

    Returns:
        User: Usuario autenticado
    """

    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        # Verificar token
        payload = TokenManager.verify_token(token)
        user_id = payload.get("sub")

        if user_id is None:
            logger.error("Token sin subject")
            raise credentials_exception

        # Convertir a int
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            logger.error(f"User ID inválido: {user_id}")
            raise credentials_exception

    except JWTError as e:
        logger.error(f"Error en token JWT: {e}")
        raise credentials_exception

    # Obtener usuario de BD
    try:
        user = db.query(User).filter(User.id == user_id).first()

        if user is None:
            logger.error(f"Usuario no encontrado: {user_id}")
            raise credentials_exception

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario inactivo"
            )

        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo usuario: {e}")
        raise credentials_exception


# ========================================
# FUNCIONES DE GENERACIÓN DE TOKENS
# ========================================

def generate_tokens(user_id: int) -> Dict[str, str]:
    """
    Generar access token y refresh token

    Args:
        user_id: ID del usuario

    Returns:
        dict: Diccionario con access_token y refresh_token
    """

    # Convertir user_id a string para el token
    access_token = TokenManager.create_access_token(
        data={"sub": user_id}
    )

    refresh_token = TokenManager.create_refresh_token(
        data={"sub": user_id}
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


# ========================================
# ALIAS PARA COMPATIBILIDAD
# ========================================

# Para mantener compatibilidad con código existente
get_current_user = get_current_user_v2