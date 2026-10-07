"""notificacoes: marco "no dia" e opt-out de e-mail

Revision ID: a3f7c9e1b5d8
Revises: b8d4f2a6c3e9
Create Date: 2026-10-06 09:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = 'a3f7c9e1b5d8'
down_revision = 'b8d4f2a6c3e9'
branch_labels = None
depends_on = None


def upgrade():
    # Marco de antecedência "no dia da atividade" (aviso ancorado a um horário
    # fixo do próprio dia, além de 24h/1h antes do início).
    op.add_column('reservation_notification_configs',
                  sa.Column('notify_dia', sa.Boolean(), nullable=False,
                            server_default='0'))
    # Espelho por e-mail das notificações: o usuário pode desativar o envio
    # no perfil (o sino in-app continua); padrão ligado.
    op.add_column('user_notification_prefs',
                  sa.Column('email_enabled', sa.Boolean(), nullable=False,
                            server_default='1'))


def downgrade():
    op.drop_column('user_notification_prefs', 'email_enabled')
    op.drop_column('reservation_notification_configs', 'notify_dia')
