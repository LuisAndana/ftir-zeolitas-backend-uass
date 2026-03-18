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
    category: str
    si_al_ratio: Optional[str]
    pore_size: Optional[str]
    typical_bands: Optional[List[float]]
    description: Optional[str]

    class Config:
        from_attributes = True