from sqlalchemy import Column, Integer, String, DateTime, func
from app.core.database import Base

class ZeoliteFamily(Base):
    __tablename__ = "zeolite_families"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(String(512), nullable=True)
    category = Column(String(100), nullable=True)
    chemical_formula = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<ZeoliteFamily(id={self.id}, code='{self.code}', name='{self.name}')>"