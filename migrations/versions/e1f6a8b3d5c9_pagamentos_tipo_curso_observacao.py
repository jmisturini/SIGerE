"""pagamentos: tipo de curso e observação na hora extra

Revision ID: e1f6a8b3d5c9
Revises: d9e3f5a7c1b4
Create Date: 2026-10-02 16:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e1f6a8b3d5c9'
down_revision = 'd9e3f5a7c1b4'
branch_labels = None
depends_on = None


def upgrade():
    # Catálogo de Tipos de Curso (Painel Admin) — alimenta o dropdown do
    # lançamento de Hora Extra; nome único porque é o identificador exibido
    # na planilha.
    op.create_table(
        'course_types',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=60), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    # Campos novos no lançamento: tipo de curso (obrigatório no formulário —
    # nullable no banco apenas para registros anteriores ao campo) e
    # observação livre. Batch mode: o SQLite não aceita ALTER de constraints
    # fora dele.
    with op.batch_alter_table('teacher_overtime_pay') as batch:
        batch.add_column(sa.Column('course_type_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('observation', sa.Text(), nullable=True))
        batch.create_foreign_key('fk_overtime_course_type', 'course_types',
                                 ['course_type_id'], ['id'])


def downgrade():
    with op.batch_alter_table('teacher_overtime_pay') as batch:
        batch.drop_column('observation')
        batch.drop_column('course_type_id')
    op.drop_table('course_types')
