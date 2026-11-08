"""Tipo de curso do lançamento de Hora Extra vira texto livre.

O campo era FK para o catálogo course_types (dropdown do formulário); o
formulário hoje aceita texto livre. A migração copia o nome do tipo para a
nova coluna course_type, preservando o histórico, e remove o FK.

Revision ID: d1a5f8c2b7e9
Revises: b4e8f2a6c9d1
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'd1a5f8c2b7e9'
down_revision = 'b4e8f2a6c9d1'
branch_labels = None
depends_on = None


def upgrade():
    """Texto livre substitui o FK: cria course_type, copia o nome do catálogo
    para preservar o histórico dos lançamentos existentes e remove o FK."""
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.add_column(sa.Column('course_type', sa.String(60), nullable=True))
    # Preserva o histórico: o texto recebe o nome do antigo catálogo.
    op.execute("""
        UPDATE teacher_overtime_pay
        SET course_type = (SELECT ct.name FROM course_types ct
                           WHERE ct.id = teacher_overtime_pay.course_type_id)
    """)
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.drop_column('course_type_id')


def downgrade():
    """Recria o FK e re-liga os lançamentos pelo nome exato no catálogo.

    Com correspondência faltando, aborta ANTES de alterar o schema — sem a
    guarda, o drop da coluna course_type descartaria o texto original. No
    PostgreSQL, trava lançamentos e catálogo para a verificação e a
    re-conversão viverem sem escritas concorrentes."""
    # A volta ao catálogo só é segura com correspondência exata para todo
    # lançamento: sem ela, o FK ficaria nulo e o drop da coluna course_type
    # descartaria o texto original — perda permanente. No PostgreSQL, trava
    # as duas tabelas: escritas nos lançamentos (um INSERT confirmado entre a
    # checagem e a re-conversão burlaria a verificação) e renames/apagões no
    # catálogo (um UPDATE em course_types entre a checagem e a re-conversão
    # quebraria o casamento pelo nome); no SQLite o gravador é único por
    # natureza. Aborta ANTES de alterar o schema, listando os valores sem
    # correspondência.
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute('LOCK TABLE teacher_overtime_pay IN EXCLUSIVE MODE')
        op.execute('LOCK TABLE course_types IN SHARE MODE')
    sem_correspondencia = bind.execute(sa.text("""
        SELECT DISTINCT course_type FROM teacher_overtime_pay
        WHERE course_type IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM course_types ct
                          WHERE ct.name = teacher_overtime_pay.course_type)
        ORDER BY course_type
    """)).scalars().all()
    if sem_correspondencia:
        raise RuntimeError(
            'Downgrade abortado antes de alterar o schema: há lançamentos de '
            'Hora Extra com "Tipo de Curso" sem correspondência exata no '
            'catálogo (course_types): '
            + ', '.join(repr(v) for v in sem_correspondencia)
            + '. Preserve-os antes de reexecutar (ex.: cadastre os tipos no '
            'catálogo com o mesmo nome, ou ajuste os lançamentos).')

    # Best effort: re-liga os lançamentos ao catálogo pelo nome exato; sem
    # correspondência, o FK fica nulo (coluna sempre foi nullable).
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'course_type_id', sa.Integer(),
            sa.ForeignKey('course_types.id'), nullable=True))
    op.execute("""
        UPDATE teacher_overtime_pay
        SET course_type_id = (SELECT ct.id FROM course_types ct
                              WHERE ct.name = teacher_overtime_pay.course_type)
    """)
    with op.batch_alter_table('teacher_overtime_pay', schema=None) as batch_op:
        batch_op.drop_column('course_type')
