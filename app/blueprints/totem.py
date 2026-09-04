import re
from flask import Blueprint, render_template, request, abort
from app.models import Classroom, Reservation, RoomCategory, Unity
from datetime import date, time, datetime, timedelta

bp = Blueprint('totem', __name__, url_prefix='/totem')

def _totem_unity():
    """Unidade exibida no totem: ?unity=<id> ou a primeira ativa (fallback)."""
    unity_id = request.args.get('unity', type=int)
    if unity_id:
        unity = Unity.query.filter_by(id=unity_id, is_active=True).first()
        if unity:
            return unity
        abort(404)
    return Unity.query.filter_by(is_active=True).order_by(Unity.name).first()

@bp.route('/')
def display():
    unity = _totem_unity()
    if unity is None:
        # Sem unidades cadastradas, não há o que exibir
        return render_template('totem.html', aud_reservations=[], classroom_floors={}, current_period='—')

    today = date.today()
    now = datetime.now()

    # Determine current period
    if now.hour < 12:
        p_start, p_end, current_period = time(0, 0), time(12, 0), "Manhã"
    elif now.hour < 18:
        p_start, p_end, current_period = time(12, 0), time(18, 0), "Tarde"
    else:
        p_start, p_end, current_period = time(18, 0), time(23, 59), "Noite"

    # 1. Fetch Auditoriums for the next 7 days (da unidade do totem)
    week_end = today + timedelta(days=7)
    aud_reservations = Reservation.query.join(Classroom).filter(
        Classroom.unity_id == unity.id,
        Classroom.category.has(RoomCategory.code == 'auditorium'),
        Reservation.date >= today,
        Reservation.date <= week_end,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()

    # 2. Fetch Classrooms for today's current period (da unidade do totem)
    cls_reservations = Reservation.query.join(Classroom).filter(
        Classroom.unity_id == unity.id,
        Classroom.category.has(RoomCategory.code != 'auditorium'),
        Reservation.date == today,
        Reservation.status == 'approved',
        Reservation.start_time < p_end,
        Reservation.end_time > p_start
    ).order_by(Classroom.code).all()

    # Group classrooms by the first number in the room code
    grouped_classrooms = {}
    for r in cls_reservations:
        # CORREÇÃO: Usar o campo 'floor' do banco de dados em vez de regex
        floor_name = r.classroom.floor or "Outros"

        if floor_name not in grouped_classrooms: grouped_classrooms[floor_name] = []
        grouped_classrooms[floor_name].append(r)

    floor_order = {"Térreo": 0, "1º Andar": 1, "2º Andar": 2, "3º Andar": 3, "4º Andar": 4, "5º Andar": 5}
    sorted_floors = dict(sorted(grouped_classrooms.items(), key=lambda item: floor_order.get(item[0], 99)))

    # Lista de unidades para alternância rápida no painel (ex: uma TV por unidade)
    unities = Unity.query.filter_by(is_active=True).order_by(Unity.name).all()

    return render_template('totem.html', aud_reservations=aud_reservations,
                           classroom_floors=sorted_floors, current_period=current_period,
                           totem_unity=unity, totem_unities=unities)
