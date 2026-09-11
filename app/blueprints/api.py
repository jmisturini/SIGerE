"""API REST de leitura de reservas para aplicativos externos.

Regras de visibilidade:
- Sem autenticação: apenas data, horário, sala e título — e somente reservas
  aprovadas (situações internas do fluxo, como pendente/cancelada, ficam
  invisíveis, na mesma linha do portal e do totem).
- Autenticado (HTTP Basic com usuário/senha do sistema, ou sessão já logada):
  todos os detalhes da reserva, em qualquer situação.

Escopo multi-unidade: usuário comum só vê a própria unidade; quem pode
alternar unidade (ou uma integração anônima) escolhe com ?unity_id=<id>.
"""
from base64 import b64decode
from datetime import date, time
from functools import wraps

from flask import Blueprint, abort, g, jsonify, request
from flask_login import current_user
from flask_limiter.errors import RateLimitExceeded

from app.extensions import db, limiter
from app.models import Classroom, Reservation, Unity, User
from app.unity_context import SWITCHABLE_PERMISSIONS, current_unity_id

bp = Blueprint('api', __name__, url_prefix='/api/v1')

PER_PAGE_DEFAULT = 100
PER_PAGE_MAX = 500

PERIODS = {
    'morning': (time(0, 0), time(12, 0)),
    'afternoon': (time(12, 0), time(18, 0)),
    'night': (time(18, 0), time(23, 59)),
}

STATUSES = ('approved', 'pending', 'cancelled')


# ── Autenticação ─────────────────────────────────────────────────────────────

def _unauthorized(message):
    response = jsonify({'error': message})
    response.status_code = 401
    response.headers['WWW-Authenticate'] = 'Basic realm="SIGerE API"'
    return response


def api_auth(view):
    """Autenticação da API: HTTP Basic (usuários do próprio sistema) com
    fallback para a sessão do Flask-Login. Requisição anônima continua
    válida — recebe apenas o payload público.
    """
    @wraps(view)
    def wrapper(*args, **kwargs):
        g.api_user = None
        g.api_via_session = False

        header = request.headers.get('Authorization', '')
        if header:
            scheme, _, value = header.strip().partition(' ')
            if scheme.lower() != 'basic' or not value:
                return _unauthorized('Autenticação suportada apenas via HTTP Basic.')
            try:
                decoded = b64decode(value.strip(), validate=True).decode('utf-8')
            except (ValueError, UnicodeDecodeError):
                return _unauthorized('Credenciais Basic inválidas (base64 malformado).')
            username, sep, password = decoded.partition(':')
            if not sep or not username:
                return _unauthorized('Credenciais Basic devem ter o formato "usuário:senha".')
            user = User.query.filter_by(username=username).first()
            if user is None or not user.check_password(password):
                return _unauthorized('Usuário ou senha inválidos.')
            if not user.is_active_user:
                return _unauthorized('Conta desativada. Contate um administrador.')
            g.api_user = user
        elif current_user.is_authenticated:
            g.api_user = current_user
            g.api_via_session = True

        return view(*args, **kwargs)
    return wrapper


# ── Escopo de unidade e serialização ─────────────────────────────────────────

def _first_active_unity():
    return Unity.query.filter_by(is_active=True).order_by(Unity.name).first()


def _scoped_unity_id():
    """Unidade das reservas retornadas.

    ?unity_id=<id> vale para anônimos e para quem pode alternar unidade;
    usuário comum fica preso à própria unidade; anônimo sem parâmetro cai na
    primeira unidade ativa (mesma regra do totem).
    """
    user = g.api_user
    param = request.args.get('unity_id', type=int)
    can_switch = user is not None and any(user.has_permission(c)
                                          for c in SWITCHABLE_PERMISSIONS)

    if param is not None and (user is None or can_switch):
        unity = db.session.get(Unity, param)
        if unity is None or not unity.is_active:
            abort(404, description=f'Unidade {param} não encontrada ou inativa.')
        return unity.id

    if user is None:
        unity = _first_active_unity()
        if unity is None:
            abort(404, description='Nenhuma unidade ativa cadastrada.')
        return unity.id

    if g.api_via_session:
        uid = current_unity_id()
        if uid is not None:
            return uid
    if user.unity_id:
        return user.unity_id
    unity = _first_active_unity()
    if unity is None:
        abort(404, description='Nenhuma unidade ativa cadastrada.')
    return unity.id


