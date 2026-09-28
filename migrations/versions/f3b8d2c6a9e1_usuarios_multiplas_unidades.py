"""usuários com múltiplas unidades (user_unities N:N)

Revision ID: f3b8d2c6a9e1
Revises: e7d5a9c3b1f8
Create Date: 2026-09-27 10:00:00.000000

A coluna única users.unity_id vira a tabela de junção user_unities: o mesmo
professor ou funcionário pode atuar em várias unidades. O vínculo existente
de cada usuário é preservado como primeira linha da associação; contas sem
unidade (globais, ex: super admin) continuam sem linhas.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f3b8d2c6a9e1'
down_revision = 'e7d5a9c3b1f8'
branch_labels = None
depends_on = None


def _tem_coluna(inspector, tabela, coluna):
    return coluna in [c['name'] for c in inspector.get_columns(tabela)]


def _tem_tabela(inspector, tabela):
    return tabela in inspector.get_table_names()


def upgrade():
    inspector = sa.inspect(op.get_bind())

    if not _tem_tabela(inspector, 'user_unities'):
        op.create_table(
            'user_unities',
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('unity_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['unity_id'], ['unities.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('user_id', 'unity_id'),
        )
        op.create_index('ix_user_unities_unity_id', 'user_unities', ['unity_id'])

    if _tem_coluna(inspector, 'users', 'unity_id'):
        # Copy do vínculo único para a associação — INSERT...SELECT gerado pelo
        # Core (portável SQLite/PostgreSQL); um usuário tem no máx. 1 linha.
        users = sa.table('users',
                         sa.column('id', sa.Integer),
                         sa.column('unity_id', sa.Integer))
        vinculos = sa.table('user_unities',
                            sa.column('user_id', sa.Integer),
                            sa.column('unity_id', sa.Integer))
        op.execute(vinculos.insert().from_select(
            ['user_id', 'unity_id'],
            sa.select(users.c.id, users.c.unity_id)
            .where(users.c.unity_id.isnot(None)),
        ))
        # SQLite não permite DROP COLUMN fora do batch mode; o batch recria a
        # tabela users sem a coluna, preservando os dados restantes.
        inspector = sa.inspect(op.get_bind())
        indices = {i['name'] for i in inspector.get_indexes('users')}
        with op.batch_alter_table('users') as batch_op:
            if 'ix_users_unity_id' in indices:
                batch_op.drop_index('ix_users_unity_id')
            batch_op.drop_column('unity_id')


def downgrade():
    inspector = sa.inspect(op.get_bind())

    if not _tem_coluna(inspector, 'users', 'unity_id'):
        # ALTER TABLE ADD COLUMN é suportado nativamente pelo SQLite.
        op.add_column('users', sa.Column('unity_id', sa.Integer(), nullable=True))
        # Repõe UM vínculo por usuário (o de menor unity_id — determinístico).
        op.get_bind().execute(sa.text(
            'UPDATE users SET unity_id = (SELECT MIN(unity_id) FROM user_unities '
            'WHERE user_unities.user_id = users.id)'))
        # Restaura a FK original recriando a tabela via batch (nativo no
        # PostgreSQL; no SQLite o batch recria a tabela com a constraint).
        with op.batch_alter_table('users') as batch_op:
            batch_op.create_foreign_key('fk_users_unity_id_unities',
                                        'unities', ['unity_id'], ['id'])

    if _tem_tabela(inspector, 'user_unities'):
        op.drop_table('user_unities')
