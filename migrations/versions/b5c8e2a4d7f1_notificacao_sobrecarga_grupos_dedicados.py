"""notificacoes: grupos dedicados do aviso de sobrecarga de professor

Revision ID: b5c8e2a4d7f1
Revises: e3b9d6c1a8f4
Create Date: 2026-10-02 09:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'b5c8e2a4d7f1'
down_revision = 'e3b9d6c1a8f4'
branch_labels = None
depends_on = None


def upgrade():
    # Regra de carga docente (reserva pendente por exceder o limite diário do
    # professor): a seleção de grupos destinatários ganha campo próprio na
    # configuração da unidade — vazio, ninguém recebe o aviso.
    op.create_table(
        'notification_config_overload_groups',
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['config_id'], ['unity_notification_configs.id'],
                                ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['notification_groups.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('config_id', 'group_id'),
    )


def downgrade():
    op.drop_table('notification_config_overload_groups')
