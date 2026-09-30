from flask import Blueprint, render_template, request, make_response, abort
from flask_login import login_required
from markupsafe import escape
from app.models import Classroom, Reservation, RoomCategory
from app.extensions import db
from app.unity_context import current_unity_id, current_unity
from datetime import datetime, date, time, timedelta
import calendar
from app.permissions import require_permission
from app.services.pdf_report import RelatorioPDF

bp = Blueprint('classrooms', __name__, url_prefix='/classrooms')

# Nomes dos meses em pt-BR: calendar.month_name depende do locale do servidor
# (em um host em inglês exibiria "January", "February"...), então usamos a
# lista fixa em todos os calendários e PDFs.
MESES_PT = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
            'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']

# Nomes dos dias em pt-BR para a visão diária (weekday(): 0=segunda ... 6=domingo)
DIAS_SEMANA_PT = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira',
                  'Sexta-feira', 'Sábado', 'Domingo']

# Helper function to apply filters and return a query
def get_filtered_classrooms(args):
    # Multi-unidade: apenas salas da unidade ativa
    query = Classroom.query.filter(
        Classroom.is_active == True,
        Classroom.unity_id == current_unity_id()
    )
    
    available_date_str = args.get('available_date')
    available_period = args.get('available_period')
    available_now = args.get('available_now')
    selected_category = args.get('category', '')
    
    if selected_category:
        query = query.filter(Classroom.category_id == selected_category)
        
    if available_now:
        now = datetime.now()
        today = date.today()
        current_time = now.time()
        occupied_ids = db.session.query(Reservation.classroom_id).filter(
            Reservation.date == today,
            Reservation.status == 'approved',
            Reservation.start_time <= current_time,
            Reservation.end_time > current_time
        ).distinct().all()
        occupied_flat = [r[0] for r in occupied_ids]
        if occupied_flat:
            query = query.filter(~Classroom.id.in_(occupied_flat))
            
    elif available_date_str and available_period:
        try:
            filter_date = datetime.strptime(available_date_str, '%Y-%m-%d').date()
        except ValueError:
            filter_date = date.today()
            
        if available_period == 'morning':
            p_start, p_end = time(0, 0), time(12, 0)
        elif available_period == 'afternoon':
            p_start, p_end = time(12, 0), time(18, 0)
        else: 
            p_start, p_end = time(18, 0), time(23, 59)
            
        occupied_ids = db.session.query(Reservation.classroom_id).filter(
            Reservation.date == filter_date,
            Reservation.status == 'approved',
            Reservation.start_time < p_end,
            Reservation.end_time > p_start
        ).distinct().all()
        occupied_flat = [r[0] for r in occupied_ids]
        if occupied_flat:
            query = query.filter(~Classroom.id.in_(occupied_flat))

    return query.order_by(Classroom.building, Classroom.code).all()

def _get_classroom_scoped(classroom_id):
    """Carrega a sala da unidade ativa — salas de outras unidades dão 404."""
    classroom = db.get_or_404(Classroom, classroom_id)
    if classroom.unity_id != current_unity_id():
        abort(404)
    return classroom

# Route to list classrooms with filters
@bp.route('/')
@login_required
def list_classrooms():
    # Get filtered rooms from helper function
    classrooms = get_filtered_classrooms(request.args)
    
    categories = RoomCategory.query.filter_by(is_active=True).order_by(RoomCategory.name).all()

    
    # Group by floor and sort by room number
    grouped_rooms = {}
    for c in classrooms:
        floor_name = c.floor or 'Outros'
        if floor_name not in grouped_rooms:
            grouped_rooms[floor_name] = []
        grouped_rooms[floor_name].append(c)
        
    # Sort rooms inside each floor by room_number (numerically if possible)
    for floor in grouped_rooms:
        grouped_rooms[floor].sort(key=lambda x: int(x.room_number) if x.room_number and x.room_number.isdigit() else 9999)
        
    # Sort floors logically
    floor_order = {"Térreo": 0, "Ground Floor": 0, "1º Andar": 1, "1st Floor": 1, "2º Andar": 2, "2nd Floor": 2, "3º Andar": 3, "3rd Floor": 3, "4º Andar": 4, "4th Floor": 4, "5º Andar": 5, "5th Floor": 5}
    sorted_floors = dict(sorted(grouped_rooms.items(), key=lambda item: floor_order.get(item[0], 99)))

    # Check filters for alert message
    is_filtered = False
    filter_message = ""
    if request.args.get('available_now'):
        is_filtered = True
        filter_message = "Mostrando salas disponíveis agora."
    elif request.args.get('available_date') and request.args.get('available_period'):
        is_filtered = True
        period_map = {
            'morning': 'Manhã',
            'afternoon': 'Tarde',
            'evening': 'Noite'
        }
        period_pt = period_map.get(request.args.get('available_period'), request.args.get('available_period'))
        # Escape obrigatório: o template exibe esta mensagem com o filtro |safe
        raw_date = escape(request.args.get('available_date', ''))
        filter_message = f"Mostrando salas disponíveis em <strong>{raw_date}</strong> durante a <strong>{period_pt}</strong>."
    elif request.args.get('category'):
        is_filtered = True
        cat_id = request.args.get('category', type=int)
        cat_obj = RoomCategory.query.get(cat_id) if cat_id else None
        cat_name = escape(cat_obj.name) if cat_obj else "Categoria"
        filter_message = f"Mostrando apenas <strong>{cat_name}</strong>."

    return render_template(
        'classrooms/list.html', 
        grouped_rooms=sorted_floors, # Pass the grouped dictionary instead of flat list
        categories=categories,
        is_filtered=is_filtered,
        filter_message=filter_message,
        selected_category=request.args.get('category', '')
    )

