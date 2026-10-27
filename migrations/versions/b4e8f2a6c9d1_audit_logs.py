"""tabela audit_logs (trilha de auditoria no painel)

Revision ID: b4e8f2a6c9d1
Revises: a7d3e9f1c5b8
Create Date: 2026-10-25 12:00:00.000000

Cria audit_logs — a trilha de auditoria de segurança que app.utils.auditar
grava a cada evento sensível (login, troca/reset de senha, bloqueios e ciclo
de usuários), consultável no Painel Admin (/admin/auditoria). O ator tem
snapshot por e-mail; o FK para users usa SET NULL para o histórico sobreviver
à eventual remoção da conta.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b4e8f2a6c9d1'
down_revision = 'a7d3e9f1c5b8'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())

    if 'audit_logs' in inspector.get_table_names():
        # Recusar: se a revisão for registrada com a tabela preexistente
        # ignorada, um downgrade posterior executaria drop_table e apagaria
        # histórico que esta revisão não criou. Conciliar manualmente (db
        # stamp b4e8f2a6c9d1 se a tabela já é a da trilha) antes de seguir.
        raise RuntimeError(
            "A tabela 'audit_logs' já existe e a revisão b4e8f2a6c9d1 não "
            "está aplicada. A origem dela é desconhecida (criada fora desta "
            "migração) — concilie manualmente antes de prosseguir para o "
            "downgrade não apagar um histórico que não foi criado aqui.")
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('evento', sa.String(50), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_email', sa.String(120), nullable=True),
        sa.Column('alvo', sa.String(120), nullable=True),
        sa.Column('ip', sa.String(45), nullable=True),
        sa.Column('detalhes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_audit_logs_created_at', 'audit_logs', ['created_at'])
    op.create_index('ix_audit_logs_evento', 'audit_logs', ['evento'])


def downgrade():
    op.drop_table('audit_logs')
