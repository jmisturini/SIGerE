"""vt: tabela de empresas de onibus e tarifas do pedido publico

Revision ID: c8d4a1e6f2b9
Revises: b5e2f7a9c4d1
Create Date: 2026-09-17 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c8d4a1e6f2b9'
down_revision = 'b5e2f7a9c4d1'
branch_labels = None
depends_on = None

# Foto das opções fixas que viraram dados (as tarifas vigentes até esta
# versão, do formulário original do Microsoft Forms). A carga só acontece
# se a tabela estiver vazia — empresas excluídas pelo admin não voltam.
EMPRESAS_INICIAIS = {
    'Consórcio Fênix': ['7,20'],
    'Jotur': ['7,24', '7,38', '10,10', '12,08'],
    'Biguaçu': ['7,24', '7,38', '10,10', '10,23', '12,08'],
    'Estrela': ['7,24', '7,38', '10,10'],
}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if 'vt_empresas' in tables:
        return
    op.create_table('vt_empresas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=100), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('vt_empresas_valores',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('empresa_id', sa.Integer(), nullable=False),
    sa.Column('valor', sa.Numeric(10, 2), nullable=False),
    sa.ForeignKeyConstraint(['empresa_id'], ['vt_empresas.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vt_empresas_valores_empresa_id'), 'vt_empresas_valores',
                    ['empresa_id'], unique=False)

    connection = op.get_bind()
    if connection.execute(sa.text('SELECT COUNT(*) FROM vt_empresas')).scalar() == 0:
        # Insert via construct do SQLAlchemy: o booleano é compilado por
        # dialeto e o id da PK volta portável (lastrowid não existe no
        # PostgreSQL/psycopg2). A PK precisa estar declarada para o
        # inserted_primary_key funcionar.
        vt_empresas = sa.Table(
            'vt_empresas', sa.MetaData(),
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('nome', sa.String(100)),
            sa.Column('is_active', sa.Boolean()))
        for nome, tarifas in EMPRESAS_INICIAIS.items():
            empresa_id = connection.execute(
                vt_empresas.insert().values(nome=nome, is_active=True)
            ).inserted_primary_key[0]
            for tarifa in tarifas:
                valor = float(tarifa.replace(',', '.'))
                connection.execute(
                    sa.text('INSERT INTO vt_empresas_valores (empresa_id, valor) '
                            'VALUES (:empresa_id, :valor)'),
                    {'empresa_id': empresa_id, 'valor': valor})


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'vt_empresas' not in inspector.get_table_names():
        return
    op.drop_index(op.f('ix_vt_empresas_valores_empresa_id'),
                  table_name='vt_empresas_valores')
    op.drop_table('vt_empresas_valores')
    op.drop_table('vt_empresas')
