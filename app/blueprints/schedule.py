from flask import (Blueprint, make_response, render_template, jsonify, request)
from flask_login import login_required
from app.extensions import db
from app.models import Reservation, Classroom, User, Course, Subject
from app.permissions import require_permission
from app.services.pdf_report import RelatorioPDF
from app.unity_context import current_unity, current_unity_id
from datetime import datetime, date, time

bp = Blueprint('schedule', __name__, url_prefix='/calendar')

DIAS_SEMANA_PT = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira',
                  'Sexta-feira', 'Sábado', 'Domingo']

# Janelas do filtro de período do dia — mesmos limites da listagem de reservas
# e dos relatórios
PERIODOS_DIA = {
    'morning': ('Manhã', time(0, 0), time(12, 0)),
    'afternoon': ('Tarde', time(12, 0), time(18, 0)),
    'night': ('Noite', time(18, 0), time(23, 59)),
}


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
        User.escopo_unidade(uid)
    ).order_by(User.full_name).all()
    courses = Course.query.filter_by(unity_id=uid, is_active=True).order_by(Course.name).all()
    subjects = Subject.query.filter_by(unity_id=uid, is_active=True).order_by(Subject.name).all()

    return render_template('calendar.html', classrooms=classrooms, teachers=teachers, courses=courses, subjects=subjects)


def _consulta_filtrada():
    """Consulta das reservas aprovadas da unidade ativa com os filtros da
    página do calendário (datas, sala, professor, curso, disciplina e período
    do dia) — fonte única da API de eventos e da exportação em PDF.

    Retorna dict com 'query' (None quando o intervalo de datas está ausente
    ou inválido: a API responde vazio e o PDF, quadro vazio — sem ele a
    consulta devolveria TODAS as reservas da unidade de uma vez), as datas
    'inicio'/'fim' resolvidas e 'filtros', a descrição legível do que foi
    aplicado, para o PDF se explicar sozinho.
    """
    resultado = {'query': None, 'inicio': None, 'fim': None, 'filtros': []}

    start_str = request.args.get('initialDate') or request.args.get('start')
    end_str = request.args.get('finalDate') or request.args.get('end')
    if not (start_str and end_str):
        return resultado
    try:
        inicio = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
        fim = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
    except ValueError:
        return resultado

    query = Reservation.query.filter_by(status='approved', unity_id=current_unity_id())
    query = query.filter(Reservation.date >= inicio, Reservation.date <= fim)
    resultado.update(query=query, inicio=inicio, fim=fim)
    resultado['filtros'].append(f"Período: {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}")

    # Vínculos opcionais (sala, docente, curso e disciplina)
    vinculos = (('room_id', 'classroom_id', 'Sala'),
                ('teacher_id', 'teacher_id', 'Professor'),
                ('course_id', 'course_id', 'Curso'),
                ('subject_id', 'subject_id', 'Disciplina'))
    for campo, coluna, prefixo in vinculos:
        valor = request.args.get(campo, type=int)
        if valor:
            query = query.filter(getattr(Reservation, coluna) == valor)
            resultado['filtros'].append(
                f"{prefixo}: {_nome_vinculo(campo, valor)}")

    period = request.args.get('period')
    if period in PERIODOS_DIA:
        _, p_start, p_end = PERIODOS_DIA[period]
        query = query.filter(Reservation.start_time < p_end, Reservation.end_time > p_start)
        resultado['filtros'].append(f"Período do dia: {PERIODOS_DIA[period][0]}")

    query = query.order_by(Reservation.date, Reservation.start_time)
    resultado['query'] = query
    return resultado


def _nome_vinculo(campo, valor):
    """Nome legível de um vínculo escolhido no filtro (sala/professor/curso/
    disciplina) para a linha de filtros aplicados do PDF."""
    modelos = {
        'room_id': Classroom, 'teacher_id': User,
        'course_id': Course, 'subject_id': Subject,
    }
    entidade = db.session.get(modelos[campo], valor)
    if entidade is None:
        return f'#{valor}'
    if campo == 'room_id':
        return f"{entidade.code} — {entidade.name}"
    return (entidade.full_name if campo == 'teacher_id' else entidade.name)


