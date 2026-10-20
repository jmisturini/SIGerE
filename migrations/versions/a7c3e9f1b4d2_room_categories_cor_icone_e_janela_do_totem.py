"""room_categories: cor, icone e janela de exibicao do totem

Revision ID: a7c3e9f1b4d2
Revises: d9f31c8a6b24
Create Date: 2026-09-08 15:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3e9f1b4d2'
down_revision = 'd9f31c8a6b24'
branch_labels = None
depends_on = None

# Aparência padrão por código conhecido — apenas categorias já cadastradas
# recebem ícone/cor; novas categorias nascem via painel com os valores escolhidos.
_DEFAULTS_BY_CODE = {
    'classroom': ('bi-door-closed', '#0d6efd'),
    'auditorium': ('bi-buildings', '#004b8d'),
    'kitchen': ('bi-cup-hot', '#f0ad4e'),
    'computer_lab': ('bi-pc-display', '#0dcaf0'),
    'health_lab': ('bi-heart-pulse', '#dc3545'),
}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'room_categories' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('room_categories')]

    with op.batch_alter_table('room_categories', schema=None) as batch_op:
        if 'color' not in columns:
            batch_op.add_column(sa.Column('color', sa.String(length=7), nullable=True))
        if 'icon' not in columns:
            batch_op.add_column(sa.Column('icon', sa.String(length=50), nullable=True))
        if 'totem_window' not in columns:
            batch_op.add_column(sa.Column('totem_window', sa.String(length=20), nullable=True))

    # Backfill: auditórios continuam exibindo a semana no totem; todo o resto,
    # o período atual. Ícone/cor só preenchem quem ainda não tem.
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE room_categories SET totem_window = 'period' WHERE totem_window IS NULL"))
    conn.execute(sa.text(
        "UPDATE room_categories SET totem_window = 'week' WHERE code = 'auditorium'"))
    for code, (icon, color) in _DEFAULTS_BY_CODE.items():
        conn.execute(
            sa.text(
                'UPDATE room_categories SET icon = :icon, color = :color '
                'WHERE code = :code AND icon IS NULL'
            ),
            {'icon': icon, 'color': color, 'code': code},
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'room_categories' not in inspector.get_table_names():
        return
    columns = [c['name'] for c in inspector.get_columns('room_categories')]
    with op.batch_alter_table('room_categories', schema=None) as batch_op:
        if 'totem_window' in columns:
            batch_op.drop_column('totem_window')
        if 'icon' in columns:
            batch_op.drop_column('icon')
        if 'color' in columns:
            batch_op.drop_column('color')
