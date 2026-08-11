"""
Esquemas Pydantic: Zeolita
"""

from pydantic import BaseModel
from typing import Optional, List


class ZeoliteFamilyResponse(BaseModel):
    """Schema para respuesta de familia de zeolita"""
    id: int
    code: str
    name: str
    category: Optional[str] = None
    si_al_ratio: Optional[str] = None
    pore_size: Optional[str] = None
    typical_bands: Optional[List[float]] = None
    ring_size: Optional[str] = None
    channel_dimensionality: Optional[str] = None
    cif_filename: Optional[str] = None
    description: Optional[str] = None

    class Config:
        from_attributes = True