# Route to export filtered classrooms to PDF
@bp.route('/export_pdf')
@login_required
@require_permission('system:export')
def export_pdf():
    classrooms = get_filtered_classrooms(request.args)
    unity = current_unity()
    pdf = RelatorioPDF("Relatório de Salas",
                       unidade=unity.name if unity else None)

    # Reproduz na descrição os filtros aplicados na listagem — um relatório
    # afixado em mural precisa explicar de onde veio a relação de salas
    filtros = []
    cat_id = request.args.get('category', type=int)
    if cat_id:
        cat_obj = RoomCategory.query.get(cat_id)
        if cat_obj:
            filtros.append(f"Categoria: {cat_obj.name}")
    if request.args.get('available_now'):
        filtros.append("Livres agora")
    elif request.args.get('available_date'):
        data_str = request.args.get('available_date')
        try:
            data_filtro = datetime.strptime(data_str, '%Y-%m-%d').date()
            rotulo = f"Livres em {data_filtro:%d/%m/%Y}"
        except ValueError:
            rotulo = f"Livres em {data_str}"
        periodo = request.args.get('available_period')
        if periodo == 'morning':
            rotulo += " pela manhã"
        elif periodo == 'afternoon':
            rotulo += " à tarde"
        elif periodo:
            rotulo += " à noite"
        filtros.append(rotulo)
    meta = " \u00b7 ".join(filtros) if filtros else "Todas as salas ativas da unidade"
    pdf.linha_meta(f"{len(classrooms)} salas \u00b7 {meta}")

    if classrooms:
        capacidade_total = sum(c.capacity or 0 for c in classrooms)
        salas_com_pc = sum(1 for c in classrooms if c.category.controla_computadores)
        predios = {c.building for c in classrooms if c.building}
        pdf.cartoes_kpi([
            (str(len(classrooms)), "Salas listadas"),
            (str(capacidade_total), "Capacidade total"),
            (str(salas_com_pc), "Com computadores"),
            (str(len(predios)), "Prédios"),
        ])

        headers = ['Nome', 'Código', 'Categoria', 'Prédio', 'Andar', 'Cap', 'PCs']
        col_widths = [78, 26, 52, 52, 26, 18, 21]
        aligns = ('LEFT', 'CENTER', 'LEFT', 'LEFT', 'CENTER', 'CENTER', 'CENTER')
        linhas = []
        for c in classrooms:
            linhas.append({"celulas": [
                c.name, c.code, c.category.name.title(),
                c.building or 'N/A', c.floor or 'N/A', str(c.capacity),
                str(c.computer_count) if c.category.controla_computadores else '0',
            ]})
        pdf.tabela(headers, linhas, col_widths, aligns)
    else:
        pdf.mensagem_vazia("Nenhuma sala encontrada",
                           "Ajuste os filtros aplicados na listagem de salas.")

    pdf_output = pdf.output()
    response = make_response(bytes(pdf_output))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=exportacao_salas.pdf'
    return response

