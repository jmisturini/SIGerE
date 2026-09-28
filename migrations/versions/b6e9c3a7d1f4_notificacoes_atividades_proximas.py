"""notificações de atividades próximas (grupos, config por unidade, avisos)

Revision ID: b6e9c3a7d1f4
Revises: f3b8d2c6a9e1
Create Date: 2026-09-27 12:00:00.000000

Cria as tabelas do módulo de notificações de reserva próxima:
- notification_groups + notification_group_members: grupos personalizados de
  destinatários por unidade (equipes que recebem os avisos juntos);
- unity_notification_configs + notification_config_groups: configuração por
  unidade (marcos de antecedência e quem recebe, incluindo quais grupos);
- notifications: um aviso por destinatário, com unicidade
  (user_id, event_type, reservation_id, milestone) que torna a varredura
  idempotente — rodar `flask notify-scan` duas vezes não duplica avisos.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b6e9c3a7d1f4'
down_revision = 'f3b8d2c6a9e1'
branch_labels = None
depends_on = None


def _tem_tabela(inspector, tabela):
    return tabela in inspector.get_table_names()


def upgrade():
    inspector = sa.inspect(op.get_bind())

    if not _tem_tabela(inspector, 'notification_groups'):
        op.create_table(
            'notification_groups',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('unity_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['unity_id'], ['unities.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unity_id', 'name', name='uq_notification_group_unity_name'),
        )
        op.create_index('ix_notification_groups_unity_id', 'notification_groups', ['unity_id'])

    if not _tem_tabela(inspector, 'notification_group_members'):
        op.create_table(
            'notification_group_members',
            sa.Column('group_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['group_id'], ['notification_groups.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('group_id', 'user_id'),
        )

    if not _tem_tabela(inspector, 'unity_notification_configs'):
        op.create_table(
            'unity_notification_configs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unity_id', sa.Integer(), nullable=False),
            sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('lead_days', sa.String(length=50), nullable=False, server_default='7,1'),
            sa.Column('notify_teacher', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('notify_creator', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('notify_approvers', sa.Boolean(), nullable=False, server_default='0'),
            sa.ForeignKeyConstraint(['unity_id'], ['unities.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unity_id'),
        )
        op.create_index('ix_unity_notification_configs_unity_id',
                        'unity_notification_configs', ['unity_id'])

    if not _tem_tabela(inspector, 'notification_config_groups'):
        op.create_table(
            'notification_config_groups',
            sa.Column('config_id', sa.Integer(), nullable=False),
            sa.Column('group_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['config_id'], ['unity_notification_configs.id'],
                                    ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['group_id'], ['notification_groups.id'],
                                    ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('config_id', 'group_id'),
        )

    if not _tem_tabela(inspector, 'notifications'):
        op.create_table(
            'notifications',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('reservation_id', sa.Integer(), nullable=True),
            sa.Column('event_type', sa.String(length=40), nullable=False,
                      server_default='reservation_upcoming'),
            sa.Column('milestone', sa.String(length=10), nullable=False),
            sa.Column('title', sa.String(length=200), nullable=False),
            sa.Column('body', sa.Text(), nullable=True),
            sa.Column('url', sa.String(length=300), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('read_at', sa.DateTime(), nullable=True),
            sa.Column('sent_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['reservation_id'], ['reservations.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('user_id', 'event_type', 'reservation_id', 'milestone',
                                name='uq_notification_destinatario_evento'),
        )
        op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
        op.create_index('ix_notifications_reservation_id', 'notifications', ['reservation_id'])
        op.create_index('ix_notifications_user_read', 'notifications', ['user_id', 'read_at'])


def downgrade():
    inspector = sa.inspect(op.get_bind())

    if _tem_tabela(inspector, 'notifications'):
        op.drop_index('ix_notifications_user_read', table_name='notifications')
        op.drop_index('ix_notifications_reservation_id', table_name='notifications')
        op.drop_index('ix_notifications_user_id', table_name='notifications')
        op.drop_table('notifications')
    if _tem_tabela(inspector, 'notification_config_groups'):
        op.drop_table('notification_config_groups')
    if _tem_tabela(inspector, 'unity_notification_configs'):
        op.drop_index('ix_unity_notification_configs_unity_id',
                      table_name='unity_notification_configs')
        op.drop_table('unity_notification_configs')
    if _tem_tabela(inspector, 'notification_group_members'):
        op.drop_table('notification_group_members')
    if _tem_tabela(inspector, 'notification_groups'):
        op.drop_index('ix_notification_groups_unity_id', table_name='notification_groups')
        op.drop_table('notification_groups')
