"""Relatórios de Salas e Reservas da unidade ativa.

Menu próprio (depois da Agenda) com duas visões: o relatório gerencial
geral (indicadores, gráficos e quadros de uso) e o relatório personalizado,
em que o usuário combina filtros e agrupamento para montar a própria
relação de dados. Ambos têm versão para impressão/PDF na própria página
(mesmo padrão do relatório de VT).
"""
import calendar

from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import and_, or_

from app.extensions import db
from app.models import (Reservation, Classroom, Course, Subject, User)
from app.permissions import require_permission
from app.unity_context import current_unity_id
from datetime import date, datetime, time

bp = Blueprint('relatorios', __name__, url_prefix='/relatorios')

DIAS_SEMANA_PT = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira',
                  'Sexta-feira', 'Sábado', 'Domingo']
DIAS_CURTOS_PT = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']

# Períodos do dia com os mesmos limites dos filtros da listagem e do calendário
PERIODOS_DIA = {
    'morning': ('Manhã', time(0, 0), time(12, 0)),
    'afternoon': ('Tarde', time(12, 0), time(18, 0)),
    'night': ('Noite', time(18, 0), time(23, 59)),
}
ORDEM_PERIODOS = ('morning', 'afternoon', 'night')

STATUS_ROTULOS = {'approved': 'Aprovada', 'pending': 'Pendente',
                  'cancelled': 'Cancelada'}

AGRUPAMENTOS = {
    'data': 'Data',
    'sala': 'Sala',
    'professor': 'Professor',
    'curso': 'Curso',
    'disciplina': 'Disciplina',
    'nenhum': 'Sem agrupamento',
}
# Rótulo do grupo que reúne reservas sem o vínculo escolhido
ROTULOS_SEM_VINCULO = {
    'sala': 'Sem sala',
    'professor': 'Sem professor',
    'curso': 'Sem curso',
    'disciplina': 'Sem disciplina',
}

ORDENS = ('asc', 'desc')


def _data_iso(texto):
    """Converte 'AAAA-MM-DD' em date; inválido/vazio vira None (sem filtro)."""
    if not texto:
        return None
    try:
        return datetime.strptime(texto, '%Y-%m-%d').date()
    except ValueError:
        return None


def _periodo_padrao():
    """Janela padrão do relatório: mês corrente (início, fim)."""
    hoje = date.today()
    return (hoje.replace(day=1),
            date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1]))


def _duracao_horas(minutos):
    """Duração legível a partir de minutos: '3h' ou '3h30'."""
    horas, resto = divmod(int(minutos), 60)
    return f"{horas}h{resto:02d}" if resto else f"{horas}h"


def _minutos_reserva(r):
    """Duração da reserva em minutos (float)."""
    return (datetime.combine(r.date, r.end_time)
            - datetime.combine(r.date, r.start_time)).total_seconds() / 60


def _juntar_nomes(nomes):
    """'Manhã, Tarde e Noite' — lista em português com 'e' antes do último."""
    if len(nomes) <= 1:
        return nomes[0] if nomes else ''
    return ', '.join(nomes[:-1]) + ' e ' + nomes[-1]


@bp.route('/')
@login_required
def raiz():
    """Atalho: /relatorios abre o Relatório Geral."""
    return redirect(url_for('relatorios.geral'))


