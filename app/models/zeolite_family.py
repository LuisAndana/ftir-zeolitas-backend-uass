from sqlalchemy import Column, Integer, String, DateTime, JSON, func
from app.core.database import Base

class ZeoliteFamily(Base):
    """
    Catálogo de referencia de familias/frameworks de zeolitas (código IZA).

    si_al_ratio/pore_size se guardan como rango en texto libre (p.ej. "1.0-1.5",
    "4.1 Å") porque varían entre miembros de una misma familia (p.ej. MFI cubre
    Si/Al desde ~15 hasta silicalita casi pura) — un único Float perdería esa
    variabilidad real. typical_bands guarda las posiciones de banda diagnósticas
    (cm⁻¹) según la clasificación Flanigen-Khatami-Szymanski, usadas por el
    visor 3D banda↔estructura para resaltar la unidad estructural correspondiente.
    """
    __tablename__ = "zeolite_families"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(512), nullable=True)
    category = Column(String(100), nullable=True)
    chemical_formula = Column(String(255), nullable=True)

    si_al_ratio = Column(String(50), nullable=True)
    pore_size = Column(String(100), nullable=True)
    typical_bands = Column(JSON, nullable=True)  # lista de floats (cm-1)
    ring_size = Column(String(50), nullable=True)  # p.ej. "8-MR", "10-MR", "12-MR"
    channel_dimensionality = Column(String(20), nullable=True)  # "1D" | "2D" | "3D"
    cif_filename = Column(String(255), nullable=True)  # nombre del CIF en static/structures/, si está disponible

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ZeoliteFamily(id={self.id}, code='{self.code}', name='{self.name}')>"
