"""proyectos: projects, project_files, project_file_versions, project_activity

Revision ID: a91c3d5e7b02
Revises: f20fcc4f3e94
Create Date: 2026-11-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = 'a91c3d5e7b02'
down_revision: Union[str, Sequence[str], None] = 'f20fcc4f3e94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_longtext = sa.Text().with_variant(mysql.LONGTEXT(), "mysql")


def upgrade() -> None:
    op.create_table(
        'projects',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(150), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('derived_from_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_projects_id', 'projects', ['id'])
    op.create_index('ix_projects_user_id', 'projects', ['user_id'])

    op.create_table(
        'project_files',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('current_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_reference', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('family_code', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_project_files_id', 'project_files', ['id'])
    op.create_index('ix_project_files_project_id', 'project_files', ['project_id'])

    op.create_table(
        'project_file_versions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('file_id', sa.Integer(), sa.ForeignKey('project_files.id', ondelete='CASCADE'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('content', _longtext, nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('change_reason', sa.String(500), nullable=False),
        sa.Column('created_by', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('file_id', 'version', name='uq_file_version'),
    )
    op.create_index('ix_project_file_versions_id', 'project_file_versions', ['id'])
    op.create_index('ix_project_file_versions_file_id', 'project_file_versions', ['file_id'])

    op.create_table(
        'project_activity',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_id', sa.Integer(), sa.ForeignKey('project_files.id', ondelete='SET NULL'), nullable=True),
        sa.Column('file_name', sa.String(255), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('action', sa.String(40), nullable=False),
        sa.Column('reason', sa.String(500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_project_activity_id', 'project_activity', ['id'])
    op.create_index('ix_project_activity_project_id', 'project_activity', ['project_id'])


def downgrade() -> None:
    op.drop_table('project_activity')
    op.drop_table('project_file_versions')
    op.drop_table('project_files')
    op.drop_table('projects')
