"""Tipo de curso do lançamento de Hora Extra vira texto livre.

O campo era FK para o catálogo course_types (dropdown do formulário); o
formulário hoje aceita texto livre. A migração copia o nome do tipo para a
nova coluna course_type, preservando o histórico, e remove o FK.

Revision ID: d1a5f8c2b7e9
Revises: b4e8f2a6c9d1
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1a5f8c2b7e9'
down_revision = 'b4e8f2a6c9d1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.add_column(sa.Column('course_type', sa.String(60), nullable=True))
    # Preserva o histórico: o texto recebe o nome do antigo catálogo.
    op.execute("""
        UPDATE teacher_overtime_pay
        SET course_type = (SELECT ct.name FROM course_types ct
                           WHERE ct.id = teacher_overtime_pay.course_type_id)
    """)
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.drop_column('course_type_id')


def downgrade():
    # Best effort: re-liga os lançamentos ao catálogo pelo nome exato; sem
    # correspondência, o FK fica nulo (coluna sempre foi nullable).
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'course_type_id', sa.Integer(),
            sa.ForeignKey('course_types.id'), nullable=True))
    op.execute("""
        UPDATE teacher_overtime_pay
        SET course_type_id = (SELECT ct.id FROM course_types ct
                              WHERE ct.name = teacher_overtime_pay.course_type)
    """)
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.drop_column('course_type')
