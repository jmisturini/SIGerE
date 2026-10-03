"""notificações: configuração passa a ser por reserva

Revision ID: c2a9e7b5d4f1
Revises: e1f6a8b3d5c9
Create Date: 2026-10-03 09:00:00.000000

Cria a configuração de notificação 1:1 com a reserva (ReservationNotificationConfig:
avisos de 24h/1h antes + destinatários individuais e grupos) e as preferências do
usuário (UserNotificationPref: silenciar tudo ou por tipo de sala). A configuração
geral por unidade (UnityNotificationConfig) sobra apenas para o aviso de sobrecarga
de professor — as colunas dos avisos de reserva próxima são removidas.

As reservas com notify_enabled herdaram destinatários da configuração da unidade:
a migração cria a configuração por reserva delas com o aviso de 24h ligado
(equivalente ao antigo marco de 1 dia) e os destinatários que a unidade configurava
(professor, criador e grupos) — o opt-in de cada reserva não morre na migração.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c2a9e7b5d4f1'
down_revision = 'e1f6a8b3d5c9'
branch_labels = None
depends_on = None


def _tem_coluna(inspector, tabela, coluna):
    return coluna in (c['name'] for c in inspector.get_columns(tabela))


def _tem_tabela(inspector, tabela):
    return tabela in inspector.get_table_names()


def _copiar_configs_legados(bind):
    """Cria a configuração por reserva das reservas com notify_enabled, com os
    destinatários que a configuração da unidade definia. Roda ANTES do drop das
    colunas legadas. Tabelas legadas ausentes (banco novo) apenas pulam a cópia."""
    inspector = sa.inspect(bind)
    if not _tem_tabela(inspector, 'unity_notification_configs'):
        return
    if not _tem_coluna(inspector, 'unity_notification_configs', 'notify_teacher'):
        return

    # Tabelas leves só para a cópia (não são metadata do app): o Core renderiza
    # os booleanos no formato certo de cada banco (TRUE no Postgres, 1 no SQLite).
    legado_cfg = sa.table('unity_notification_configs',
                          sa.column('id', sa.Integer),
                          sa.column('unity_id', sa.Integer),
                          sa.column('notify_teacher', sa.Boolean),
                          sa.column('notify_creator', sa.Boolean),
                          sa.column('lead_days', sa.String))
    legado_grupos = sa.table('notification_config_groups',
                             sa.column('config_id', sa.Integer),
                             sa.column('group_id', sa.Integer))
    reservas = sa.table('reservations',
                        sa.column('id', sa.Integer),
                        sa.column('unity_id', sa.Integer),
                        sa.column('user_id', sa.Integer),
                        sa.column('teacher_id', sa.Integer),
                        sa.column('notify_enabled', sa.Boolean))
    novas = sa.table('reservation_notification_configs',
                     sa.column('id', sa.Integer),
                     sa.column('reservation_id', sa.Integer),
                     sa.column('notify_24h', sa.Boolean),
                     sa.column('notify_1h', sa.Boolean))
    novos_grupos = sa.table('reservation_notification_groups',
                            sa.column('config_id', sa.Integer),
                            sa.column('group_id', sa.Integer))
    novos_usuarios = sa.table('reservation_notification_users',
                              sa.column('config_id', sa.Integer),
                              sa.column('user_id', sa.Integer))

    por_unidade = {}
    for row in bind.execute(sa.select(
            legado_cfg.c.id, legado_cfg.c.unity_id, legado_cfg.c.notify_teacher,
            legado_cfg.c.notify_creator)):
        grupos = [g for g in bind.execute(sa.select(legado_grupos.c.group_id)
                  .where(legado_grupos.c.config_id == row.id)).scalars()]
        por_unidade[row.unity_id] = {
            'teacher': bool(row.notify_teacher), 'creator': bool(row.notify_creator),
            'grupos': grupos}

    for row in bind.execute(sa.select(
            reservas.c.id, reservas.c.unity_id, reservas.c.user_id,
            reservas.c.teacher_id).where(reservas.c.notify_enabled == True)):  # noqa: E712
        legado = por_unidade.get(row.unity_id)
        if legado is None:
            continue
        resultado = bind.execute(novas.insert().values(
            reservation_id=row.id, notify_24h=True, notify_1h=False))
        config_id = resultado.inserted_primary_key[0]
        usuarios = set()
        if legado['creator'] and row.user_id is not None:
            usuarios.add(row.user_id)
        if legado['teacher'] and row.teacher_id is not None:
            usuarios.add(row.teacher_id)
        for user_id in sorted(usuarios):
            bind.execute(novos_usuarios.insert().values(
                config_id=config_id, user_id=user_id))
        for group_id in legado['grupos']:
            bind.execute(novos_grupos.insert().values(
                config_id=config_id, group_id=group_id))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    op.create_table(
        'reservation_notification_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('reservation_id', sa.Integer(), nullable=False),
        sa.Column('notify_24h', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('notify_1h', sa.Boolean(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'],
                                name='fk_resnotif_reservation', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_reservation_notification_configs_reservation_id',
                    'reservation_notification_configs', ['reservation_id'], unique=True)

    op.create_table(
        'reservation_notification_groups',
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['config_id'],
                                ['reservation_notification_configs.id'],
                                name='fk_resnotifgrupos_config', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['notification_groups.id'],
                                name='fk_resnotifgrupos_grupo', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('config_id', 'group_id'),
    )

    op.create_table(
        'reservation_notification_users',
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['config_id'],
                                ['reservation_notification_configs.id'],
                                name='fk_resnotifusers_config', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'],
                                name='fk_resnotifusers_user', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('config_id', 'user_id'),
    )

    op.create_table(
        'user_notification_prefs',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('mute_all', sa.Boolean(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'],
                                name='fk_usernotifpref_user', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
    )

    op.create_table(
        'user_notification_muted_categories',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('category_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['user_notification_prefs.user_id'],
                                name='fk_usermutecat_pref', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['category_id'], ['room_categories.id'],
                                name='fk_usermutecat_category', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'category_id'),
    )

    # Herança dos opt-ins existentes antes de remover as colunas legadas.
    if _tem_tabela(inspector, 'reservations') and _tem_coluna(
            inspector, 'reservations', 'notify_enabled'):
        _copiar_configs_legados(bind)

    if _tem_tabela(inspector, 'notification_config_groups'):
        op.drop_table('notification_config_groups')

    if _tem_tabela(inspector, 'unity_notification_configs'):
        with op.batch_alter_table('unity_notification_configs') as batch:
            for coluna in ('notify_approvers', 'notify_creator', 'notify_teacher',
                           'lead_days', 'is_enabled'):
                if _tem_coluna(inspector, 'unity_notification_configs', coluna):
                    batch.drop_column(coluna)


def downgrade():
    with op.batch_alter_table('unity_notification_configs') as batch:
        batch.add_column(sa.Column('is_enabled', sa.Boolean(), nullable=False,
                                   server_default='1'))
        batch.add_column(sa.Column('lead_days', sa.String(50), nullable=False,
                                   server_default='7,1'))
        batch.add_column(sa.Column('notify_teacher', sa.Boolean(), nullable=False,
                                   server_default='1'))
        batch.add_column(sa.Column('notify_creator', sa.Boolean(), nullable=False,
                                   server_default='1'))
        batch.add_column(sa.Column('notify_approvers', sa.Boolean(), nullable=False,
                                   server_default='0'))

    op.create_table(
        'notification_config_groups',
        sa.Column('config_id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['config_id'], ['unity_notification_configs.id'],
                                name='fk_cfggrupos_config', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['group_id'], ['notification_groups.id'],
                                name='fk_cfggrupos_grupo', ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('config_id', 'group_id'),
    )

    op.drop_table('user_notification_muted_categories')
    op.drop_table('user_notification_prefs')
    op.drop_table('reservation_notification_users')
    op.drop_table('reservation_notification_groups')
    op.drop_table('reservation_notification_configs')
