"""
Modelo para espectros FTIR
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Spectrum(Base):
    """
    Modelo de espectro FTIR
    """
    __tablename__ = "spectra"

    # Campos principales
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)

    # Metadata del espectro
    material = Column(String(255), nullable=True)
    technique = Column(String(100), nullable=True)  # ATR, Transmisión, Reflexión, DRIFT
    hydration_state = Column(String(100), nullable=True)  # As-synthesized, Secado, Calcinado
    temperature = Column(String(50), nullable=True)  # Temperatura de medición

    # Datos del espectro (JSON string con wavenumbers y absorbance)
    wavenumber_data = Column(Text, nullable=True, default='{"wavenumbers": [], "absorbance": []}')

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relación con User
    user = relationship("User", back_populates="spectra")

    def __repr__(self):
        return f"<Spectrum(id={self.id}, filename='{self.filename}', user_id={self.user_id})>"