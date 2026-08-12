"""similarity_results: ON DELETE CASCADE en query_spectrum_id

Antes, borrar un espectro que ya tuviera una búsqueda de similitud guardada
(tabla similarity_results, ver migración 543003fa5a07) fallaba con un 500
genérico: MySQL rechazaba el DELETE por la FK sin comportamiento definido
(IntegrityError 1451 'Cannot delete or update a parent row'). El historial de
búsquedas no tiene sentido sin el espectro de consulta que lo originó, así
que se agrega ON DELETE CASCADE: borrar un espectro borra también sus
búsquedas asociadas, en vez de bloquear la eliminación.

Revision ID: f20fcc4f3e94
Revises: 543003fa5a07
Create Date: 2026-08-11 23:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f20fcc4f3e94'
down_revision: Union[str, Sequence[str], None] = '543003fa5a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('similarity_results') as batch_op:
        batch_op.drop_constraint('similarity_results_ibfk_2', type_='foreignkey')
        batch_op.create_foreign_key(
            'similarity_results_ibfk_2',
            'spectra', ['query_spectrum_id'], ['id'],
            ondelete='CASCADE',
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('similarity_results') as batch_op:
        batch_op.drop_constraint('similarity_results_ibfk_2', type_='foreignkey')
        batch_op.create_foreign_key(
            'similarity_results_ibfk_2',
            'spectra', ['query_spectrum_id'], ['id'],
        )