# Route to view details of a specific classroom
@bp.route('/<int:classroom_id>')
@login_required
def detail(classroom_id):
    classroom = _get_classroom_scoped(classroom_id)
    today = date.today()
    upcoming = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= today,
        Reservation.status.in_(['approved', 'pending'])
    ).order_by(Reservation.date, Reservation.start_time).all()
    return render_template('classrooms/detail.html', classroom=classroom, upcoming=upcoming)

def _availability_anchor():
    """Âncora (date) da visão de disponibilidade a partir de year/month/day.

    Sem parâmetros cai em hoje. No mês corrente sem day explícito, ancora no
    dia de hoje — trocar de visão não pode pular para o dia 1. Um dia além do
    comprimento do mês (preservado pela navegação) clampara no último dia.
    """
    today = date.today()
    req_year = request.args.get('year', type=int)
    req_month = request.args.get('month', type=int)
    req_day = request.args.get('day', type=int)
    if req_year and req_month:
        year, month = req_year, req_month
        day = req_day or (today.day if (year, month) == (today.year, today.month) else 1)
    else:
        year, month, day = today.year, today.month, today.day
    try:
        return date(year, month, day)
    except ValueError:
        try:
            return date(year, month, calendar.monthrange(year, month)[1])
        except ValueError:
            return today


# Route to view availability of a classroom (dia, semana ou mês)
@bp.route('/<int:classroom_id>/availability')
@login_required
def availability(classroom_id):
    classroom = _get_classroom_scoped(classroom_id)
    today = date.today()

    view = request.args.get('view', 'month')
    if view not in ('day', 'week', 'month'):
        view = 'month'

    anchor = _availability_anchor()

    def reservas_entre(inicio, fim):
        """Reservas aprovadas da sala no intervalo fechado [inicio, fim]."""
        return Reservation.query.filter(
            Reservation.classroom_id == classroom_id,
            Reservation.date >= inicio,
            Reservation.date <= fim,
            Reservation.status == 'approved'
        ).order_by(Reservation.date, Reservation.start_time).all()

    month_days = None
    reservations_by_day = {}
    days = []
    title_periodo = ''

    if view == 'day':
        days = [(anchor, reservas_entre(anchor, anchor))]
        prev_date, next_date = anchor - timedelta(days=1), anchor + timedelta(days=1)
        title_periodo = (f"{DIAS_SEMANA_PT[anchor.weekday()]}, "
                         f"{anchor.strftime('%d/%m/%Y')}")
    elif view == 'week':
        # Semana começando no domingo, igual ao calendário mensal (firstweekday=6)
        week_start = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
        week_end = week_start + timedelta(days=6)
        reservas = reservas_entre(week_start, week_end)
        days = [(week_start + timedelta(days=i),
                 [r for r in reservas if r.date == week_start + timedelta(days=i)])
                for i in range(7)]
        prev_date, next_date = week_start - timedelta(days=7), week_end + timedelta(days=1)
        title_periodo = (f"{week_start.strftime('%d/%m')} – "
                         f"{week_end.strftime('%d/%m/%Y')}")
    else:  # month (padrão)
        first_day = date(anchor.year, anchor.month, 1)
        last_day = date(anchor.year, anchor.month,
                        calendar.monthrange(anchor.year, anchor.month)[1])
        for r in reservas_entre(first_day, last_day):
            reservations_by_day.setdefault(r.date.day, []).append(r)
        month_days = calendar.Calendar(firstweekday=6).monthdayscalendar(
            anchor.year, anchor.month)
        prev_date, next_date = first_day - timedelta(days=1), last_day + timedelta(days=1)
        title_periodo = f"{MESES_PT[anchor.month - 1]} de {anchor.year}"

    return render_template(
        'classrooms/availability.html', classroom=classroom, view=view,
        anchor=anchor, today=today, days=days, title_periodo=title_periodo,
        month_days=month_days, reservations_by_day=reservations_by_day,
        prev_date=prev_date, next_date=next_date,
        year=anchor.year, month=anchor.month,
    )

