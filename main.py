from flask import Blueprint, render_template
from flask_login import login_required, current_user
from models import Classroom, Reservation
from datetime import datetime, date, time

bp = Blueprint('main', __name__)


@bp.route('/dashboard')
@login_required
def index():
    today = date.today()
    now = datetime.now()

    # Determine current period based on time of day
    if now.hour < 12:
        period_start, period_end = time(0, 0), time(12, 0)
        current_period = "Morning"
    elif now.hour < 18:
        period_start, period_end = time(12, 0), time(18, 0)
        current_period = "Afternoon"
    else:
        period_start, period_end = time(18, 0), time(23, 59)
        current_period = "Night"

    # Fetch all approved reservations for today that overlap with the current period
    today_reservations = Reservation.query.filter(
        Reservation.date == today,
        Reservation.status == 'approved',
        Reservation.start_time < period_end,
        Reservation.end_time > period_start
    ).order_by(Reservation.start_time).all()

    return render_template(
        'index.html',
        today_reservations=today_reservations,
        current_period=current_period,
        today_date=today
    )