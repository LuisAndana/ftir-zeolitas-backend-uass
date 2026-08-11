"""
Modelo: Tabla de Resultados de Búsqueda de Similitud
"""

from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
from datetime import datetime


class SimilarityResult(Base):
    """
    Almacena historiales de búsquedas por similitud
    Guarda la configuración y resultados de cada búsqueda
    """
    __tablename__ = "similarity_results"

    # Identificador
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    query_spectrum_id = Column(Integer, ForeignKey("spectra.id"), nullable=False)

    # Configuración de búsqueda
    search_method = Column(String(50), default="cosine")  # cosine, pearson, euclidean
    tolerance = Column(Integer, default=4)
    range_min = Column(Integer, default=400)
    range_max = Column(Integer, default=4000)
    top_n = Column(Integer, default=10)
    min_similarity = Column(Float, default=0.5)
    family_filter = Column(String(50), nullable=True)
    use_windows = Column(Boolean, default=False)
    selected_windows = Column(JSON, nullable=True)

    # Versión del pipeline que produjo estos scores — ver
    # app.services.spectral_preprocessing.ALGORITHM_VERSION. Necesario para
    # reproducibilidad: si el algoritmo cambia, un score histórico solo es
    # comparable a otro si comparten esta versión.
    algorithm_version = Column(String(20), nullable=True)

    # Resultados (almacenados como JSON)
    results = Column(JSON, nullable=False)  # Lista de resultados con scores

    # Estadísticas
    total_spectra_searched = Column(Integer, nullable=True)
    execution_time_ms = Column(Float, nullable=True)
    results_found = Column(Integer, nullable=True)

    # Auditoría
    searched_at = Column(DateTime(timezone=True), server_default=func.now())



    def __repr__(self):
        return f"<SimilarityResult(id={self.id}, user_id={self.user_id}, method={self.search_method})>"