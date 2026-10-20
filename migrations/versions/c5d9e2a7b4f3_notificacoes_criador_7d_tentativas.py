"""notificacoes: criador como destinatario, marco 7d e tentativas de e-mail

Revision ID: c5d9e2a7b4f3
Revises: a3f7c9e1b5d8
Create Date: 2026-10-06 16:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'c5d9e2a7b4f3'
down_revision = 'a3f7c9e1b5d8'
branch_labels = None
depends_on = None


def upgrade():
    # Criador entra como destinatário dos avisos da própria reserva por
    # padrão (pode desmarcar no formulário). Configurações existentes passam
    # a incluir o criador — o padrão do sistema.
    op.add_column('reservation_notification_configs',
                  sa.Column('notify_criador', sa.Boolean(), nullable=False,
                            server_default='1'))
    # Marco de antecedência de 7 dias antes do início.
    op.add_column('reservation_notification_configs',
                  sa.Column('notify_7d', sa.Boolean(), nullable=False,
                            server_default='0'))
    # Espelho por e-mail: tentativas de envio já feitas para a notificação —
    # passadas do limite (MAIL_MAX_ATTEMPTS), saem da fila para não travá-la.
    op.add_column('notifications',
                  sa.Column('send_attempts', sa.Integer(), nullable=False,
                            server_default='0'))


def downgrade():
    op.drop_column('notifications', 'send_attempts')
    op.drop_column('reservation_notification_configs', 'notify_7d')
    op.drop_column('reservation_notification_configs', 'notify_criador')
