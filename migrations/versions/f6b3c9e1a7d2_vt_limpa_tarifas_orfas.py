"""vt: limpa tarifas orfas e repetidas sem identificacao

Revision ID: f6b3c9e1a7d2
Revises: c4f8a9d2e6b3
Create Date: 2026-09-18 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f6b3c9e1a7d2'
down_revision = 'c4f8a9d2e6b3'
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if 'vt_empresas_valores' not in tables or 'vt_empresas' not in tables:
        return

    # O SQLite não valida a chave estrangeira por padrão: exclusões feitas
    # fora do aplicativo (SQL direto, migração interrompida) deixaram
    # tarifas sem empresa dona — e, com o id reutilizado ao cadastrar de
    # novo, a tarifa órfã "reatava" à empresa nova como linha fantasma.
    op.execute('DELETE FROM vt_empresas_valores '
               'WHERE empresa_id IS NULL '
               'OR empresa_id NOT IN (SELECT id FROM vt_empresas)')

    # Fantasma já reanexada (o id da empresa voltou a existir): tarifa sem
    # identificação cujo valor já existe identificado na MESMA empresa é
    # duplicata — o formulário público ofereceria a tarifa duas vezes. As
    # linhas legadas da carga inicial (sem identificação, valores distintos
    # entre si) não têm par identificado e ficam intactas.
    op.execute('DELETE FROM vt_empresas_valores '
               'WHERE (identificacao IS NULL OR identificacao = \'\') '
               'AND EXISTS ('
               'SELECT 1 FROM vt_empresas_valores AS v2 '
               'WHERE v2.empresa_id = vt_empresas_valores.empresa_id '
               'AND v2.id <> vt_empresas_valores.id '
               'AND v2.identificacao IS NOT NULL AND v2.identificacao <> \'\' '
               'AND v2.valor = vt_empresas_valores.valor)')


def downgrade():
    # Tarifas órfãs/duplicatas não têm como voltar: a limpeza é definitiva.
    pass