@bp.route('/geral')
@login_required
@require_permission('reservation:read_all')
def geral():
    """Relatório gerencial de Salas e Reservas da unidade ativa: volume de
    reservas por status, horas reservadas, ocupação por sala, cursos e carga
    por docente, no período escolhido (padrão: mês corrente). A página tem
    versão para impressão/PDF (mesmo padrão do relatório de VT)."""
    inicio, fim = _periodo_padrao()
    inicio = _data_iso(request.args.get('start')) or inicio
    fim = _data_iso(request.args.get('end')) or fim
    if fim < inicio:
        inicio, fim = fim, inicio

    reservas = (Reservation.query.filter(
        Reservation.unity_id == current_unity_id(),
        Reservation.date >= inicio,
        Reservation.date <= fim,
    ).order_by(Reservation.date, Reservation.start_time).all())

    aprovadas = [r for r in reservas if r.status == 'approved']
    pendentes = sum(1 for r in reservas if r.status == 'pending')
    canceladas = sum(1 for r in reservas if r.status == 'cancelled')
    minutos_total = sum(_minutos_reserva(r) for r in aprovadas)

    # ── Ocupação por sala (aprovadas) ──
    por_sala = {}
    for r in aprovadas:
        sala = por_sala.setdefault(r.classroom_id, {
            'codigo': r.classroom.code, 'nome': r.classroom.name,
            'reservas': 0, 'minutos': 0.0})
        sala['reservas'] += 1
        sala['minutos'] += _minutos_reserva(r)
    salas_utilizadas = len(por_sala)
    salas_ativas = Classroom.query.filter_by(
        unity_id=current_unity_id(), is_active=True).count()

    # ── Reservas por curso ──
    por_curso = {}
    sem_curso = {'nome': 'Sem curso vinculado', 'reservas': 0, 'minutos': 0.0}
    for r in aprovadas:
        destino = (por_curso.setdefault(r.course_id, {
            'nome': r.course.name, 'reservas': 0, 'minutos': 0.0})
            if r.course else sem_curso)
        destino['reservas'] += 1
        destino['minutos'] += _minutos_reserva(r)

    # ── Carga por docente ──
    por_docente = {}
    sem_docente = {'nome': 'Sem docente vinculado', 'reservas': 0, 'minutos': 0.0}
    for r in aprovadas:
        destino = (por_docente.setdefault(r.teacher_id, {
            'nome': r.teacher.full_name, 'reservas': 0, 'minutos': 0.0})
            if r.teacher else sem_docente)
        destino['reservas'] += 1
        destino['minutos'] += _minutos_reserva(r)

    def _com_participacao(grupos, extras=None):
        """Grupos ordenados por horas desc, com duração formatada e % do total."""
        itens = sorted(grupos, key=lambda g: g['minutos'], reverse=True)
        for g in itens:
            g['horas'] = _duracao_horas(g['minutos'])
            g['percentual'] = (g['minutos'] * 100 / minutos_total
                               if minutos_total else 0)
        if extras is not None and extras['reservas']:
            extras['sem_vinculo'] = True
            extras['horas'] = _duracao_horas(extras['minutos'])
            extras['percentual'] = (extras['minutos'] * 100 / minutos_total
                                    if minutos_total else 0)
            itens.append(extras)
        return itens

    tabela_salas = _com_participacao(list(por_sala.values()))
    tabela_cursos = _com_participacao(list(por_curso.values()), sem_curso)
    tabela_docentes = _com_participacao(list(por_docente.values()), sem_docente)

    # ── Professores por curso: horas de cada docente no total do curso ──
    # Cursos com ao menos um docente nas aprovadas; as horas do curso sem
    # docente vinculado entram como linha de restos quando existirem.
    professores_por_curso = {}
    for r in aprovadas:
        if not r.course_id:
            continue
        grupo = professores_por_curso.setdefault(r.course_id, {
            'curso': r.course.name, 'minutos': 0.0,
            'docentes': {}, 'sem_docente': {'reservas': 0, 'minutos': 0.0}})
        grupo['minutos'] += _minutos_reserva(r)
        if r.teacher_id:
            docente = grupo['docentes'].setdefault(r.teacher_id, {
                'nome': r.teacher.full_name, 'reservas': 0, 'minutos': 0.0})
            docente['reservas'] += 1
            docente['minutos'] += _minutos_reserva(r)
        else:
            grupo['sem_docente']['reservas'] += 1
            grupo['sem_docente']['minutos'] += _minutos_reserva(r)

    professores_por_curso = [
        {'curso': g['curso'], 'docentes': sorted(
            g['docentes'].values(), key=lambda d: -d['minutos']),
         'sem_docente': g['sem_docente'] if g['sem_docente']['reservas'] else None,
         'minutos': g['minutos']}
        for g in sorted(professores_por_curso.values(),
                        key=lambda g: g['curso'])
        if g['docentes']]
    for grupo in professores_por_curso:
        grupo['horas'] = _duracao_horas(grupo['minutos'])
        for docente in grupo['docentes']:
            docente['horas'] = _duracao_horas(docente['minutos'])
            docente['percentual'] = (docente['minutos'] * 100 / grupo['minutos']
                                     if grupo['minutos'] else 0)
        if grupo['sem_docente']:
            grupo['sem_docente']['horas'] = _duracao_horas(
                grupo['sem_docente']['minutos'])
            grupo['sem_docente']['percentual'] = (
                grupo['sem_docente']['minutos'] * 100 / grupo['minutos']
                if grupo['minutos'] else 0)

    # ── Cursos por professor: horas de cada curso na carga do docente ──
    # Espelho do quadro anterior: professores com ao menos um curso nas
    # aprovadas; horas do docente sem curso entram como linha de restos.
    cursos_por_docente = {}
    for r in aprovadas:
        if not r.teacher_id:
            continue
        grupo = cursos_por_docente.setdefault(r.teacher_id, {
            'docente': r.teacher.full_name, 'minutos': 0.0,
            'cursos': {}, 'sem_curso': {'reservas': 0, 'minutos': 0.0}})
        grupo['minutos'] += _minutos_reserva(r)
        if r.course_id:
            curso = grupo['cursos'].setdefault(r.course_id, {
                'nome': r.course.name, 'reservas': 0, 'minutos': 0.0})
            curso['reservas'] += 1
            curso['minutos'] += _minutos_reserva(r)
        else:
            grupo['sem_curso']['reservas'] += 1
            grupo['sem_curso']['minutos'] += _minutos_reserva(r)

    cursos_por_docente = [
        {'docente': g['docente'],
         'cursos': sorted(g['cursos'].values(),
                          key=lambda c: (-c['minutos'], c['nome'])),
         'sem_curso': g['sem_curso'] if g['sem_curso']['reservas'] else None,
         'minutos': g['minutos']}
        for g in sorted(cursos_por_docente.values(),
                        key=lambda g: g['docente'])
        if g['cursos']]
    for grupo in cursos_por_docente:
        grupo['horas'] = _duracao_horas(grupo['minutos'])
        for curso in grupo['cursos']:
            curso['horas'] = _duracao_horas(curso['minutos'])
            curso['percentual'] = (curso['minutos'] * 100 / grupo['minutos']
                                   if grupo['minutos'] else 0)
        if grupo['sem_curso']:
            grupo['sem_curso']['horas'] = _duracao_horas(
                grupo['sem_curso']['minutos'])
            grupo['sem_curso']['percentual'] = (
                grupo['sem_curso']['minutos'] * 100 / grupo['minutos']
                if grupo['minutos'] else 0)

    # ── Distribuições para os gráficos (aprovadas) ──
    por_semana = [0] * 7
    por_periodo = {'manha': 0, 'tarde': 0, 'noite': 0}
    for r in aprovadas:
        por_semana[r.date.weekday()] += 1
        if r.start_time < time(12, 0):
            por_periodo['manha'] += 1
        elif r.start_time < time(18, 0):
            por_periodo['tarde'] += 1
        else:
            por_periodo['noite'] += 1

    # Top salas do gráfico: código como rótulo curto, horas como número
    top_salas = sorted(por_sala.values(), key=lambda s: s['minutos'],
                       reverse=True)[:8]

    docentes_count = len(por_docente)
    gerado_em = datetime.now().strftime('%d/%m/%Y às %H:%M')

    return render_template('relatorios/geral.html',
                           inicio=inicio, fim=fim,
                           periodo_label=f"{inicio:%d/%m/%Y} a {fim:%d/%m/%Y}",
                           gerado_em=gerado_em,
                           total_aprovadas=len(aprovadas),
                           pendentes=pendentes, canceladas=canceladas,
                           horas_total=_duracao_horas(minutos_total),
                           dias_com_atividade=len({r.date for r in aprovadas}),
                           salas_utilizadas=salas_utilizadas,
                           salas_ativas=salas_ativas,
                           docentes_count=docentes_count,
                           media_por_docente=(len(aprovadas) / docentes_count
                                              if docentes_count else 0),
                           tabela_salas=tabela_salas,
                           tabela_cursos=tabela_cursos,
                           tabela_docentes=tabela_docentes,
                           professores_por_curso=professores_por_curso,
                           cursos_por_docente=cursos_por_docente,
                           grafico_status=[len(aprovadas), pendentes, canceladas],
                           grafico_semana=por_semana,
                           grafico_periodo=[por_periodo['manha'],
                                            por_periodo['tarde'],
                                            por_periodo['noite']],
                           grafico_salas_rotulos=[
                               f"{s['codigo']} — {s['nome']}" for s in top_salas],
                           grafico_salas_horas=[round(s['minutos'] / 60, 1)
                                                for s in top_salas],
                           tem_reservas=bool(reservas),
                           tem_aprovadas=bool(aprovadas))


