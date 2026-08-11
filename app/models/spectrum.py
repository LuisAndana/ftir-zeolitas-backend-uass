"""
Modelo para espectros FTIR
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
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

    # Datos del espectro (JSON string con wavenumbers y absorbance).
    # LONGTEXT en MySQL (hasta 4 GB) en vez de TEXT (límite real de 64 KB, que
    # puede truncar SILENCIOSAMENTE según sql_mode un espectro de resolución
    # fina: 1800-7200 puntos con floats en JSON ronda o supera 64 KB). Sigue
    # siendo JSON de texto plano — sin cambios en la serialización/lectura.
    # with_variant: Text genérico en cualquier otro dialecto (SQLite en tests),
    # LONGTEXT específicamente en MySQL — mysql.LONGTEXT no es compilable en SQLite.
    wavenumber_data = Column(
        Text().with_variant(LONGTEXT, "mysql"),
        nullable=True, default='{"wavenumbers": [], "absorbance": []}',
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relación con User
    user = relationship("User", back_populates="spectra")

    def __repr__(self):
        return f"<Spectrum(id={self.id}, filename='{self.filename}', user_id={self.user_id})>"