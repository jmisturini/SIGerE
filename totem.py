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
        p_start, p_end = time(0, 0), time(12, 0)
        current_period = "Morning"
    elif now.hour < 18:
        p_start, p_end = time(12, 0), time(18, 0)
        current_period = "Afternoon"
    else:
        p_start, p_end = time(18, 0), time(23, 59)
        current_period = "Night"

    # 1. Fetch Auditoriums for the next 7 days
    week_end = today + timedelta(days=7)
    aud_reservations = Reservation.query.join(Classroom).filter(
        Classroom.category == 'auditorium',
        Reservation.date >= today,
        Reservation.date <= week_end,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()

    # 2. Fetch Classrooms for today's current period
    cls_reservations = Reservation.query.join(Classroom).filter(
        Classroom.category != 'auditorium',
        Reservation.date == today,
        Reservation.status == 'approved',
        Reservation.start_time < p_end,
        Reservation.end_time > p_start
    ).order_by(Classroom.code).all()

    # Group classrooms by the first number in the room code (e.g., "CR101" -> "1st Floor")
    grouped_classrooms = {}
    for r in cls_reservations:
        code = r.classroom.code
        match = re.search(r'\d', code)
        if match:
            floor_digit = match.group()
            if floor_digit == '0':
                floor_name = "Ground Floor"
            elif floor_digit == '1':
                floor_name = "1st Floor"
            elif floor_digit == '2':
                floor_name = "2nd Floor"
            elif floor_digit == '3':
                floor_name = "3rd Floor"
            else:
                floor_name = f"{floor_digit}th Floor"
        else:
            floor_name = "General Floor"
        
        if floor_name not in grouped_classrooms:
            grouped_classrooms[floor_name] = []
        grouped_classrooms[floor_name].append(r)

    # Sort floors logically
    floor_order = {"Ground Floor": 0, "1st Floor": 1, "2nd Floor": 2, "3rd Floor": 3, "4th Floor": 4, "5th Floor": 5}
    sorted_floors = dict(sorted(grouped_classrooms.items(), key=lambda item: floor_order.get(item[0], 99)))

    return render_template(
        'totem.html',
        aud_reservations=aud_reservations,
        classroom_floors=sorted_floors,
        current_period=current_period
    )