def _hora(t):
    """Horário em HH:MM:SS sempre (times gravados com microssegundo por
    importação/seed não devem vazar frações na API)."""
    return t.strftime('%H:%M:%S') if t else None


def _classroom_brief(classroom):
    return {'id': classroom.id, 'code': classroom.code, 'name': classroom.name}


def _person(user):
    if user is None:
        return None
    return {'id': user.id, 'username': user.username, 'full_name': user.full_name}


def _reservation_public(reservation):
    """Payload sem autenticação: apenas data, horário, sala e título."""
    return {
        'id': reservation.id,
        'title': reservation.title,
        'date': reservation.date.isoformat(),
        'start_time': _hora(reservation.start_time),
        'end_time': _hora(reservation.end_time),
        'classroom': _classroom_brief(reservation.classroom),
    }


def _reservation_full(reservation):
    """Payload autenticado: todos os detalhes da reserva."""
    classroom = reservation.classroom
    unity = reservation.unity
    course = reservation.course
    subject = reservation.subject
    return {
        'id': reservation.id,
        'title': reservation.title,
        'description': reservation.description,
        'date': reservation.date.isoformat(),
        'start_time': _hora(reservation.start_time),
        'end_time': _hora(reservation.end_time),
        'status': reservation.status,
        'classroom': {
            **_classroom_brief(classroom),
            'room_number': classroom.room_number,
            'building': classroom.building,
            'floor': classroom.floor,
            'capacity': classroom.capacity,
            'category': classroom.category.name if classroom.category else None,
        },
        'unity': {'id': unity.id, 'code': unity.code, 'name': unity.name} if unity else None,
        'created_by': _person(reservation.user),
        'teacher': _person(reservation.teacher),
        'course': {'id': course.id, 'code': course.code, 'name': course.name} if course else None,
        'subject': {'id': subject.id, 'code': subject.code, 'name': subject.name} if subject else None,
        'reviewed_by': _person(reservation.reviewer),
        'review_note': reservation.review_note,
        'repeat_group_id': reservation.repeat_group_id,
        'created_at': reservation.created_at.isoformat() if reservation.created_at else None,
        'updated_at': reservation.updated_at.isoformat() if reservation.updated_at else None,
    }


def _serializer():
    return _reservation_full if g.api_user is not None else _reservation_public


# ── Filtros ──────────────────────────────────────────────────────────────────

def _parse_date(value, param):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        abort(400, description=f"Parâmetro '{param}' inválido: use o formato AAAA-MM-DD.")


def _filtered_reservations(unity_id):
    """Query de reservas da unidade com os filtros da query string.

    Sem autenticação a situação é travada em 'approved' (qualquer valor de
    ?status= é ignorado); autenticado pode filtrar approved/pending/cancelled
    ou pedir tudo com status=all.
    """
    status = (request.args.get('status') or 'approved').strip().lower()
    if g.api_user is None:
        status = 'approved'
    if status != 'all' and status not in STATUSES:
        abort(400, description="Parâmetro 'status' inválido: "
                               "use approved, pending, cancelled ou all.")

    query = Reservation.query.filter_by(unity_id=unity_id)
    if status != 'all':
        query = query.filter(Reservation.status == status)

    start = _parse_date(request.args['start'], 'start') if request.args.get('start') else None
    end = _parse_date(request.args['end'], 'end') if request.args.get('end') else None
    if start and end and start > end:
        abort(400, description="Parâmetro 'start' não pode ser maior que 'end'.")
    if start:
        query = query.filter(Reservation.date >= start)
    if end:
        query = query.filter(Reservation.date <= end)

    classroom_id = request.args.get('classroom_id', type=int)
    if classroom_id:
        query = query.filter(Reservation.classroom_id == classroom_id)

    classroom_code = (request.args.get('classroom_code') or '').strip()
    if classroom_code:
        query = (query.join(Classroom, Classroom.id == Reservation.classroom_id)
                 .filter(Classroom.code == classroom_code))

    for param in ('teacher_id', 'course_id', 'subject_id'):
        value = request.args.get(param, type=int)
        if value:
            query = query.filter(getattr(Reservation, param) == value)

    period = (request.args.get('period') or '').strip().lower()
    if period:
        period_range = PERIODS.get(period)
        if period_range is None:
            abort(400, description="Parâmetro 'period' inválido: "
                                   "use morning, afternoon ou night.")
        p_start, p_end = period_range
        query = query.filter(Reservation.start_time < p_end,
                             Reservation.end_time > p_start)

    return query