@bp.route('/personalizado')
@login_required
@require_permission('reservation:read_all')
def personalizado():
    """Relatório personalizado: o usuário combina filtros (período, status,
    sala, professor, curso, disciplina, período do dia e busca no título) e
    escolhe o agrupamento para montar a própria relação de reservas, com
    versão para impressão/PDF em paisagem."""
    inicio, fim = _periodo_padrao()
    inicio = _data_iso(request.args.get('start')) or inicio
    fim = _data_iso(request.args.get('end')) or fim
    if fim < inicio:
        inicio, fim = fim, inicio

    # Status: nada marcado = todos
    statuses = [s for s in STATUS_ROTULOS
                if request.args.get(f'status_{s}') == '1']

    query = Reservation.query.filter(
        Reservation.unity_id == current_unity_id(),
        Reservation.date >= inicio,
        Reservation.date <= fim)
    if statuses:
        query = query.filter(Reservation.status.in_(statuses))

    # Vínculos opcionais (sala, docente, curso e disciplina)
    room_id = request.args.get('room_id', type=int)
    teacher_id = request.args.get('teacher_id', type=int)
    course_id = request.args.get('course_id', type=int)
    subject_id = request.args.get('subject_id', type=int)
    if room_id:
        query = query.filter(Reservation.classroom_id == room_id)
    if teacher_id:
        query = query.filter(Reservation.teacher_id == teacher_id)
    if course_id:
        query = query.filter(Reservation.course_id == course_id)
    if subject_id:
        query = query.filter(Reservation.subject_id == subject_id)

    # Período do dia: reservas que ocorrem em qualquer janela marcada
    periodos = [p for p in ORDEM_PERIODOS
                if request.args.get(f'periodo_{p}') == '1']
    if periodos:
        janelas = [and_(Reservation.start_time < PERIODOS_DIA[p][2],
                        Reservation.end_time > PERIODOS_DIA[p][1])
                   for p in periodos]
        query = query.filter(or_(*janelas))

    # Busca livre no título da reserva
    texto = (request.args.get('texto') or '').strip()
    if texto:
        query = query.filter(Reservation.title.ilike(f'%{texto}%'))

    ordem = request.args.get('ordem', 'asc')
    if ordem not in ORDENS:
        ordem = 'asc'
    if ordem == 'desc':
        query = query.order_by(Reservation.date.desc(),
                               Reservation.start_time.desc())
    else:
        query = query.order_by(Reservation.date, Reservation.start_time)

    reservas = query.all()

    agrupar = request.args.get('agrupar', 'data')
    if agrupar not in AGRUPAMENTOS:
        agrupar = 'data'

    minutos_total = sum(_minutos_reserva(r) for r in reservas)
    hoje = date.today()

    def _faixa_data(d):
        faixa = f"{DIAS_SEMANA_PT[d.weekday()]}, {d:%d/%m/%Y}"
        if d == hoje:
            faixa += ' · hoje'
        return faixa

    # Agrupamento: cada grupo vira uma faixa na tabela com total próprio
    grupos = []
    if agrupar == 'nenhum':
        grupos = [{'titulo': None, 'reservas': reservas,
                   'contagem': len(reservas), 'minutos': minutos_total}]
    else:
        if agrupar == 'data':
            def chave(r):
                return r.date
            def rotulo(valor):
                return _faixa_data(valor)
        elif agrupar == 'sala':
            def chave(r):
                return f"{r.classroom.code} — {r.classroom.name}"
            def rotulo(valor):
                return valor
        else:
            chaves = {
                'professor': (lambda r: (r.teacher.full_name if r.teacher
                                         else ROTULOS_SEM_VINCULO['professor'])),
                'curso': (lambda r: (r.course.name if r.course
                                     else ROTULOS_SEM_VINCULO['curso'])),
                'disciplina': (lambda r: (r.subject.name if r.subject
                                          else ROTULOS_SEM_VINCULO['disciplina'])),
            }
            chave = chaves[agrupar]

            def rotulo(valor):
                return valor

        por_grupo = {}
        for r in reservas:
            por_grupo.setdefault(chave(r), []).append(r)

        if agrupar == 'data':
            # Ordena pelas datas de verdade — o rótulo ("Quinta-feira, 01/10/2026")
            # não ordena cronologicamente
            chaves_ordenadas = sorted(por_grupo, reverse=(ordem == 'desc'))
        else:
            chaves_ordenadas = sorted(por_grupo, key=lambda v: str(v).casefold())
        for valor in chaves_ordenadas:
            rs = por_grupo[valor]
            grupos.append({'titulo': rotulo(valor), 'reservas': rs,
                           'contagem': len(rs),
                           'minutos': sum(_minutos_reserva(r) for r in rs)})
    for grupo in grupos:
        grupo['horas'] = _duracao_horas(grupo['minutos'])

    # Descrição dos filtros aplicados, exibida sob o título
    filtros = [f"Período: {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}"]
    if statuses and len(statuses) < len(STATUS_ROTULOS):
        filtros.append('Status: ' + _juntar_nomes(
            [STATUS_ROTULOS[s].lower() + 's' for s in statuses]))
    for valor, rotulo, prefixo in (
            (room_id, 'room_id', 'Sala'), (teacher_id, 'teacher_id', 'Professor'),
            (course_id, 'course_id', 'Curso'), (subject_id, 'subject_id', 'Disciplina')):
        if valor:
            filtros.append(f"{prefixo}: {_nome_vinculo(rotulo, valor)}")
    if periodos:
        filtros.append('Período do dia: ' + _juntar_nomes(
            [PERIODOS_DIA[p][0] for p in periodos]))
    if texto:
        filtros.append(f"Busca: \u201c{texto}\u201d")
    filtros.append(f"Agrupado por: {AGRUPAMENTOS[agrupar]}")
    if ordem == 'desc':
        filtros.append('Ordem: decrescente')

    gerado_em = datetime.now().strftime('%d/%m/%Y às %H:%M')

    return render_template('relatorios/personalizado.html',
                           inicio=inicio, fim=fim, ordem=ordem,
                           agrupar=agrupar, statuses=statuses,
                           periodos=periodos, texto=texto,
                           meta_filtros=' · '.join(filtros),
                           gerado_em=gerado_em,
                           grupos=grupos,
                           tem_reservas=bool(reservas),
                           kpi_reservas=len(reservas),
                           kpi_horas=_duracao_horas(minutos_total),
                           kpi_salas=len({r.classroom_id for r in reservas}),
                           kpi_docentes=len({r.teacher_id
                                             for r in reservas if r.teacher_id}),
                           classrooms=Classroom.query.filter_by(
                               unity_id=current_unity_id(), is_active=True
                           ).order_by(Classroom.code).all(),
                           teachers=User.query.filter(
                               User.is_active_user == True,  # noqa: E712
                               ((User.profile_type == 'teacher')
                                | (User.is_teacher == True)),  # noqa: E712
                               User.escopo_unidade(current_unity_id()),
                           ).order_by(User.full_name).all(),
                           courses=Course.query.filter_by(
                               unity_id=current_unity_id(), is_active=True
                           ).order_by(Course.name).all(),
                           subjects=Subject.query.filter_by(
                               unity_id=current_unity_id(), is_active=True
                           ).order_by(Subject.name).all())


def _nome_vinculo(campo, valor):
    """Nome legível de um vínculo escolhido no filtro (sala/professor/curso/
    disciplina) para a linha de filtros aplicados."""
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
