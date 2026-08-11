"""spectra: wavenumber_data de TEXT a LONGTEXT

Revision ID: e0c697971c04
Revises: 2401e9b67e1e
Create Date: 2026-08-09

TEXT en MySQL tiene un límite real de 64 KB. Un espectro FTIR de resolución
fina (1800-7200 puntos, 400-4000 cm⁻¹) serializado como JSON de dos arrays de
floats ronda o supera ese límite — MySQL puede truncarlo SILENCIOSAMENTE según
sql_mode (sin lanzar error), dejando JSON corrupto que parse_wavenumber_data
convertía en lista vacía sin ninguna señal del problema real.

Escrita a mano (no autogenerada): SQLite no distingue TEXT de LONGTEXT (misma
afinidad de tipo), así que `alembic revision --autogenerate` contra una BD de
prueba en SQLite no detecta este cambio — es un ajuste específico de MySQL.
No cambia la serialización (sigue siendo JSON de texto plano) ni afecta a
otros dialectos: en SQLite/PostgreSQL este ALTER es esencialmente un no-op.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'e0c697971c04'
down_revision: Union[str, Sequence[str], None] = '2401e9b67e1e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'spectra', 'wavenumber_data',
        existing_type=mysql.TEXT(),
        type_=mysql.LONGTEXT(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # ADVERTENCIA: si algún espectro ya excede 64 KB tras el upgrade, este
    # downgrade lo truncaría silenciosamente al volver a TEXT — MySQL no avisa.
    op.alter_column(
        'spectra', 'wavenumber_data',
        existing_type=mysql.LONGTEXT(),
        type_=mysql.TEXT(),
        existing_nullable=True,
    )
