import re
from flask import Blueprint, render_template
from models import Classroom, Reservation
from datetime import date, time, datetime, timedelta

bp = Blueprint('totem', __name__, url_prefix='/totem')

@bp.route('/')
def display():
    today = date.today()
    now = datetime.now()

    # Determine current period
    if now.hour < 12:
        p_start, p_end, current_period = time(0, 0), time(12, 0), "Manhã"
    elif now.hour < 18:
        p_start, p_end, current_period = time(12, 0), time(18, 0), "Tarde"
    else:
        p_start, p_end, current_period = time(18, 0), time(23, 59), "Noite"

    # 1. Fetch Auditoriums for the next 7 days
    week_end = today + timedelta(days=7)
    aud_reservations = Reservation.query.join(Classroom).filter(
        Classroom.category == 'auditorium',
        Reservation.date >= today, Reservation.date <= week_end,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()

    # 2. Fetch Classrooms for today's current period
    cls_reservations = Reservation.query.join(Classroom).filter(
        Classroom.category != 'auditorium',
        Reservation.date == today, Reservation.status == 'approved',
        Reservation.start_time < p_end, Reservation.end_time > p_start
    ).order_by(Classroom.code).all()

    # Group classrooms by the first number in the room code
    grouped_classrooms = {}
    for r in cls_reservations:
        match = re.search(r'^(?:CR|AU|KI|CP|HL)(\d)', r.classroom.code)
        if match:
            d = match.group(1)
            floor_name = {"0": "Térreo", "1": "1º Andar", "2": "2º Andar", "3": "3º Andar"}.get(d, f"{d}º Andar")
        else: floor_name = "Outros"
        
        if floor_name not in grouped_classrooms: grouped_classrooms[floor_name] = []
        grouped_classrooms[floor_name].append(r)

    floor_order = {"Térreo": 0, "1º Andar": 1, "2º Andar": 2, "3º Andar": 3, "4º Andar": 4, "5º Andar": 5}
    sorted_floors = dict(sorted(grouped_classrooms.items(), key=lambda item: floor_order.get(item[0], 99)))

    return render_template('totem.html', aud_reservations=aud_reservations, classroom_floors=sorted_floors, current_period=current_period)