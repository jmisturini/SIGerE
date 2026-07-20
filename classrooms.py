from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models import Classroom, Reservation
from forms import ClassroomForm
import calendar
from extensions import db
from datetime import datetime, date, time



bp = Blueprint('classrooms', __name__, url_prefix='/classrooms')


@bp.route('/')
@login_required
def list_classrooms():
    query = Classroom.query.filter_by(is_active=True)
    
    # New Filters: Date and Period
    available_date_str = request.args.get('available_date')
    available_period = request.args.get('available_period')
    
    is_filtered = False
    
    if available_date_str and available_period:
        is_filtered = True
        try:
            filter_date = datetime.strptime(available_date_str, '%Y-%m-%d').date()
        except ValueError:
            filter_date = date.today()
            
        # Define period time blocks
        if available_period == 'morning':
            p_start, p_end = time(0, 0), time(12, 0)
        elif available_period == 'afternoon':
            p_start, p_end = time(12, 0), time(18, 0)
        else: # night
            p_start, p_end = time(18, 0), time(23, 59)
            
        # Find IDs of rooms that are OCCUPIED during this period
        occupied_ids = db.session.query(Reservation.classroom_id).filter(
            Reservation.date == filter_date,
            Reservation.status == 'approved',
            Reservation.start_time < p_end,
            Reservation.end_time > p_start
        ).distinct().all()
        
        # Flatten the list of tuples returned by SQLAlchemy
        occupied_flat = [r[0] for r in occupied_ids]
        
        # Exclude occupied rooms from the main query
        if occupied_flat:
            query = query.filter(~Classroom.id.in_(occupied_flat))

    classrooms = query.order_by(Classroom.code).all()
    
    return render_template(
        'classrooms/list.html', 
        classrooms=classrooms,
        is_filtered=is_filtered,
        available_date=available_date_str,
        available_period=available_period
    )

@bp.route('/<int:classroom_id>')
@login_required
def detail(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)
    today = date.today()
    upcoming = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= today,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()
    return render_template(
        'classrooms/detail.html', classroom=classroom, upcoming=upcoming
    )
    
@bp.route('/<int:classroom_id>/availability')
@login_required
def availability(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)
    
    # Get requested month/year from query params, or default to current
    req_year = request.args.get('year', type=int)
    req_month = request.args.get('month', type=int)
    
    today = date.today()
    if req_year and req_month:
        year, month = req_year, req_month
    else:
        year, month = today.year, today.month

    # Calculate first and last day of the month
    first_day = date(year, month, 1)
    last_day_num = calendar.monthrange(year, month)[1]
    last_day = date(year, month, last_day_num)

    # Fetch all approved reservations for this classroom in this month
    month_reservations = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= first_day,
        Reservation.date <= last_day,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()

    # Group reservations by the day of the month
    reservations_by_day = {}
    for r in month_reservations:
        if r.date.day not in reservations_by_day:
            reservations_by_day[r.date.day] = []
        reservations_by_day[r.date.day].append(r)

    # Get calendar matrix (list of weeks, each week is a list of days)
    # firstweekday=6 means Sunday is the first day of the week (0=Monday)
    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)

    # Calculate previous and next month for navigation
    if month == 1:
        prev_month, prev_year = 12, year - 1
        next_month, next_year = 2, year + 1
    elif month == 12:
        prev_month, prev_year = 11, year
        next_month, next_year = 1, year + 1
    else:
        prev_month, prev_year = month - 1, year
        next_month, next_year = month + 1, year

    return render_template(
        'classrooms/availability.html',
        classroom=classroom,
        year=year,
        month=month,
        month_name=calendar.month_name[month],
        month_days=month_days,
        reservations_by_day=reservations_by_day,
        today=today,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month
    )