"""
Esquemas Pydantic: Usuario
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime


class UserRegister(BaseModel):
    """Schema para registro de usuario"""
    name: str = Field(..., min_length=3, max_length=100, description="Nombre completo")
    email: EmailStr = Field(..., description="Email válido y único")
    password: str = Field(..., min_length=8, max_length=255, description="Contraseña mínimo 8 caracteres")

    @field_validator('name')
    @classmethod
    def name_must_have_space(cls, v):
        """Validar que el nombre tenga al menos un espacio"""
        if ' ' not in v:
            # Opcional: validar que tenga espacio
            pass
        return v.strip()


class UserLogin(BaseModel):
    """Schema para login"""
    email: EmailStr = Field(..., description="Email registrado")
    password: str = Field(..., description="Contraseña")


class UserResponse(BaseModel):
    """Schema para respuesta de usuario (sin password)"""
    id: int
    name: str
    email: str
    role: str = "investigador"
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UserAdminUpdate(BaseModel):
    """Schema para que el admin actualice un usuario"""
    is_active: Optional[bool] = None
    role: Optional[str] = None


class UserUpdate(BaseModel):
    """Schema para actualizar usuario"""
    name: Optional[str] = Field(None, min_length=3, max_length=100)
    institution: Optional[str] = Field(None, max_length=255)
    department: Optional[str] = Field(None, max_length=255)
    research_area: Optional[str] = Field(None, max_length=100)