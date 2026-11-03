"""
Modelos de Proyectos: espacio de trabajo personal del investigador.

Un proyecto agrupa archivos (espectros y notas). Cada edición de un archivo crea
una VERSIÓN nueva e inmutable con su motivo (los datos nunca se sobrescriben), y
cada acción relevante queda en la bitácora (ProjectActivity, solo se agrega).
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import relationship
from app.core.database import Base

_LongText = Text().with_variant(LONGTEXT, "mysql")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(150), nullable=False)
    description = Column(Text, nullable=True)
    derived_from_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    files = relationship("ProjectFile", back_populates="project", cascade="all, delete-orphan",
                         passive_deletes=True)
    activity = relationship("ProjectActivity", back_populates="project", cascade="all, delete-orphan",
                            passive_deletes=True)


class ProjectFile(Base):
    __tablename__ = "project_files"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    kind = Column(String(20), nullable=False)  # "spectrum" | "note"
    current_version = Column(Integer, nullable=False, default=1)
    # Biblioteca de referencia verificada: el investigador confirma la familia
    # (p. ej. con DRX) y el archivo participa como candidato en /similarity/search.
    is_reference = Column(Boolean, nullable=False, default=False)
    family_code = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    project = relationship("Project", back_populates="files")
    versions = relationship("ProjectFileVersion", back_populates="file", cascade="all, delete-orphan",
                            passive_deletes=True, order_by="ProjectFileVersion.version")


class ProjectFileVersion(Base):
    __tablename__ = "project_file_versions"
    __table_args__ = (UniqueConstraint("file_id", "version", name="uq_file_version"),)

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("project_files.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    # spectrum: JSON {"wavenumbers": [...], "absorbance": [...]}; note: texto plano
    content = Column(_LongText, nullable=False)
    content_hash = Column(String(64), nullable=False)  # SHA-256 del contenido
    change_reason = Column(String(500), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    file = relationship("ProjectFile", back_populates="versions")


class ProjectActivity(Base):
    """Bitácora: solo se agrega, nunca se edita ni se borra individualmente."""
    __tablename__ = "project_activity"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    file_id = Column(Integer, ForeignKey("project_files.id", ondelete="SET NULL"), nullable=True)
    file_name = Column(String(255), nullable=True)  # se conserva aunque el archivo se elimine
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(40), nullable=False)
    reason = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="activity")
