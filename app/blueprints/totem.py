from flask import Blueprint, render_template, request, abort, current_app
from app.models import Classroom, Reservation, RoomCategory, Unity
from datetime import date, time, datetime, timedelta

bp = Blueprint('totem', __name__, url_prefix='/totem')

# Ordem de exibição dos andares dentro de cada categoria; andar fora do mapa
# vai para o fim da lista.
FLOOR_ORDER = {"Térreo": 0, "1º Andar": 1, "2º Andar": 2, "3º Andar": 3, "4º Andar": 4, "5º Andar": 5}

def _totem_unity():
    """Unidade exibida no totem: ?unity=<id> ou a primeira ativa (fallback)."""
    unity_id = request.args.get('unity', type=int)
    if unity_id:
        unity = Unity.query.filter_by(id=unity_id, is_active=True).first()
        if unity:
            return unity
        abort(404)
    return Unity.query.filter_by(is_active=True).order_by(Unity.name).first()

def _totem_weather(unity):
    """Localização do clima: coordenadas da unidade (cada uma tem a sua) com
    fallback para as globais do Config (TOTEM_LATITUDE/TOTEM_LONGITUDE)."""
    if unity and unity.weather_latitude is not None and unity.weather_longitude is not None:
        return (unity.weather_latitude, unity.weather_longitude,
                unity.weather_city or 'Campus')
    return (current_app.config['TOTEM_LATITUDE'],
            current_app.config['TOTEM_LONGITUDE'],
            (unity.weather_city if unity else None) or 'Campus')

def _category_sections(unity, today, p_start, p_end):
    """Monta as seções do totem a partir das categorias cadastradas.

    Cada categoria ativa com espaço na unidade E atividade no seu recorte de
    tempo vira um bloco — o recorte (período atual ou próximos 7 dias) e a
    aparência (cor/ícone) vêm do cadastro, e nenhuma categoria é citada pelo
    código. Cadastrar a quadra, por exemplo, faz o bloco dela aparecer aqui
    sem deploy; grupos sem atividade não entram na tela.
    """
    categories = (RoomCategory.query
                  .join(Classroom, Classroom.category_id == RoomCategory.id)
                  .filter(RoomCategory.is_active == True,
                          Classroom.is_active == True,
                          Classroom.unity_id == unity.id)
                  .distinct()
                  .order_by(RoomCategory.name)
                  .all())

    week_cats = [c for c in categories if c.totem_window == RoomCategory.TOTEM_WINDOW_WEEK]
    period_cats = [c for c in categories if c.totem_window != RoomCategory.TOTEM_WINDOW_WEEK]

    week_by_cat = {}
    if week_cats:
        week_res = (Reservation.query.join(Classroom)
                    .filter(Classroom.unity_id == unity.id,
                            Classroom.category_id.in_([c.id for c in week_cats]),
                            Reservation.date >= today,
                            Reservation.date <= today + timedelta(days=7),
                            Reservation.status == 'approved')
                    .order_by(Reservation.date, Reservation.start_time)
                    .all())
        for r in week_res:
            week_by_cat.setdefault(r.classroom.category_id, []).append(r)

    period_by_cat = {}
    if period_cats:
        period_res = (Reservation.query.join(Classroom)
                      .filter(Classroom.unity_id == unity.id,
                              Classroom.category_id.in_([c.id for c in period_cats]),
                              Reservation.date == today,
                              Reservation.status == 'approved',
                              Reservation.start_time < p_end,
                              Reservation.end_time > p_start)
                      .order_by(Classroom.code)
                      .all())
        for r in period_res:
            period_by_cat.setdefault(r.classroom.category_id, []).append(r)

    # Apenas categorias COM atividade entram na tela: blocos vazios somem e
    # o espaço restante se redistribui entre os grupos com reservas.
    sections = []
    for cat in week_cats:
        reservations = week_by_cat.get(cat.id, [])
        if reservations:
            sections.append({'category': cat, 'window': 'week',
                             'reservations': reservations})
    for cat in period_cats:
        bucket = period_by_cat.get(cat.id, [])
        if not bucket:
            continue
        grouped = {}
        for r in bucket:
            floor_name = r.classroom.floor or "Outros"
            grouped.setdefault(floor_name, []).append(r)
        sorted_floors = dict(sorted(grouped.items(),
                                    key=lambda item: FLOOR_ORDER.get(item[0], 99)))
        sections.append({'category': cat, 'window': 'period', 'floors': sorted_floors})

    # Agenda semanal primeiro (eventos), depois as categorias do período
    sections.sort(key=lambda s: (0 if s['window'] == 'week' else 1,
                                 s['category'].name.lower()))
    return sections

@bp.route('/')
def display():
    unity = _totem_unity()
    if unity is None:
        # Sem unidades cadastradas, não há o que exibir
        return render_template('totem.html', category_sections=[], current_period='—',
                               weather_lat=current_app.config['TOTEM_LATITUDE'],
                               weather_lon=current_app.config['TOTEM_LONGITUDE'],
                               weather_city='Campus')

    today = date.today()
    now = datetime.now()

    # Determine current period
    if now.hour < 12:
        p_start, p_end, current_period = time(0, 0), time(12, 0), "Manhã"
    elif now.hour < 18:
        p_start, p_end, current_period = time(12, 0), time(18, 0), "Tarde"
    else:
        p_start, p_end, current_period = time(18, 0), time(23, 59), "Noite"

    category_sections = _category_sections(unity, today, p_start, p_end)

    # Lista de unidades para alternância rápida no painel (ex: uma TV por unidade)
    unities = Unity.query.filter_by(is_active=True).order_by(Unity.name).all()

    weather_lat, weather_lon, weather_city = _totem_weather(unity)

    return render_template('totem.html', category_sections=category_sections,
                           current_period=current_period,
                           totem_unity=unity, totem_unities=unities,
                           weather_lat=weather_lat, weather_lon=weather_lon,
                           weather_city=weather_city)
