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
from datetime import datetime, time

from sqlalchemy import text

from app.extensions import db
from app.models import Reservation, Holiday
from app.unity_context import current_unity_id

# ── Locks por (sala, data) ───────────────────────────────────────────────────
_slot_locks = {}
_slot_locks_guard = threading.Lock()


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
