"""
Schemas para espectros FTIR
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
import json

class SpectrumBase(BaseModel):
    """Schema base para espectro"""
    filename: str
    material: Optional[str] = None
    technique: Optional[str] = None
    hydration_state: Optional[str] = None
    temperature: Optional[str] = None


class SpectrumCreate(SpectrumBase):
    """Schema para crear espectro"""
    pass


class SpectrumResponse(BaseModel):
    """
    Schema para respuesta de espectro
    ✅ COINCIDE CON EL MODELO SPECTRUM
    """
    id: int
    user_id: int
    filename: str
    material: Optional[str] = None
    technique: Optional[str] = None
    hydration_state: Optional[str] = None
    temperature: Optional[str] = None
    wavenumber_data: Optional[str] = None  # JSON string
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True  # ✅ Para ORM objects


class SpectrumDetailResponse(SpectrumResponse):
    """
    Schema extendido con datos parseados del espectro
    """
    wavenumbers: Optional[List[float]] = Field(default=None)
    absorbance: Optional[List[float]] = Field(default=None)
    point_count: Optional[int] = None
    spectral_range_min: Optional[float] = None
    spectral_range_max: Optional[float] = None
    min_absorbance: Optional[float] = None
    max_absorbance: Optional[float] = None
    mean_absorbance: Optional[float] = None

    @classmethod
    def from_spectrum(cls, spectrum: "SpectrumResponse"):
        """
        Convertir SpectrumResponse a SpectrumDetailResponse
        parseando los datos JSON
        """
        wavenumbers = []
        absorbance = []

        # Parsear wavenumber_data si existe
        if spectrum.wavenumber_data:
            try:
                data = json.loads(spectrum.wavenumber_data)
                wavenumbers = data.get("wavenumbers", [])
                absorbance = data.get("absorbance", [])
            except (json.JSONDecodeError, TypeError):
                pass

        # Calcular estadísticas
        point_count = len(wavenumbers) if wavenumbers else 0
        spectral_range_min = min(wavenumbers) if wavenumbers else None
        spectral_range_max = max(wavenumbers) if wavenumbers else None
        min_absorbance = min(absorbance) if absorbance else None
        max_absorbance = max(absorbance) if absorbance else None
        mean_absorbance = sum(absorbance) / len(absorbance) if absorbance else None

        return cls(
            id=spectrum.id,
            user_id=spectrum.user_id,
            filename=spectrum.filename,
            material=spectrum.material,
            technique=spectrum.technique,
            hydration_state=spectrum.hydration_state,
            temperature=spectrum.temperature,
            wavenumber_data=spectrum.wavenumber_data,
            created_at=spectrum.created_at,
            updated_at=spectrum.updated_at,
            wavenumbers=wavenumbers,
            absorbance=absorbance,
            point_count=point_count,
            spectral_range_min=spectral_range_min,
            spectral_range_max=spectral_range_max,
            min_absorbance=min_absorbance,
            max_absorbance=max_absorbance,
            mean_absorbance=mean_absorbance,
        )


class SpectrumListResponse(BaseModel):
    """Schema para lista de espectros sin datos detallados"""
    id: int
    filename: str
    material: Optional[str] = None
    technique: Optional[str] = None
    created_at: datetime
    point_count: Optional[int] = None

    class Config:
        from_attributes = True