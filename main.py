from flask import Blueprint, render_template
from flask_login import login_required, current_user
from models import Classroom, Reservation
from datetime import datetime, date, time

bp = Blueprint('main', __name__)

# Dashboard route: Shows today's schedule split by Auditoriums and Classrooms
@bp.route('/dashboard')
@login_required
def index():
    today = date.today()
    now = datetime.now()

    # Determine current period based on time of day (Portuguese labels)
    if now.hour < 12:
        period_start, period_end = time(0, 0), time(12, 0)
        current_period = "Manhã"
    elif now.hour < 18:
        period_start, period_end = time(12, 0), time(18, 0)
        current_period = "Tarde"
    else:
        period_start, period_end = time(18, 0), time(23, 59)
        current_period = "Noite"

    # Format today's date in Portuguese manually to avoid server locale issues
    dias_semana = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
    meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']
    
    formatted_today = f"{dias_semana[today.weekday()]}, {today.day} de {meses[today.month - 1]}"

    # Fetch all approved reservations for today that overlap with the current period
    today_reservations = Reservation.query.filter(
        Reservation.date == today,
        Reservation.status == 'approved',
        Reservation.start_time < period_end,
        Reservation.end_time > period_start
    ).order_by(Reservation.start_time).all()

    # Split into Classrooms and Auditoriums for separate display blocks
    # r.classroom.category is a RoomCategory object — compare via .code, not the object itself
    aud_res = [r for r in today_reservations if r.classroom.category and r.classroom.category.code == 'auditorium']
    cls_res = [r for r in today_reservations if not r.classroom.category or r.classroom.category.code != 'auditorium']

    return render_template(
        'index.html',
        auditorium_reservations=aud_res,
        classroom_reservations=cls_res,
        current_period=current_period,
        formatted_today=formatted_today # Pass the pre-formatted string
    )