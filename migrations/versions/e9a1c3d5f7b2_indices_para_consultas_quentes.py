"""Índices para as consultas quentes e FKs sem índice

Cria os índices que faltam para os filtros mais acessados da aplicação e as
foreign keys que o PostgreSQL não indexa sozinho (usadas em JOIN, filtro e
cascatas de ON DELETE). Validado com EXPLAIN (ANALYZE, BUFFERS) numa base de
testes com volume de produção (~160 mil reservas, ~220 mil notificações):

- Painel do dia (/dashboard) e contador de pendências: caíram de 6,2 ms com
  bitmap de 53 mil linhas da unidade para ~0,1 ms (Index Only Scan).
- Calendário (/calendar/api/events) e listagem /reservations/all (incluindo o
  count(*) da paginação): de 6,5 ms / 2935 buffers para 1,2 ms / 22 buffers.
- Sino de notificações (lista das últimas): de 3,2 ms para 0,35 ms.
- Dreno de e-mail (notify-email): de 24,4 ms com Parallel Seq Scan para
  0,7 ms (índice parcial na fila).
- Login e validações de e-mail (WHERE lower(email) = ...): Seq Scan de tabela
  inteira passa a busca por índice de expressão.
- Hora Extra/Vale Alimentação/Adicional Noturno (filtro por mês): busca direta
  por (unity_id, month_base).
- Auditoria com filtro de evento: de varredura com filtro tardio para leitura
  direta das 20 linhas da página.

Notas de operação:
- Em bases de produção com muitas reservas, criar os índices de `reservations`
  e `notifications` fora do horário de pico; se estiver sob janela curta,
  considerar CREATE INDEX CONCURRENTLY (fora deste arquivo, que mantém o
  padrão transacional do repo).
- O índice idx_users_email_lower complementa (não substitui) o índice único
  simples de users.email, que continua garantindo a unicidade.

Revision ID: e9a1c3d5f7b2
Revises: c8a2e6b9d4f7
Create Date: 2026-11-17 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e9a1c3d5f7b2'
down_revision = 'c8a2e6b9d4f7'
branch_labels = None
depends_on = None


# (nome, tabela, colunas/expressões, kwargs extras) — a ordem segue o ganho
# medido: primeiro os compostos de `reservations` e `notifications`, depois os
# de financeiro/auditoria, e por último a higiene de FKs.
INDICES = (
    # ── reservations: filtros por unidade+data+status e por criador ──────────
    # Painel do dia, calendário, /reservations/all (listagem + count da
    # paginação) e relatório geral: WHERE unity_id = ? [AND date ...] [AND
    # status ...] ORDER BY date, start_time.
    ('idx_reservations_unity_date_status', 'reservations',
     ['unity_id', 'date', 'status'], {}),
    # Painel do dia (ORDER BY start_time sem sort) e contador de pendências da
    # unidade (Index Only Scan): WHERE unity_id = ? AND status = ? [AND date
    # >= hoje].
    ('idx_reservations_unity_status_date_start', 'reservations',
     ['unity_id', 'status', 'date', 'start_time'], {}),
    # Minhas reservas: WHERE user_id = ? OR teacher_id = ? AND date >= ? — o
    # lado do teacher já tem idx_reservation_teacher_date; o do user_id não
    # tinha nenhum (o OR caía em varredura por data descartando ~96% das
    # linhas).
    ('idx_reservations_user_date', 'reservations', ['user_id', 'date'], {}),
    # Filtros de curso/disciplina da listagem e calendário; também FKs sem
    # índice (course/subject com ondelete SET NULL).
    ('idx_reservations_course_id', 'reservations', ['course_id'], {}),
    ('idx_reservations_subject_id', 'reservations', ['subject_id'], {}),

    # ── notifications: sino e fila de e-mail ────────────────────────────────
    # Lista do sino (/notificacoes e /api/recentes): WHERE user_id = ? ORDER
    # BY created_at DESC, id DESC LIMIT 50 — o índice existente
    # ix_notifications_user_read cobre só o badge de não lidas.
    ('idx_notifications_user_created', 'notifications',
     ['user_id', sa.text('created_at DESC'), sa.text('id DESC')], {}),
    # Dreno de e-mail (notify-email): WHERE sent_at IS NULL AND
    # send_attempts < 10 ORDER BY created_at LIMIT N — índice parcial evita
    # Seq Scan de toda a tabela (a fila é uma fração minúscula do total).
    ('idx_notifications_mail_queue', 'notifications', ['created_at'],
     {'postgresql_where': sa.text('sent_at IS NULL'),
      'sqlite_where': sa.text('sent_at IS NULL')}),

    # ── usuários: login e validações por e-mail em minúsculas ───────────────
    # auth.login, UserForm.validate_email, /vt/pedido e reset-password usam
    # WHERE lower(email) = ?, que o índice único simples não atende.
    ('idx_users_email_lower', 'users', [sa.text('lower(email)')], {}),

    # ── financeiro: filtro por mês dentro da unidade ────────────────────────
    # Listagens de Hora Extra, Vale Alimentação e Adicional Noturno:
    # WHERE unity_id = ? [AND month_base = ?] ORDER BY month_base ...
    ('idx_teacher_overtime_pay_unity_month', 'teacher_overtime_pay',
     ['unity_id', 'month_base'], {}),
    ('idx_teacher_meal_allowances_unity_month', 'teacher_meal_allowances',
     ['unity_id', 'month_base'], {}),
    ('idx_teacher_night_shift_pay_unity_month', 'teacher_night_shift_pay',
     ['unity_id', 'month_base'], {}),
    # Filtro por docente nas listagens de Hora Extra/Vale Alimentação
    # (filter_teacher) — também FK sem índice.
    ('idx_teacher_overtime_pay_teacher_id', 'teacher_overtime_pay',
     ['teacher_id'], {}),
    ('idx_teacher_meal_allowances_teacher_id', 'teacher_meal_allowances',
     ['teacher_id'], {}),

    # ── auditoria: listagem com filtro de evento ────────────────────────────
    # /admin/auditoria: WHERE evento = ? ORDER BY created_at DESC, id DESC
    ('idx_audit_logs_evento_created', 'audit_logs',
     ['evento', sa.text('created_at DESC'), sa.text('id DESC')], {}),

    # ── higiene de FKs (JOIN/cascata; o PostgreSQL não indexa FKs sozinho) ──
    ('idx_users_role_id', 'users', ['role_id'], {}),
    ('idx_subjects_course_id', 'subjects', ['course_id'], {}),
    ('idx_classrooms_category_id', 'classrooms', ['category_id'], {}),
    ('idx_audit_logs_actor_id', 'audit_logs', ['actor_id'], {}),
    ('idx_api_tokens_created_by_id', 'api_tokens', ['created_by_id'], {}),
    ('idx_technical_sheets_uploaded_by_id', 'technical_sheets',
     ['uploaded_by_id'], {}),
    ('idx_kitchen_recipes_technical_sheet_id', 'kitchen_recipes',
     ['technical_sheet_id'], {}),
    ('idx_overtime_month_closures_closed_by_id', 'overtime_month_closures',
     ['closed_by_id'], {}),
    ('idx_teacher_meal_allowances_created_by_id', 'teacher_meal_allowances',
     ['created_by_id'], {}),
    ('idx_teacher_night_shift_pay_created_by_id', 'teacher_night_shift_pay',
     ['created_by_id'], {}),
    ('idx_teacher_overtime_pay_accountable_id', 'teacher_overtime_pay',
     ['accountable_id'], {}),
    # Segunda coluna das tabelas de junção N:N — sem ela, apagar um papel/
    # usuário/unidade/grupo/categoria varre a tabela inteira para achar as
    # linhas de cascata (a primeira coluna já é coberta pela PK composta).
    ('idx_role_permissions_permission_id', 'role_permissions',
     ['permission_id'], {}),
    ('idx_user_roles_role_id', 'user_roles', ['role_id'], {}),
    ('idx_user_unities_unity_id', 'user_unities', ['unity_id'], {}),
    ('idx_notification_group_members_user_id', 'notification_group_members',
     ['user_id'], {}),
    ('idx_reservation_notification_groups_group_id',
     'reservation_notification_groups', ['group_id'], {}),
    ('idx_reservation_notification_users_user_id',
     'reservation_notification_users', ['user_id'], {}),
    ('idx_user_notification_muted_categories_category_id',
     'user_notification_muted_categories', ['category_id'], {}),
    ('idx_notification_config_overload_groups_group_id',
     'notification_config_overload_groups', ['group_id'], {}),
)


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tabelas = set(inspector.get_table_names())
    for nome, tabela, colunas, kwargs in INDICES:
        if tabela not in tabelas:
            continue  # instalação antiga sem esta tabela
        if nome in {i['name'] for i in inspector.get_indexes(tabela)}:
            continue  # índice já existe (migração idempotente)
        op.create_index(nome, tabela, colunas, **kwargs)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    tabelas = set(inspector.get_table_names())
    for nome, tabela, _, _ in reversed(INDICES):
        if tabela not in tabelas:
            continue
        if nome not in {i['name'] for i in inspector.get_indexes(tabela)}:
            continue
        op.drop_index(nome, tabela)