# ── Rotas ────────────────────────────────────────────────────────────────────

@bp.route('/reservations')
@limiter.limit('120 per minute')
@api_auth
def list_reservations():
    unity_id = _scoped_unity_id()
    query = (_filtered_reservations(unity_id)
             .order_by(Reservation.date, Reservation.start_time, Reservation.id))

    page = request.args.get('page', 1, type=int) or 1
    per_page = request.args.get('per_page', PER_PAGE_DEFAULT, type=int) or PER_PAGE_DEFAULT
    page = max(page, 1)
    per_page = min(max(per_page, 1), PER_PAGE_MAX)

    pagination = db.paginate(query, page=page, per_page=per_page, error_out=False)
    serialize = _serializer()
    return jsonify({
        'unity_id': unity_id,
        'authenticated': g.api_user is not None,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'total': pagination.total,
        'pages': pagination.pages,
        'reservations': [serialize(r) for r in pagination.items],
    })


@bp.route('/reservations/<int:reservation_id>')
@limiter.limit('120 per minute')
@api_auth
def reservation_detail(reservation_id):
    unity_id = _scoped_unity_id()
    reservation = db.session.get(Reservation, reservation_id)
    # 404 unifica "não existe" e "fora do seu escopo": a API não confirma a
    # existência de reservas de outra unidade — nem de reservas não aprovadas
    # quando a chamada é anônima.
    if (reservation is None or reservation.unity_id != unity_id
            or (g.api_user is None and reservation.status != 'approved')):
        abort(404, description='Reserva não encontrada.')
    return jsonify(_serializer()(reservation))


@bp.route('/rooms')
@limiter.limit('120 per minute')
@api_auth
def list_rooms():
    """Salas ativas da unidade, para o app externo resolver códigos de sala."""
    unity_id = _scoped_unity_id()
    classrooms = (Classroom.query
                  .filter_by(unity_id=unity_id, is_active=True)
                  .order_by(Classroom.code)
                  .all())
    if g.api_user is None:
        rooms = [{'id': c.id, 'code': c.code, 'name': c.name} for c in classrooms]
    else:
        rooms = [{'id': c.id, 'code': c.code, 'name': c.name,
                  'building': c.building, 'floor': c.floor,
                  'capacity': c.capacity,
                  'category': c.category.name if c.category else None}
                 for c in classrooms]
    return jsonify({
        'unity_id': unity_id,
        'authenticated': g.api_user is not None,
        'rooms': rooms,
    })


# Erros da API em JSON (abort() dentro das rotas chega aqui como HTTPException)
@bp.errorhandler(400)
@bp.errorhandler(401)
@bp.errorhandler(403)
@bp.errorhandler(404)
def api_error(error):
    return jsonify({'error': error.description or error.name}), error.code


# 429 em JSON: o handler global de RateLimitExceeded dá flash e redireciona ao
# login — comportamento de navegador que não cabe numa API.
@bp.errorhandler(RateLimitExceeded)
def api_rate_limited(error):
    return jsonify({'error': 'Limite de requisições excedido. '
                             'Aguarde um momento e tente novamente.'}), 429


# CORS liberado para consumo por apps web hospedados em outras origens
# (quadro de porta, painéis de ocupação). A leitura anônima é pública por
# design; com Authorization, o navegador negocia o preflight via OPTIONS
# automático do Flask e recebe estes mesmos cabeçalhos.
@bp.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Authorization'
    return response
