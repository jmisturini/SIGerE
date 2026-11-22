"""Serviço central de agendamento — validações e gravação atômica de reservas.

Ponto único para as regras de reserva (conflito de sala/docente, feriados,
domingos e sábado após 18h) e para a proteção da condição de corrida entre a
checagem de conflito e o INSERT (padrão TOCTOU: duas requisições leem "sala
livre" simultaneamente e ambas gravam).

Mecanismos de proteção por ambiente:
- Todos os bancos: lock de processo por (sala, data) — serializa a janela
  checagem→gravação entre threads do mesmo processo.
- PostgreSQL: adicionalmente `SELECT ... FOR UPDATE` nas queries de conflito
  e advisory lock transacional por (sala, data), cobrindo múltiplos processos.
- SQLite: o lock de processo é o mecanismo efetivo (o banco já serializa
  escritas entre processos no nível do arquivo).
"""
import threading
from contextlib import contextmanager
from datetime import datetime, time, timedelta

from sqlalchemy import text

from app.extensions import db
from app.models import Reservation, Holiday, EVENT_RESERVATION_CANCELLED
from app.unity_context import current_unity_id

# ── Locks por (sala, data) ───────────────────────────────────────────────────
_slot_locks = {}
_slot_locks_guard = threading.Lock()

# Limite do intervalo da repetição de reservas (protege contra lotes enormes
# de Inserts e contra telas que iterariam milhares de dias).
MAX_REPEAT_RANGE_DAYS = 180


def _lock_key(classroom_id, d):
    date_str = d.isoformat() if hasattr(d, 'isoformat') else str(d)
    return (classroom_id, date_str)


@contextmanager
def slot_locks(classroom_id, dates):
    """Context manager: trava todas as (sala, data) envolvidas na operação.

    As chaves são adquiridas em ordem canônica para evitar deadlock quando
    uma operação em lote cruza datas com outra operação concorrente.
    """
    keys = sorted({_lock_key(classroom_id, d) for d in dates})

    def _acquire_all():
        with _slot_locks_guard:
            return [_slot_locks.setdefault(k, threading.RLock()) for k in keys]

    acquired = []
    try:
        for lock in _acquire_all():
            lock.acquire()
            acquired.append(lock)
        if db.engine.name == 'postgresql':
            # Advisory lock por slot: estende a proteção a múltiplos processos
            # (liberada no commit/rollback da transação da requisição).
            for classroom_id_, date_str in keys:
                db.session.execute(text(
                    'SELECT pg_advisory_xact_lock(hashtext(:k)::bigint)'),
                    {'k': f'reserva:{classroom_id_}:{date_str}'})
        yield
    finally:
        for lock in reversed(acquired):
            lock.release()


# ── Validações ───────────────────────────────────────────────────────────────

def check_conflict(classroom_id, reservation_date, start_time, end_time,
                   exclude_id=None):
    """Sala já possui reserva aprovada sobreposta no dia? (janela semiaberta:
    fim == início do outro NÃO conflita)."""
    query = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date == reservation_date,
        Reservation.status == 'approved',
        Reservation.start_time < end_time,
        Reservation.end_time > start_time
    )
    if exclude_id:
        query = query.filter(Reservation.id != exclude_id)
    # FOR UPDATE: trava as linhas conflitantes (efetivo em PostgreSQL;
    # ignorado pelo dialeto SQLite).
    return query.with_for_update(of=Reservation).first()


def check_teacher_conflict(teacher_id, reservation_date, start_time, end_time,
                           exclude_id=None):
    """Docente já possui reserva aprovada/pendente sobreposta no dia?"""
    query = Reservation.query.filter(
        Reservation.teacher_id == teacher_id,
        Reservation.date == reservation_date,
        Reservation.status.in_(['approved', 'pending']),
        Reservation.start_time < end_time,
        Reservation.end_time > start_time
    )
    if exclude_id:
        query = query.filter(Reservation.id != exclude_id)
    return query.first()


# ── Regra de carga docente ───────────────────────────────────────────────────
# Mais de TEACHER_DAILY_RESERVATION_LIMIT reservas ativas (aprovadas +
# pendentes) do mesmo docente no dia leva a reserva nova/editada a PENDENTE
# para avaliação — a agenda do professor ficou carregada demais.

TEACHER_DAILY_RESERVATION_LIMIT = 2


def count_teacher_reservations(teacher_id, reservation_date, exclude_id=None):
    """Reservas ativas (approved/pending) do docente no dia — base da regra
    de carga diária. Ainda não gravada na seção crítica, contar com exclude_id
    da própria reserva na edição; na criação ela ainda não existe no banco."""
    query = Reservation.query.filter(
        Reservation.teacher_id == teacher_id,
        Reservation.date == reservation_date,
        Reservation.status.in_(['approved', 'pending']),
    )
    if exclude_id:
        query = query.filter(Reservation.id != exclude_id)
    return query.count()


