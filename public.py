from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import current_user
from models import User, Classroom
from unity_context import current_unity_id

bp = Blueprint('public', __name__)

# Public home page
@bp.route('/')
def home():
    # Redirect to dashboard if the user is already logged in
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    return render_template('home.html')

# Public search page for rooms and teachers
@bp.route('/search')
def search():
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'classroom')

    results_rooms = []
    results_teachers = []

    if query:
        if search_type == 'classroom':
            # Busca salas ativas da unidade do visitante logado (ou de todas para anônimos)
            uid = current_unity_id()
            room_filter = [
                Classroom.is_active == True,
                (Classroom.name.ilike(f'%{query}%') | Classroom.code.ilike(f'%{query}%'))
            ]
            if uid is not None:
                room_filter.append(Classroom.unity_id == uid)
            results_rooms = Classroom.query.filter(*room_filter).order_by(Classroom.code).all()

        elif search_type == 'teacher':
            # Busca professores ativos (escopo por unidade quando determinável)
            uid = current_unity_id()
            teacher_filter = [
                User.is_active_user == True,
                User.profile_type == 'teacher',
                User.full_name.ilike(f'%{query}%')
            ]
            if uid is not None:
                teacher_filter.append((User.unity_id == uid) | (User.unity_id.is_(None)))
            results_teachers = User.query.filter(*teacher_filter).order_by(User.full_name).all()

    return render_template(
        'search.html',
        query=query,
        search_type=search_type,
        results_rooms=results_rooms,
        results_teachers=results_teachers
    )
