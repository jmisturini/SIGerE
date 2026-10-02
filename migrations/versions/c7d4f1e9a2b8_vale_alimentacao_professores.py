"""rh: vale alimentação de professores (lançamento de dias trabalhados)

Revision ID: c7d4f1e9a2b8
Revises: b5c8e2a4d7f1
Create Date: 2026-10-02 11:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c7d4f1e9a2b8'
down_revision = 'b5c8e2a4d7f1'
branch_labels = None
depends_on = None


def upgrade():
    # Módulo RH "Vale Alimentação - Professores": lançamento simples de dias
    # trabalhados por professor, escopado à unidade e com o responsável
    # registrado. Sem valores financeiros — a folha continua fora do sistema.
    op.create_table(
        'teacher_meal_allowances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('unity_id', sa.Integer(), nullable=True),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.ForeignKeyConstraint(['unity_id'], ['unities.id']),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_teacher_meal_allowances_unity_id',
                    'teacher_meal_allowances', ['unity_id'])


def downgrade():
    op.drop_index('ix_teacher_meal_allowances_unity_id',
                  table_name='teacher_meal_allowances')
    op.drop_table('teacher_meal_allowances')