def teacher_exceeds_daily_limit(teacher_id, reservation_date, exclude_id=None):
    """True se a reserva em julgamento leva o docente além do limite diário:
    já existem TEACHER_DAILY_RESERVATION_LIMIT reservas ativas dele no dia
    (esta nova completa mais de LIMIT)."""
    return count_teacher_reservations(teacher_id, reservation_date,
                                      exclude_id) >= TEACHER_DAILY_RESERVATION_LIMIT


def check_schedule_restrictions(res_date, start_time, end_time=None):
    """Regras de calendário: domingos, feriados cadastrados na unidade e
    sábado após 18:00 (o fim da reserva também deve caber até 18:00)."""
    unity_id = current_unity_id()  # feriados são cadastrados por unidade
    if isinstance(res_date, str):
        try:
            res_date = datetime.strptime(res_date, '%Y-%m-%d').date()
        except ValueError:
            pass

    weekday = res_date.weekday()

    # 1. Block Sundays
    if weekday == 6:
        return False, "Reservas não podem ser agendadas aos domingos."

    # 2. Block Holidays (Query Database)
    holiday = Holiday.query.filter_by(date=res_date, is_active=True,
                                      unity_id=unity_id).first()
    if holiday:
        return False, f"Reservas não podem ser agendadas em feriados ({holiday.name})."

    # 3. Block Saturday Nights (after 18:00 — início OU término após 18h)
    if weekday == 5:
        late_start = start_time is not None and start_time >= time(18, 0)
        late_end = end_time is not None and end_time > time(18, 0)
        if late_start or late_end:
            return False, "Aos sábados, as reservas são permitidas apenas pela manhã e tarde (até 18:00)."

    return True, ""


# ── Cancelamento automático de pendências ────────────────────────────────────
# Pendência sem aprovação até 1 hora antes do início vira cancelada: a esta
# altura uma aprovação tardia não tem mais função prática (avisos de 1h já
# teriam saído para os participantes de uma reserva que ninguém confirmou).
ANTECEDENCIA_AUTOCANCEL = timedelta(hours=1)


def autocancelar_pendentes(agora=None, dry_run=False):
    """Cancela as reservas pending não aprovadas até ANTECEDENCIA_AUTOCANCEL
    (1h) antes do início — inclui as cujo início já passou (timer parado ou
    fim de semana: pendência vencida nunca mais será aprovada).

    Cada cancelamento avisa o criador pelo mesmo aviso de mudança de status
    dos cancelamentos manuais (notificar_mudanca_status), com o motivo do
    cancelamento automático no corpo — é uma ação do sistema, então o criador
    sempre recebe (não há ator). Com dry_run=True nada é gravado, mas a
    prévia conta os avisos exatamente como a execução real os criaria.
    A gravação revalida o status no próprio UPDATE (só pendência vira
    cancelada), então uma reserva aprovada por outra sessão durante a
    varredura não é sobrescrita. Retorna estatísticas para o log do comando;
    idempotente (rodar de novo não faz nada — as pendências vencidas já
    saíram da fila).
    """
    # Import local: notifications importa este módulo (count_teacher_reservations).
    from app.services.notifications import (_MILESTONE_STATUS,
                                            _notificacao_existente,
                                            notificar_mudanca_status)

    agora = agora or datetime.now()
    limite = agora + ANTECEDENCIA_AUTOCANCEL
    stats = {'avaliadas': 0, 'canceladas': 0, 'avisos': 0}

    # Candidatos pré-filtrados por data (portátil SQLite/PostgreSQL); o corte
    # fino por (data, hora de início) é feito em Python no combine.
    candidatos = Reservation.query.filter(
        Reservation.status == 'pending',
        Reservation.date <= limite.date(),
    ).all()

    for reservation in candidatos:
        inicio = datetime.combine(reservation.date, reservation.start_time)
        if inicio > limite:
            continue
        stats['avaliadas'] += 1
        if dry_run:
            stats['canceladas'] += 1
            # Elegibilidade do aviso, sem gravar: mesmo critério da função
            # de notificação (criador ativo e sem aviso de cancelamento).
            criador = reservation.user
            if (criador is not None and criador.is_active_user
                    and not _notificacao_existente(
                        criador.id, reservation.id, _MILESTONE_STATUS,
                        EVENT_RESERVATION_CANCELLED)):
                stats['avisos'] += 1
            continue
        # Revalidação atômica na gravação: entre a consulta dos candidatos e
        # aqui a reserva pode ter sido aprovada em outra sessão — ou remarcada
        # (editar muda date/start_time mantendo pending). O filtro repete id,
        # status E o horário avaliado: só cancela quem continua sendo a
        # pendência vencida, e o rowcount diz se a linha mudou ('fetch'
        # espelha o novo status na instância da sessão para o aviso).
        afetadas = Reservation.query.filter(
            Reservation.id == reservation.id,
            Reservation.status == 'pending',
            Reservation.date == reservation.date,
            Reservation.start_time == reservation.start_time,
        ).update({'status': 'cancelled'}, synchronize_session='fetch')
        if not afetadas:
            continue
        stats['canceladas'] += 1
        stats['avisos'] += notificar_mudanca_status(
            reservation, 'pending',
            motivo='Não houve aprovação até 1 hora antes do horário agendado.')

    if not dry_run:
        db.session.commit()
    return stats
