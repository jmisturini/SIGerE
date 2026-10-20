"""notificacoes: remove duplicados redundantes da varredura antiga

Revision ID: e3b9d6c1a8f4
Revises: d8e2f4a6c0b8
Create Date: 2026-09-30 10:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = 'e3b9d6c1a8f4'
down_revision = 'd8e2f4a6c0b8'
branch_labels = None
depends_on = None


def upgrade():
    # A varredura, com janela aberta, podia disparar marcos anteriores junto
    # do mais iminente: reserva criada na véspera para o dia seguinte, com
    # marcos 7,1,0, criava '7d' e '1d' na mesma execução — com título e corpo
    # idênticos (o título descreve a proximidade real, "Amanhã"), o que o
    # usuário via como notificação duplicada. Mantém, por destinatário/reserva
    # com o mesmo conteúdo, apenas o marco mais iminente (menor lead); avisos
    # legítimos (títulos distintos, criados em dias diferentes) ficam intactos.
    op.execute('DELETE FROM notifications '
               'WHERE event_type = \'reservation_upcoming\' '
               'AND EXISTS ('
               'SELECT 1 FROM notifications AS n2 '
               'WHERE n2.user_id = notifications.user_id '
               'AND n2.reservation_id = notifications.reservation_id '
               'AND n2.event_type = notifications.event_type '
               'AND n2.title = notifications.title '
               'AND n2.body IS NOT DISTINCT FROM notifications.body '
               'AND CAST(rtrim(n2.milestone, \'d\') AS INTEGER) '
               '< CAST(rtrim(notifications.milestone, \'d\') AS INTEGER))')


def downgrade():
    # Notificações removidas eram duplicatas redundantes: não há como (nem
    # por que) recriá-las.
    pass
