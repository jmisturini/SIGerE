"""pagamentos: carga horaria semanal em hora decimal

O formulario passa a receber hora e minuto separados e grava o valor ja
convertido (ex: 4h30 → 4.5). Inteiros antigos continuam validos como decimais,
entao nenhuma conversao de dados e necessaria.

Revision ID: e7d5a9c3b1f8
Revises: f6b3c9e1a7d2
Create Date: 2026-09-18 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7d5a9c3b1f8'
down_revision = 'f6b3c9e1a7d2'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'teacher_overtime_pay' not in inspector.get_table_names():
        return
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.alter_column('weekly_workload', existing_type=sa.Integer(),
                              type_=sa.Numeric(5, 2), existing_nullable=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'teacher_overtime_pay' not in inspector.get_table_names():
        return
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.alter_column('weekly_workload', existing_type=sa.Numeric(5, 2),
                              type_=sa.Integer(), existing_nullable=False)
