"""remove users.username: login passa a ser pelo e-mail

Revision ID: e2c9a7d5f8b1
Revises: b3d8f7a2c6e1
Create Date: 2026-09-14 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2c9a7d5f8b1'
down_revision = 'b3d8f7a2c6e1'
branch_labels = None
depends_on = None


def _tem_coluna(inspector, tabela, coluna):
    return coluna in [c['name'] for c in inspector.get_columns(tabela)]


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not _tem_coluna(inspector, 'users', 'username'):
        return
    # SQLite não permite DROP COLUMN fora do batch mode; o batch recria a
    # tabela users sem a coluna, preservando os dados restantes. O índice
    # único precisa cair DENTRO do batch: recriado junto com a tabela, ele
    # referenciaria uma coluna que não existe mais.
    indices = {i['name'] for i in inspector.get_indexes('users')}
    with op.batch_alter_table('users') as batch_op:
        if 'ix_users_username' in indices:
            batch_op.drop_index('ix_users_username')
        batch_op.drop_column('username')


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if _tem_coluna(inspector, 'users', 'username'):
        return
    # ALTER TABLE ADD COLUMN é suportado nativamente pelo SQLite; o índice
    # único sai por último, fora do batch (dentro dele o índice seria criado
    # antes da coluna existir na tabela recriada).
    op.add_column('users',
                  sa.Column('username', sa.String(length=64), nullable=False,
                            server_default=''))
    # Repõe usernames pela convenção antiga (prefixo do e-mail) e desambigua
    # colisões com o id — o índice único exige valores distintos.
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE users SET username = substr(email, 1, instr(email, '@') - 1)"))
    bind.execute(sa.text(
        "UPDATE users SET username = username || '_' || id "
        "WHERE id NOT IN (SELECT MIN(id) FROM users GROUP BY username)"))
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
