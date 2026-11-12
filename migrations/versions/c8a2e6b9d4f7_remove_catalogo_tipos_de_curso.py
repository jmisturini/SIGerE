"""Remove o catálogo de Tipos de Curso (course_types).

O campo "Tipo de Curso" do lançamento de Hora Extra virou texto livre
(d1a5f8c2b7e9): o catálogo administrado no Painel Admin e as permissões
course_type:* ficaram obsoletos — nada lê nem grava a tabela. O histórico
dos lançamentos não se perde: a migração anterior já copiou os nomes do
catálogo para a coluna course_type.

Revision ID: c8a2e6b9d4f7
Revises: d1a5f8c2b7e9
Create Date: 2026-11-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'c8a2e6b9d4f7'
down_revision = 'd1a5f8c2b7e9'
branch_labels = None
depends_on = None


def upgrade():
    """Derruba o catálogo: os nomes já vivem na coluna course_type dos
    lançamentos de Hora Extra (copiados na conversão do FK)."""
    op.drop_table('course_types')


def downgrade():
    """Recria o catálogo vazio, com o schema original.

    Vazia de propósito: os nomes originais foram descartados com a tabela e
    não há como restaurá-los — quem voltar ao catálogo recadastra os tipos
    usados nos lançamentos (o downgrade de d1a5f8c2b7e9, seguinte na volta,
    aborta se algum lançamento ficar sem correspondência exata pelo nome).
    """
    op.create_table(
        'course_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