# Route to export a specific classroom's reservations to PDF, following the
# view in use on the availability page (day, week or month)
@bp.route('/<int:classroom_id>/export_availability')
@login_required
@require_permission('system:export')
def export_availability(classroom_id):
    classroom = _get_classroom_scoped(classroom_id)
    anchor = _availability_anchor()

    view = request.args.get('view', 'month')
    if view not in ('day', 'week', 'month'):
        view = 'month'

    # O período exportado acompanha a visão em uso na página.
    if view == 'day':
        inicio = fim = anchor
        periodo_label = f"Dia: {anchor.strftime('%d/%m/%Y')}"
        nome_arquivo = f"reservas_{classroom.code}_{anchor.strftime('%Y-%m-%d')}.pdf"
    elif view == 'week':
        # Semana começando no domingo, igual à visão semanal da página
        inicio = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
        fim = inicio + timedelta(days=6)
        # "a" em vez de "–": a fonte Helvetica core do PDF não cobre o travessão
        periodo_label = (f"Semana: {inicio.strftime('%d/%m')} a "
                         f"{fim.strftime('%d/%m/%Y')}")
        nome_arquivo = (f"reservas_{classroom.code}_{inicio.strftime('%Y-%m-%d')}"
                        f"_a_{fim.strftime('%Y-%m-%d')}.pdf")
    else:  # month (padrão)
        inicio = date(anchor.year, anchor.month, 1)
        fim = date(anchor.year, anchor.month,
                   calendar.monthrange(anchor.year, anchor.month)[1])
        periodo_label = f"{MESES_PT[anchor.month - 1]} de {anchor.year}"
        nome_arquivo = f"reservas_{classroom.code}_{anchor.month}-{anchor.year}.pdf"

    # Fetch approved reservations for this period
    reservations = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= inicio,
        Reservation.date <= fim,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()

    unity = current_unity()
    pdf = RelatorioPDF("Agenda de Reservas",
                       unidade=unity.name if unity else None)
    pdf.linha_meta(f"Sala {classroom.name} ({classroom.code}) \u00b7 "
                   f"{periodo_label} \u00b7 {len(reservations)} reservas")

    today = date.today()
    now = datetime.now()

    if reservations:
        minutos_total = sum(
            (datetime.combine(r.date, r.end_time)
             - datetime.combine(r.date, r.start_time)).total_seconds() / 60
            for r in reservations
        )
        horas, minutos = divmod(int(minutos_total), 60)
        duracao = f"{horas}h{minutos:02d}" if minutos else f"{horas}h"
        proximas = sum(
            1 for r in reservations
            if r.date > today
            or (r.date == today and r.end_time >= now.time())
        )
        pdf.cartoes_kpi([
            (str(len(reservations)), "Reservas"),
            (duracao, "Horas reservadas"),
            (str(len({r.date for r in reservations})), "Dias com atividade"),
            (str(proximas), "Ainda vão ocorrer"),
        ])

        headers = ['Início', 'Fim', 'Título', 'Curso', 'Disciplina', 'Professor']
        col_widths = [20, 20, 88, 55, 50, 40]
        aligns = ('CENTER', 'CENTER', 'LEFT', 'LEFT', 'LEFT', 'LEFT')

        # Agrupa as reservas por dia com faixas de data: em mural ou telão,
        # o leitor localiza o dia de interesse sem ler linha por linha
        linhas = []
        data_atual = None
        tem_passadas = False
        for r in reservations:
            if r.date != data_atual:
                data_atual = r.date
                faixa = (f"{DIAS_SEMANA_PT[r.date.weekday()]}, "
                         f"{r.date:%d/%m/%Y}")
                if r.date == today:
                    faixa += " \u00b7 hoje"
                dia_passado = r.date < today
                linhas.append({"faixa": faixa,
                               "estilo": RelatorioPDF.PASSADO if dia_passado else None})
            is_past = r.date < today or (
                r.date == today and r.end_time < now.time())
            tem_passadas = tem_passadas or is_past
            linhas.append({
                "celulas": [
                    r.start_time.strftime('%H:%M'),
                    r.end_time.strftime('%H:%M'),
                    r.title,
                    r.course.name if r.course else 'N/A',
                    r.subject.name if r.subject else 'N/A',
                    r.teacher.full_name if r.teacher else 'N/A',
                ],
                "estilo": RelatorioPDF.PASSADO if is_past else None,
            })
        pdf.tabela(headers, linhas, col_widths, aligns)

        if tem_passadas:
            pdf.nota("Em cinza riscado: reservas que já ocorreram.")
    else:
        pdf.mensagem_vazia("Nenhuma reserva aprovada no período",
                           "As reservas confirmadas aparecem nesta agenda "
                           "assim que aprovadas.")

    # Output PDF
    pdf_output = pdf.output()
    # CORREÇÃO: Converter para bytes explicitamente (resolve o erro do bytearray)
    response = make_response(bytes(pdf_output))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={nome_arquivo}'
    return response