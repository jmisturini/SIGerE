from flask import Blueprint, render_template, request, redirect, url_for
from flask_login import current_user
from sqlalchemy import or_
from app.models import User, Classroom, Reservation, Course, Subject, Unity
from app.unity_context import current_unity_id
from datetime import date, time

bp = Blueprint('public', __name__)

# Cortes de período do cronograma público — mesmos limites usados no totem
# (Manhã até 12h, Tarde até 18h, Noite a partir das 18h). A aula entra no
# período em que COMEÇA, então uma aula 11h–13h aparece na Manhã.
PERIODOS_DIA = (
    ('manha', 'Manhã', 'bi-sunrise', time(12, 0)),
    ('tarde', 'Tarde', 'bi-sun', time(18, 0)),
    ('noite', 'Noite', 'bi-moon-stars', None),
)


def _periodo_da_aula(start_time):
    for key, _, _, limite in PERIODOS_DIA:
        if limite is None or start_time < limite:
            return key
    return 'noite'


def _public_unity():
    """Unidade exibida no portal público: ?unity=<id> ou a primeira ativa
    (fallback), mesmo comportamento do totem."""
    unity_id = request.args.get('unity', type=int)
    if unity_id:
        unity = Unity.query.filter_by(id=unity_id, is_active=True).first()
        if unity:
            return unity
    return Unity.query.filter_by(is_active=True).order_by(Unity.name).first()


# Public home page
@bp.route('/')
def home():
    # Redirect to dashboard if the user is already logged in
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    return render_template('home.html')


def _parse_data_arg():
    """Data consultada (?data=YYYY-MM-DD, padrão: hoje); datas inválidas caem para hoje."""
    schedule_date = date.today()
    if request.args.get('data'):
        try:
            schedule_date = date.fromisoformat(request.args.get('data'))
        except ValueError:
            pass
    return schedule_date


def _aulas_do_dia(schedule_date, query=''):
    """Reservas aprovadas do dia na unidade pública, agrupadas por período,
    mais o resultado da busca (quando há query). Retorna (periodos, resultados,
    unidade_ativa, unidades_disponiveis)."""
    unity = _public_unity()
    periods = [
        {'key': key, 'label': label, 'icon': icon, 'reservations': []}
        for key, label, icon, _ in PERIODOS_DIA
    ]
    results = []

    if unity is not None:
        scope = [
            Reservation.status == 'approved',
            Reservation.date == schedule_date,
            Classroom.unity_id == unity.id,
        ]
        day_reservations = (Reservation.query.join(Reservation.classroom)
                            .filter(*scope)
                            .order_by(Reservation.start_time, Classroom.code)
                            .all())
        by_period = {p['key']: p for p in periods}
        for r in day_reservations:
            by_period[_periodo_da_aula(r.start_time)]['reservations'].append(r)

        if query:
            # O aluno busca pelo que reconhece: título da aula, curso/turma,
            # disciplina, professor ou sala.
            like = f'%{query}%'
            results = (Reservation.query
                       .join(Reservation.classroom)
                       .outerjoin(Reservation.course)
                       .outerjoin(Reservation.subject)
                       .outerjoin(User, Reservation.teacher_id == User.id)
                       .filter(*scope, or_(
                           Reservation.title.ilike(like),
                           Classroom.name.ilike(like),
                           Classroom.code.ilike(like),
                           Course.name.ilike(like),
                           Course.code.ilike(like),
                           Subject.name.ilike(like),
                           Subject.code.ilike(like),
                           User.full_name.ilike(like)))
                       .order_by(Reservation.start_time, Classroom.code)
                       .all())

    unities = Unity.query.filter_by(is_active=True).order_by(Unity.name).all()
    return periods, results, unity, unities


# Public: busca da aula pelo aluno (curso, disciplina, professor ou sala)
@bp.route('/buscar-aula')
def class_search():
    query = request.args.get('q', '').strip()
    schedule_date = _parse_data_arg()
    _, results, unity, unities = _aulas_do_dia(schedule_date, query)
    return render_template(
        'buscar_aula.html',
        query=query,
        search_results=results,
        schedule_date=schedule_date,
        today=date.today(),
        public_unity=unity,
        public_unities=unities,
    )


# Public: cronograma geral das aulas do dia, dividido por período
@bp.route('/cronograma')
def daily_schedule():
    schedule_date = _parse_data_arg()
    periods, _, unity, unities = _aulas_do_dia(schedule_date)
    return render_template(
        'cronograma.html',
        schedule_date=schedule_date,
        today=date.today(),
        schedule_periods=periods,
        schedule_count=sum(len(p['reservations']) for p in periods),
        public_unity=unity,
        public_unities=unities,
    )

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
