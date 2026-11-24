"""Fila do dreno: archived_at para esgotadas e índice parcial enxuto

Follow-up do índice parcial idx_notifications_mail_queue (e9a1c3d5f7b2,
issue #235): o predicado antigo (sent_at IS NULL) retém para sempre as
notificações que esgotaram MAIL_MAX_ATTEMPTS — elas envelhecem para o início
da ordem de created_at e cada rodada do notify-email anda por entradas mortas
antes de achar as vivas.

A saída honesta (sem apagar o aviso do sino e sem mentir no sent_at, que é
reservado para envios que de fato saíram):

- coluna nova notifications.archived_at — carimbada pelo dreno quando a
  notificação esgota tentativas; a linha segue na base (o sino continua) e
  deixa de disputar a fila;
- o índice parcial da fila passa a excluir as arquivadas
  (sent_at IS NULL AND archived_at IS NULL).

As linhas anteriores à coluna são arquivadas pela PRIMEIRA rodada do dreno
após o upgrade — lá, e não aqui, porque o limite de tentativas é configurável
(MAIL_MAX_ATTEMPTS) e só o dreno conhece o valor real do ambiente.

Revision ID: b7d4e1f2a8c3
Revises: e9a1c3d5f7b2
Create Date: 2026-11-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b7d4e1f2a8c3'
down_revision = 'e9a1c3d5f7b2'
branch_labels = None
depends_on = None

INDICE_FILA = 'idx_notifications_mail_queue'

# Predicado antigo e novo do índice parcial da fila (o restante é igual):
# a fila passa a ser "pendente de envio E não arquivada".
PREDICADO_ANTIGO = 'sent_at IS NULL'
PREDICADO_NOVO = 'sent_at IS NULL AND archived_at IS NULL'


def _colunas_notifications():
    inspector = sa.inspect(op.get_bind())
    return [c['name'] for c in inspector.get_columns('notifications')]


def upgrade():
    if 'archived_at' not in _colunas_notifications():
        # batch_alter_table cobre os dois dialetos: no SQLite, ADD COLUMN
        # nativo serve, mas o batch mantém um caminho só para ambos.
        with op.batch_alter_table('notifications', schema=None) as batch_op:
            batch_op.add_column(sa.Column('archived_at', sa.DateTime(),
                                          nullable=True))
    # Reconstruir o índice parcial com o predicado novo. if_exists/if_not_
    # exists pelo mesmo motivo da e9a1c3d5f7b2: o SQLite omite índices de
    # expressão na reflexão, e a checagem por inspector quebraria o ciclo
    # upgrade → downgrade → upgrade.
    op.drop_index(INDICE_FILA, 'notifications', if_exists=True)
    op.create_index(INDICE_FILA, 'notifications', ['created_at'],
                    if_not_exists=True,
                    postgresql_where=sa.text(PREDICADO_NOVO),
                    sqlite_where=sa.text(PREDICADO_NOVO))


def downgrade():
    op.drop_index(INDICE_FILA, 'notifications', if_exists=True)
    op.create_index(INDICE_FILA, 'notifications', ['created_at'],
                    if_not_exists=True,
                    postgresql_where=sa.text(PREDICADO_ANTIGO),
                    sqlite_where=sa.text(PREDICADO_ANTIGO))
    if 'archived_at' in _colunas_notifications():
        with op.batch_alter_table('notifications', schema=None) as batch_op:
            batch_op.drop_column('archived_at')
