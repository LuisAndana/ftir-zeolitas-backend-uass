"""
Esquemas Pydantic: Comunes/Genéricos
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class Token(BaseModel):
    """Schema para respuesta de token"""
    access_token: str = Field(..., description="JWT Access Token")
    refresh_token: str = Field(..., description="JWT Refresh Token")
    token_type: str = Field(default="bearer", description="Tipo de token")
    expires_in: int = Field(..., description="Tiempo de expiración en segundos")


class TokenPayload(BaseModel):
    """Schema para payload del token JWT"""
    sub: int  # user_id
    exp: datetime
    iat: datetime


class SuccessResponse(BaseModel):
    """Schema para respuesta exitosa genérica"""
    success: bool = True
    message: str
    data: Optional[dict] = None


class ErrorResponse(BaseModel):
    """Schema para respuesta de error"""
    success: bool = False
    message: str
    detail: Optional[str] = None
    error_code: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Schema para respuesta paginada"""
    success: bool = True
    data: List
    pagination: dict
    total: int
    page: int
    page_size: int
    total_pages: int