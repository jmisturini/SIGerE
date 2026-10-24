"""bloqueio de conta por excesso de tentativas de login

Revision ID: a7d3e9f1c5b8
Revises: cd04617d1484
Create Date: 2026-10-24 21:30:00.000000

Colunas do bloqueio de acesso (CWE-307): contador de falhas de login,
flag de bloqueio e momento do bloqueio. Contas existentes nascem
desbloqueadas e com contador zerado (server_default). Sem
auto-desbloqueio por tempo — o retorno é só com ação de quem tem user:lock.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7d3e9f1c5b8'
down_revision = 'cd04617d1484'
branch_labels = None
depends_on = None


def _tem_coluna(inspector, tabela, coluna):
    return coluna in [c['name'] for c in inspector.get_columns(tabela)]


def upgrade():
    inspector = sa.inspect(op.get_bind())

    with op.batch_alter_table('users', schema=None) as batch_op:
        if not _tem_coluna(inspector, 'users', 'failed_login_attempts'):
            batch_op.add_column(sa.Column('failed_login_attempts', sa.Integer(),
                                          nullable=False, server_default='0'))
        if not _tem_coluna(inspector, 'users', 'is_locked'):
            # Booleano com server_default booleano (sa.false()), nunca 0/1 em
            # SQL cru — cada diaconete expande para o literal correto.
            batch_op.add_column(sa.Column('is_locked', sa.Boolean(),
                                          nullable=False, server_default=sa.false()))
        if not _tem_coluna(inspector, 'users', 'locked_at'):
            batch_op.add_column(sa.Column('locked_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('locked_at')
        batch_op.drop_column('is_locked')
        batch_op.drop_column('failed_login_attempts')
