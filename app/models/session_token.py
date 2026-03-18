"""
Modelo: Tabla de Session Tokens
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from app.core.database import Base
from datetime import datetime


class SessionToken(Base):
    """
    Tabla para gestionar sesiones y refresh tokens
    """
    __tablename__ = "session_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    refresh_token = Column(String(500), unique=True, nullable=False)
    is_revoked = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)

    def __repr__(self):
        return f"<SessionToken(user_id={self.user_id}, is_revoked={self.is_revoked})>"