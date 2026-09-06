from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required
from app.models import Reservation, Classroom, User, Course, Subject
from app.unity_context import current_unity_id
from datetime import datetime, time

bp = Blueprint('schedule', __name__, url_prefix='/calendar')

# Route to render the calendar page
@bp.route('/')
@login_required
def view():
    uid = current_unity_id()
    # Fetch data for filter dropdowns — apenas registros da unidade ativa
    classrooms = Classroom.query.filter_by(unity_id=uid, is_active=True).order_by(Classroom.code).all()
    teachers = User.query.filter(
        User.is_active_user == True,
        ((User.profile_type == 'teacher') | (User.is_teacher == True)),
        (User.unity_id == uid) | (User.unity_id.is_(None))
    ).order_by(User.full_name).all()
    courses = Course.query.filter_by(unity_id=uid, is_active=True).order_by(Course.name).all()
    subjects = Subject.query.filter_by(unity_id=uid, is_active=True).order_by(Subject.name).all()

    return render_template('calendar.html', classrooms=classrooms, teachers=teachers, courses=courses, subjects=subjects)

# API route to fetch reservation events as JSON
@bp.route('/api/events')
@login_required
def events():
    start_str = request.args.get('initialDate') or request.args.get('start')
    end_str = request.args.get('finalDate') or request.args.get('end')

    # Intervalo é obrigatório: sem ele a API devolveria TODAS as reservas da
    # unidade de uma vez (resposta desproporcional e consulta sem limite).
    if not (start_str and end_str):
        return jsonify([])

    # Multi-unidade: apenas reservas da unidade ativa
    query = Reservation.query.filter_by(status='approved', unity_id=current_unity_id())

    # Filter by date range
    try:
        start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
        end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
        query = query.filter(Reservation.date >= start_date, Reservation.date <= end_date)
    except ValueError:
        # CORREÇÃO: Retornar lista vazia em vez de ignorar o erro e buscar tudo
        return jsonify([])

    # Apply specific dropdown filters
    room_id = request.args.get('room_id', type=int)
    teacher_id = request.args.get('teacher_id', type=int)
    course_id = request.args.get('course_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    period = request.args.get('period')

    if room_id: query = query.filter_by(classroom_id=room_id)
    if teacher_id: query = query.filter_by(teacher_id=teacher_id)
    if course_id: query = query.filter_by(course_id=course_id)
    if subject_id: query = query.filter_by(subject_id=subject_id)

    # Apply period filter
    if period:
        if period == 'morning':
            p_start, p_end = time(0, 0), time(12, 0)
        elif period == 'afternoon':
            p_start, p_end = time(12, 0), time(18, 0)
        elif period == 'night':
            p_start, p_end = time(18, 0), time(23, 59)
        else:
            p_start, p_end = None, None

        if p_start and p_end:
            query = query.filter(Reservation.start_time < p_end, Reservation.end_time > p_start)

    reservations = query.all()
    events = []
    for r in reservations:
        start_dt = datetime.combine(r.date, r.start_time)
        end_dt = datetime.combine(r.date, r.end_time)
        events.append({
            'id': r.id, 'title': r.title, 'start': start_dt.isoformat(), 'end': end_dt.isoformat(),
            'url': f"/reservations/{r.id}", 'classroom_code': r.classroom.code,
            'classroom_name': r.classroom.name, 'teacher': r.teacher.full_name if r.teacher else 'N/A',
            'course': r.course.name if r.course else 'N/A',
            'floor': r.classroom.floor or 'Outros', # NOVO
            'room_number': r.classroom.room_number or '9999' # NOVO
        })
    return jsonify(events)
