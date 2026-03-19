"""
Esquemas (Pydantic) para similitud espectral FTIR
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SimilarityConfig(BaseModel):
    """Configuración para búsqueda de similitud"""

    method: str = Field(default="cosine", description="Método: cosine, pearson, euclidean")
    tolerance: float = Field(default=4, ge=0.1, le=10, description="Tolerancia en cm⁻¹")
    range_min: int = Field(default=400, ge=0, le=4000, description="Rango mínimo cm⁻¹")
    range_max: int = Field(default=4000, ge=0, le=4000, description="Rango máximo cm⁻¹")
    top_n: int = Field(default=10, ge=1, le=100, description="Número de resultados")
    family_filter: Optional[str] = Field(default=None, description="Filtrar por familia")
    use_windows: bool = Field(default=False, description="Usar ventanas espectrales")
    selected_windows: List[str] = Field(default_factory=list, description="Ventanas seleccionadas")

    class Config:
        json_schema_extra = {
            "example": {
                "method": "cosine",
                "tolerance": 4,
                "range_min": 400,
                "range_max": 4000,
                "top_n": 10,
                "family_filter": None,
                "use_windows": False,
                "selected_windows": []
            }
        }


class SimilarityResult(BaseModel):
    """Resultado individual de similitud"""

    spectrum_id: int
    filename: str
    family: Optional[str] = None
    global_score: float = Field(..., ge=0, le=1)
    window_scores: List[Dict[str, Any]] = Field(default_factory=list)
    matching_peaks: int = 0
    total_peaks: int = 0
    rank: int = 0


class SimilaritySearchData(BaseModel):
    """Datos de respuesta de búsqueda"""

    query_spectrum_id: int
    search_method: str
    tolerance: float
    results: List[SimilarityResult]
    total_spectra_searched: int
    results_found: int
    execution_time_ms: float
    searched_at: Optional[str] = None


class SimilaritySearchRequest(BaseModel):
    """Request para búsqueda de similitud"""

    query_spectrum_id: int = Field(..., description="ID del espectro a buscar")
    config: SimilarityConfig = Field(..., description="Configuración de búsqueda")

    class Config:
        json_schema_extra = {
            "example": {
                "query_spectrum_id": 1,
                "config": {
                    "method": "cosine",
                    "tolerance": 4,
                    "range_min": 400,
                    "range_max": 4000,
                    "top_n": 10,
                    "family_filter": None,
                    "use_windows": False,
                    "selected_windows": []
                }
            }
        }


class SimilaritySearchResponse(BaseModel):
    """Response para búsqueda de similitud"""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class ComparisonResponse(BaseModel):
    """Response para comparación de espectros"""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None