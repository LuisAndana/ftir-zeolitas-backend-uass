"""
Esquemas Pydantic: Búsqueda por Similitud
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class SimilarityConfig(BaseModel):
    """Schema para configuración de búsqueda de similitud"""
    method: str = Field(default="cosine", description="cosine, pearson, euclidean")
    tolerance: int = Field(default=4, ge=1, le=20, description="±N cm-1")
    range_min: int = Field(default=400, ge=200, le=4000)
    range_max: int = Field(default=4000, ge=200, le=4000)
    top_n: int = Field(default=10, ge=1, le=100)
    family_filter: Optional[str] = Field(None)
    use_windows: bool = Field(default=False)
    selected_windows: Optional[List[str]] = Field(None)


class SimilarityResultItem(BaseModel):
    """Un resultado individual de similitud"""
    spectrum_id: int
    filename: str
    family: Optional[str]
    global_score: float = Field(..., ge=0, le=1)
    window_scores: Optional[List[dict]] = None
    matching_peaks: int
    total_peaks: int
    rank: int


class SimilaritySearchRequest(BaseModel):
    """Schema para request de búsqueda de similitud"""
    query_spectrum_id: int = Field(..., description="ID del espectro a buscar")
    config: SimilarityConfig = Field(..., description="Configuración de búsqueda")


class SimilaritySearchResponse(BaseModel):
    """Schema para respuesta de búsqueda de similitud"""
    query_spectrum_id: int
    search_method: str
    tolerance: int
    results: List[SimilarityResultItem]
    total_spectra_searched: int
    results_found: int
    execution_time_ms: float
    searched_at: datetime