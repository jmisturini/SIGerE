"""hora extra: mes das datas do lancamento

O formulario passa a ter o campo Mês (mês de referência ou o anterior) que
define a qual mês pertencem os dias gravados em multiple_dates — que voltam a
ser apenas os dias ("10, 17, 25"). A coluna dates_month guarda esse mês; nula
nos lançamentos antigos, cujos dias pertencem ao month_base.

Revision ID: b8d4f2a6c3e9
Revises: c2a9e7b5d4f1
Create Date: 2026-10-05 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8d4f2a6c3e9'
down_revision = 'c2a9e7b5d4f1'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'teacher_overtime_pay' not in inspector.get_table_names():
        return
    colunas = {c['name'] for c in inspector.get_columns('teacher_overtime_pay')}
    if 'dates_month' in colunas:
        return
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.add_column(sa.Column('dates_month', sa.String(7), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'teacher_overtime_pay' not in inspector.get_table_names():
        return
    colunas = {c['name'] for c in inspector.get_columns('teacher_overtime_pay')}
    if 'dates_month' not in colunas:
        return
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.drop_column('dates_month')
