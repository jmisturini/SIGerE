"""pagamentos: remove lancamentos base e aditivos (resta hora extra)

Revision ID: b8c41d6f2e97
Revises: d3502873b8e2
Create Date: 2026-09-08 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8c41d6f2e97'
down_revision = 'd3502873b8e2'
branch_labels = None
depends_on = None

# O aditivo referencia o lançamento base (FK CASCADE), então ambos saem juntos.
DROPPED_TABLES = ('teacher_additive_payment', 'teacher_base_pay')


def _existing_tables():
    inspector = sa.inspect(op.get_bind())
    return inspector.get_table_names()


def upgrade():
    # Guarda idempotente: bancos criados após a remoção do módulo não têm
    # essas tabelas (equivalente ao padrão da migration d3502873b8e2).
    tables = _existing_tables()
    for table in DROPPED_TABLES:
        if table in tables:
            op.drop_table(table)


def downgrade():
    # Recria as tabelas conforme o schema inicial (9673dec865ca).
    tables = _existing_tables()
    if 'teacher_base_pay' not in tables:
        op.create_table('teacher_base_pay',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=True),
        sa.Column('unity_id', sa.Integer(), nullable=True),
        sa.Column('month_start', sa.String(length=7), nullable=False),
        sa.Column('month_end', sa.String(length=7), nullable=False),
        sa.Column('budget_code', sa.Integer(), nullable=False),
        sa.Column('complement', sa.String(length=100), nullable=True),
        sa.Column('weekly_workload', sa.Integer(), nullable=False),
        sa.Column('monthly_hour', sa.Integer(), nullable=True),
        sa.Column('semester_hour', sa.Integer(), nullable=True),
        sa.Column('accountable_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('term_generated', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['accountable_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['unity_id'], ['unities.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('teacher_base_pay', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_teacher_base_pay_unity_id'), ['unity_id'], unique=False)

    if 'teacher_additive_payment' not in tables:
        op.create_table('teacher_additive_payment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('base_release_id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=True),
        sa.Column('unity_id', sa.Integer(), nullable=True),
        sa.Column('month_start', sa.String(length=7), nullable=False),
        sa.Column('month_end', sa.String(length=7), nullable=False),
        sa.Column('additional_hour', sa.Integer(), nullable=False),
        sa.Column('monthly_hour', sa.Integer(), nullable=True),
        sa.Column('semester_hour', sa.Integer(), nullable=True),
        sa.Column('complement', sa.String(length=100), nullable=True),
        sa.Column('accountable_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('term_generated', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['accountable_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['base_release_id'], ['teacher_base_pay.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['unity_id'], ['unities.id'], ),
        sa.PrimaryKeyConstraint('id')
        )
        with op.batch_alter_table('teacher_additive_payment', schema=None) as batch_op:
            batch_op.create_index(batch_op.f('ix_teacher_additive_payment_unity_id'), ['unity_id'], unique=False)