# API route to fetch reservation events as JSON
@bp.route('/api/events')
@login_required
def events():
    consulta = _consulta_filtrada()
    reservas = consulta['query'].all() if consulta['query'] else []
    events = []
    for r in reservas:
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


# Exporta as aulas do calendário em PDF com os mesmos filtros aplicados na página
@bp.route('/export_pdf')
@login_required
@require_permission('system:export')
def export_pdf():
    consulta = _consulta_filtrada()
    reservations = consulta['query'].all() if consulta['query'] else []

    unity = current_unity()
    pdf = RelatorioPDF("Aulas do Calendário",
                       unidade=unity.name if unity else None)

    # A relação afixada em mural precisa explicar de onde veio: período e
    # filtros escolhidos na página
    meta = " \u00b7 ".join(consulta['filtros']) if consulta['filtros'] \
        else "Sem período selecionado"
    pdf.linha_meta(f"{len(reservations)} aulas \u00b7 {meta}")

    hoje = date.today()
    agora = datetime.now()

    if reservations:
        minutos_total = sum(
            (datetime.combine(r.date, r.end_time)
             - datetime.combine(r.date, r.start_time)).total_seconds() / 60
            for r in reservations
        )
        horas, minutos = divmod(int(minutos_total), 60)
        duracao = f"{horas}h{minutos:02d}" if minutos else f"{horas}h"
        pdf.cartoes_kpi([
            (str(len(reservations)), "Aulas"),
            (duracao, "Horas de aula"),
            (str(len({r.date for r in reservations})), "Dias com aula"),
            (str(len({r.classroom_id for r in reservations})), "Salas diferentes"),
        ])

        headers = ['Horário', 'Sala', 'Curso', 'Professor', 'Evento']
        col_widths = [28, 20, 62, 55, 108]
        aligns = ('CENTER', 'CENTER', 'LEFT', 'LEFT', 'LEFT')

        # Faixas por dia: em mural ou telão, o leitor localiza o dia de
        # interesse sem ler linha por linha
        linhas = []
        data_atual = None
        tem_passadas = False
        for r in reservations:
            if r.date != data_atual:
                data_atual = r.date
                faixa = (f"{DIAS_SEMANA_PT[r.date.weekday()]}, "
                         f"{r.date:%d/%m/%Y}")
                if r.date == hoje:
                    faixa += " \u00b7 hoje"
                linhas.append({"faixa": faixa,
                               "estilo": RelatorioPDF.PASSADO if r.date < hoje else None})
            is_past = r.date < hoje or (
                r.date == hoje and r.end_time < agora.time())
            tem_passadas = tem_passadas or is_past
            linhas.append({
                "celulas": [
                    f"{r.start_time:%H:%M} - {r.end_time:%H:%M}",
                    r.classroom.code,
                    r.course.name if r.course else 'N/A',
                    r.teacher.full_name if r.teacher else 'N/A',
                    (r.title or '').strip() or '-',
                ],
                "estilo": RelatorioPDF.PASSADO if is_past else None,
            })
        pdf.tabela(headers, linhas, col_widths, aligns)

        if tem_passadas:
            pdf.nota("Em cinza riscado: aulas que já ocorreram.")
    else:
        pdf.mensagem_vazia("Nenhuma aula no período",
                           "Ajuste os filtros na página do calendário "
                           "e exporte novamente.")

    nome_arquivo = 'aulas.pdf'
    if consulta['inicio']:
        nome_arquivo = (f"aulas_{consulta['inicio']:%Y-%m-%d}"
                        f"_a_{consulta['fim']:%Y-%m-%d}.pdf")

    pdf_output = pdf.output()
    response = make_response(bytes(pdf_output))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={nome_arquivo}'
    return response
