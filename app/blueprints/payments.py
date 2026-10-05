import os
import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user
from app.models import (User, TeacherOvertimePay, TeacherMealAllowance,
                        OvertimeMonthClosure, CourseType)
from app.forms import FormTeacherOvertimePay, FormValeAlimentacao
from app.extensions import db
from app.unity_context import current_unity_id
from datetime import datetime
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Border, Side, Font, Alignment
from io import BytesIO
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from app.permissions import require_module, require_permission
from app.utils import redirect_back, redirect_preserving_args

bp = Blueprint('payments', __name__, url_prefix='/payments')

PAYS_PER_PAGE = 25

# Máscara do Código Orçamentário: o código curto tem 9 dígitos
# (xx.xx.xxxx.x) e o longo tem 14 (xx.xx.xxxx.xx.xxxx). Os grupos avançam
# 2.2.4.2.4 — no curto, o 4º grupo fica com 1 dígito.
BUDGET_CODE_GROUPS = (2, 2, 4, 2, 4)
BUDGET_CODE_LENGTHS = (9, 14)

MONTH_NAMES_PT = ('Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
                  'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro')

# Janela de lançamento da Hora Extra: do dia 21 do mês anterior ao dia 20 do
# mês corrente, tudo que é lançado conta para o mês corrente; depois do dia
# 20, conta para o mês seguinte. O Mês Base segue essa janela por padrão — o
# formulário permite antecipar a entrada para o mês seguinte selecionando o
# próximo mês no Mês de Referência.
MONTH_WINDOW_DAY = 20


def _mes_atual(now=None):
    """Mês corrente do calendário (YYYY-MM)."""
    return (now or datetime.now()).strftime('%Y-%m')


def _mes_anterior_de(mes):
    """Mês anterior a um mês dado (YYYY-MM → YYYY-MM)."""
    ano, mes = int(mes[:4]), int(mes[5:7])
    mes -= 1
    if mes < 1:
        mes, ano = 12, ano - 1
    return f'{ano:04d}-{mes:02d}'


def _mes_anterior(now=None):
    """Mês anterior do calendário (YYYY-MM)."""
    return _mes_anterior_de(_mes_atual(now))


def _proximo_mes(now=None):
    """Mês seguinte do calendário (YYYY-MM)."""
    now = now or datetime.now()
    mes, ano = now.month + 1, now.year
    if mes > 12:
        mes, ano = 1, ano + 1
    return f'{ano:04d}-{mes:02d}'


def _month_base_janela(now=None):
    """Mês de referência do lançamento pela janela 20→20."""
    now = now or datetime.now()
    return _mes_atual(now) if now.day <= MONTH_WINDOW_DAY else _proximo_mes(now)


def _rotulo_mes(month_base):
    """'Novembro/2026' — rótulo legível do mês de referência (YYYY-MM)."""
    try:
        parsed = datetime.strptime(month_base, '%Y-%m')
    except (TypeError, ValueError):
        return month_base or '—'
    return f'{MONTH_NAMES_PT[parsed.month - 1]}/{parsed.year}'


def _mes_fechado(unity_id, month_base):
    """O mês de referência já foi fechado nesta unidade?"""
    return db.session.query(OvertimeMonthClosure.id).filter_by(
        unity_id=unity_id, month_base=month_base).first() is not None


def _meses_fechados(unity_id):
    """Conjunto dos meses já fechados na unidade (uma consulta por página)."""
    return {c.month_base for c in
            OvertimeMonthClosure.query.filter_by(unity_id=unity_id).all()}


def _mes_valido(valor):
    """Valor em formato de mês (YYYY-MM) ou None."""
    if valor and re.match(r'^\d{4}-\d{2}$', valor):
        return valor
    return None


def _opcoes_mes_datas(referencia, extra=None):
    """Opções do seletor de mês das datas, relativas ao mês de referência
    escolhido: o mês anterior a ele e ele próprio. Na edição, entra também o
    mês já gravado no lançamento, quando distinto, para que as datas salvas
    continuem acessíveis no calendário."""
    mes_anterior = _mes_anterior_de(referencia)
    opcoes = [(mes_anterior, _rotulo_mes(mes_anterior)),
              (referencia, _rotulo_mes(referencia))]
    if extra and extra not in {valor for valor, _ in opcoes}:
        opcoes.append((extra, _rotulo_mes(extra)))
    return opcoes


def _mes_datas_salvas(overtime):
    """Mês (YYYY-MM) ao qual pertencem os dias gravados: o campo dates_month
    (lançamentos novos) ou, nos antigos, o próprio mês base — datas completas
    gravadas por uma versão intermediária também são reconhecidas."""
    if overtime.dates_month:
        return overtime.dates_month
    for token in (overtime.multiple_dates or '').split(','):
        m = re.match(r'^\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*$', token)
        if m:
            return f'{m.group(3)}-{int(m.group(2)):02d}'
    return overtime.month_base


def _mes_datas_postado(referencia, extra=None):
    """Mês das datas selecionado no formulário: aceito apenas quando é o mês
    de referência, o anterior ou o já gravado (edição). Fora disso grava nulo —
    a edição então assume o mês base, como nos lançamentos antigos."""
    permitidos = {_mes_anterior_de(referencia), referencia}
    if extra:
        permitidos.add(extra)
    mes = _mes_valido(request.form.get('dates_month'))
    return mes if mes and mes in permitidos else None

# ================= HELPER FUNCTIONS =================

def _teachers_for_current_unity():
    """Professores da unidade ativa + contas globais (para dropdowns de pagamento)."""
    uid = current_unity_id()
    return User.query.filter(
        User.profile_type == 'teacher',
        User.is_active_user == True,
        User.escopo_unidade(uid)
    ).order_by(User.full_name).all()

def format_budget_code(value):
    """Aplica a máscara de pontos ao Código Orçamentário.

    Códigos com 9 dígitos viram xx.xx.xxxx.x e com 14 dígitos viram
    xx.xx.xxxx.xx.xxxx. Qualquer outro formato é devolvido sem alterações.
    """
    if not value:
        return value
    digits = re.sub(r'\D', '', value)
    if len(digits) not in BUDGET_CODE_LENGTHS:
        return value.strip()
    groups, pos = [], 0
    for size in BUDGET_CODE_GROUPS:
        if pos >= len(digits):
            break
        groups.append(digits[pos:pos + size])
        pos += size
    return '.'.join(groups)


@bp.app_template_filter('budget_code')
def budget_code_filter(value):
    """Máscara do Código Orçamentário para exibição nas listagens."""
    return format_budget_code(value)


@bp.app_template_filter('hours_minutes')
def hours_minutes_filter(value):
    """Hora decimal como hora/minuto: 4.5 → '4h30', 4.33 → '4h20',
    4 → '4h'. Único formato de carga horária exibido na consulta e enviado à
    planilha — a hora decimal não é mais usada."""
    if value is None:
        return '—'
    horas, minutos = divmod(decimal_to_minutes(value), 60)
    return f'{horas}h' + (f'{minutos:02d}' if minutos else '')


def _month_options():
    """Meses para a caixa de seleção da consulta: os que já possuem lançamentos
    na unidade + o mês atual e o mês da janela, do mais recente para o mais
    antigo."""
    rows = (TeacherOvertimePay.query.with_entities(TeacherOvertimePay.month_base)
            .filter_by(unity_id=current_unity_id()).distinct().all())
    months = {row[0] for row in rows if row[0]}
    months.add(_mes_atual())
    months.add(_month_base_janela())
    options = []
    for value in sorted(months, reverse=True):
        options.append((value, _rotulo_mes(value)))
    return options


def _get_overtime_scoped(overtime_id):
    overtime = db.get_or_404(TeacherOvertimePay, overtime_id)
    if overtime.unity_id != current_unity_id():
        abort(404)
    return overtime

def parse_currency(value_str):
    """Converte texto de valor monetário em Decimal.

    Aceita os formatos pt-BR e en-US: '15,50', '15.50' e '1.234,56'.
    O ponto só é tratado como separador de milhar quando há vírgula decimal
    na string — sem vírgula, o ponto é decimal ('15.50' → 15.50, não 1550).
    """
    if not value_str:
        return None
    cleaned = value_str.strip()
    if ',' in cleaned:
        cleaned = cleaned.replace('.', '').replace(',', '.')
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def decimal_to_minutes(value):
    """Hora decimal em minutos inteiros com arredondamento comercial
    (4.33 → 260 = 4h20). Usado ao reabrir o formulário e na exibição."""
    return int((Decimal(str(value)) * 60).to_integral_value(rounding=ROUND_HALF_UP))

# ================= OVERTIME ROUTES =================

@bp.route('/overtime/list')
@login_required
@require_permission('payment:read')
@require_module('finance')
def list_overtime():
    # A consulta abre no mês atual do calendário: é ele que o botão "Fechar
    # Mês" tranca — os lançamentos do mês seguinte permanecem editáveis. A
    # caixa de seleção permite escolher outro mês ou "Todos os meses" (vazio).
    filter_month = request.args.get('month_base')
    if filter_month is None:
        filter_month = _mes_atual()
    filter_teacher = request.args.get('teacher_filter', type=int)

    # CORREÇÃO: a condição anterior era dead-code — @require_permission('payment:read') já garante
    # que qualquer usuário aqui tem payment:read, tornando o bloco de filtro por professor
    # inalcançável. Agora aplica os filtros normalmente para todos.
    query = TeacherOvertimePay.query.filter_by(unity_id=current_unity_id())
    if filter_month:
        query = query.filter_by(month_base=filter_month)
    if filter_teacher:
        query = query.filter_by(teacher_id=filter_teacher)

    pagination = query.order_by(TeacherOvertimePay.created_at.desc()) \
        .paginate(page=request.args.get('page', 1, type=int),
                  per_page=PAYS_PER_PAGE, error_out=False)
    list_teachers = _teachers_for_current_unity()

    fechamento = None
    if filter_month and filter_month in _meses_fechados(current_unity_id()):
        fechamento = OvertimeMonthClosure.query.filter_by(
            unity_id=current_unity_id(), month_base=filter_month).first()

    return render_template('payments/list_overtime.html', infos=pagination.items, pagination=pagination,
                           list_teachers=list_teachers, month_options=_month_options(),
                           filter_month=filter_month, filter_teacher=filter_teacher,
                           filter_month_label=_rotulo_mes(filter_month),
                           meses_fechados=_meses_fechados(current_unity_id()),
                           fechamento=fechamento)

@bp.route('/overtime/create', methods=['GET', 'POST'])
@login_required
@require_permission('payment:create')
@require_module('finance')
def create_overtime():
    form = FormTeacherOvertimePay()
    form.teacher.choices = [(t.id, t.full_name) for t in _teachers_for_current_unity()]
    form.course_type.choices = _course_type_choices()

    # Mês de referência: a janela 20→20 define o padrão (lançamentos entre o
    # dia 21 do mês anterior e o dia 20 contam para o mês atual; depois disso,
    # para o próximo). Exceção: selecionar o próximo mês no Mês de Referência
    # inclui a entrada no próximo mês de pagamento, mesmo antes do dia 20.
    mes_atual, proximo_mes = _mes_atual(), _proximo_mes()
    month_base = (proximo_mes if request.form.get('reference_month') == proximo_mes
                  else _month_base_janela())

    # O campo Mês segue o mês de referência escolhido: oferece o mês anterior
    # a ele e ele próprio (o JavaScript reconstrói as opções quando a seleção
    # muda). O mês das datas é gravado para a edição restaurar o calendário.
    referencia_selecionada = (_mes_valido(request.form.get('reference_month'))
                              or _month_base_janela())
    opcoes_datas = _opcoes_mes_datas(referencia_selecionada)
    mes_datas_selecionada = request.form.get('dates_month')
    if mes_datas_selecionada not in {valor for valor, _ in opcoes_datas}:
        mes_datas_selecionada = referencia_selecionada

    if form.validate_on_submit():
        # Fechamento antecipado: se a unidade já fechou o mês de referência
        # deste lançamento (janela ou próximo mês selecionado), ele não entra.
        if _mes_fechado(current_unity_id(), month_base):
            flash('Erro: O mês de referência deste lançamento já foi fechado. '
                  'Não é possível lançar em um mês fechado.', 'danger')
            return redirect(url_for('payments.create_overtime'))

        hourly_value = parse_currency(form.hourly_value.data)
        if hourly_value is None or hourly_value <= 0:
            flash('Erro: O Valor H/a deve ser maior que 0.', 'danger')
            return redirect(url_for('payments.create_overtime'))

        # Hora + minuto já convertidos para hora decimal pelo formulário
        weekly_workload = form.workload_decimal()
        if weekly_workload is None or weekly_workload <= 0:
            flash('Erro: A Carga Horária Semanal deve ser maior que 0.', 'danger')
            return redirect(url_for('payments.create_overtime'))

        overtime = TeacherOvertimePay(
            teacher_id=form.teacher.data, teaching_level=form.teaching_level.data,
            course_type_id=form.course_type.data,
            unity_id=current_unity_id(),
            weekly_workload=weekly_workload, hourly_value=hourly_value,
            budget_code=format_budget_code(form.budget_code.data), shift=form.shift.data,
            multiple_dates=form.multiple_dates.data, justification=form.justification.data,
            observation=form.observation.data,
            month_base=month_base, dates_month=_mes_datas_postado(referencia_selecionada),
            accountable_id=current_user.id
        )
        db.session.add(overtime)
        db.session.commit()
        flash('Lançamento de Hora Extra realizado!', 'success')
        return redirect_preserving_args('payments.list_overtime')

    return render_template('payments/form_overtime.html', form=form, title='Nova Hora Extra',
                           modo_criacao=True,
                           opcoes_referencia=[(mes_atual, _rotulo_mes(mes_atual)),
                                              (proximo_mes, _rotulo_mes(proximo_mes))],
                           referencia_selecionada=referencia_selecionada,
                           valor_proximo_mes=proximo_mes,
                           nomes_meses=MONTH_NAMES_PT,
                           opcoes_mes_datas=opcoes_datas,
                           mes_datas_selecionada=mes_datas_selecionada)

@bp.route('/overtime/edit/<int:overtime_id>', methods=['GET', 'POST'])
@login_required
@require_permission('payment:edit')
@require_module('finance')
def edit_overtime(overtime_id):
    overtime = _get_overtime_scoped(overtime_id)

    # O mês fechado é o único tranca: sem fechamento, o lançamento permanece
    # editável (os antigos bloqueios de 30 dias e de mês anterior saíram).
    if _mes_fechado(overtime.unity_id, overtime.month_base):
        flash('Erro: O mês deste lançamento já foi fechado; o registro não pode mais ser alterado.', 'danger')
        return redirect_back('payments.list_overtime')

    form = FormTeacherOvertimePay(obj=overtime)
    form.teacher.choices = [(t.id, t.full_name) for t in _teachers_for_current_unity()]
    form.course_type.choices = _course_type_choices()

    # Mês ao qual pertencem os dias gravados (dates_month, ou o mês base nos
    # lançamentos antigos): usado no POST e na reexibição do calendário.
    mes_datas = _mes_datas_salvas(overtime)

    if request.method == 'GET':
        # Os relationships overtime.teacher e overtime.course_type (objetos)
        # têm os mesmos nomes dos campos: o WTForms tenta int(objeto), falha
        # em silêncio e a seleção volta para o primeiro da lista — restaura
        # pelos ids.
        form.teacher.data = overtime.teacher_id
        form.course_type.data = overtime.course_type_id
        form.hourly_value.data = f"{overtime.hourly_value:.2f}".replace('.', ',')
        # A carga em hora decimal volta para os dois campos (ex: 4.33 → 4h20)
        total_minutes = decimal_to_minutes(overtime.weekly_workload)
        form.weekly_workload_hours.data = total_minutes // 60
        form.weekly_workload_minutes.data = total_minutes % 60

    if form.validate_on_submit():
        hourly_value = parse_currency(form.hourly_value.data)
        if hourly_value is None or hourly_value <= 0:
            flash('Erro: O Valor H/a deve ser maior que 0.', 'danger')
            return redirect(url_for('payments.edit_overtime', overtime_id=overtime_id))

        weekly_workload = form.workload_decimal()
        if weekly_workload is None or weekly_workload <= 0:
            flash('Erro: A Carga Horária Semanal deve ser maior que 0.', 'danger')
            return redirect(url_for('payments.edit_overtime', overtime_id=overtime_id))

        overtime.teacher_id = form.teacher.data
        overtime.teaching_level = form.teaching_level.data
        overtime.course_type_id = form.course_type.data
        overtime.weekly_workload = weekly_workload
        overtime.hourly_value = hourly_value
        overtime.budget_code = format_budget_code(form.budget_code.data)
        overtime.shift = form.shift.data
        overtime.multiple_dates = form.multiple_dates.data
        overtime.justification = form.justification.data
        overtime.observation = form.observation.data
        # O Mês Base não muda na edição. O mês das datas pode ser reescolhido
        # (mês base ou anterior); sem o campo no POST, preserva o gravado.
        if 'dates_month' in request.form:
            overtime.dates_month = _mes_datas_postado(overtime.month_base, extra=mes_datas)
        overtime.accountable_id = current_user.id

        db.session.commit()
        flash('Alteração realizada!', 'success')
        return redirect_preserving_args('payments.list_overtime')

    # O Mês Base não muda na edição: é definido no lançamento (janela 20→20 ou
    # próximo mês selecionado) e apenas exibido. O campo Mês oferece o mês
    # anterior e o próprio mês base, mais o mês já gravado quando distinto.
    opcoes_datas = _opcoes_mes_datas(overtime.month_base, extra=mes_datas)
    mes_datas_selecionada = request.form.get('dates_month')
    if mes_datas_selecionada not in {valor for valor, _ in opcoes_datas}:
        mes_datas_selecionada = mes_datas

    return render_template('payments/form_overtime.html', form=form, title='Editar Hora Extra',
                           modo_criacao=False,
                           month_label=_rotulo_mes(overtime.month_base),
                           nomes_meses=MONTH_NAMES_PT,
                           opcoes_mes_datas=opcoes_datas,
                           mes_datas_selecionada=mes_datas_selecionada)

@bp.route('/overtime/delete/<int:overtime_id>', methods=['POST'])
@login_required
@require_permission('payment:delete')
@require_module('finance')
def delete_overtime(overtime_id):
    overtime = _get_overtime_scoped(overtime_id)
    # Mesma regra do edit: mês fechado é o único bloqueio.
    if _mes_fechado(overtime.unity_id, overtime.month_base):
        flash('Erro: O mês deste lançamento já foi fechado; o registro não pode mais ser excluído.', 'danger')
        return redirect_back('payments.list_overtime')

    db.session.delete(overtime)
    db.session.commit()
    flash('Registro de Hora Extra excluído', 'success')
    return redirect_back('payments.list_overtime')

# ================= CLOSE MONTH (FECHAMENTO) =================

@bp.route('/overtime/close-month', methods=['POST'])
@login_required
@require_permission('payment:close_month')
@require_module('finance')
def close_month_overtime():
    """Fecha os lançamentos do mês de referência: grava o fechamento (trava
    edição e exclusão do mês) e devolve a planilha final do mês para download."""
    month_base = request.form.get('month_base', '')
    if not re.match(r'^\d{4}-\d{2}$', month_base):
        flash('Erro: Mês inválido para fechamento.', 'danger')
        return redirect(url_for('payments.list_overtime'))

    unity_id = current_unity_id()
    if _mes_fechado(unity_id, month_base):
        flash(f'Os lançamentos de {_rotulo_mes(month_base)} já estavam fechados.', 'info')
        return redirect(url_for('payments.list_overtime', month_base=month_base))

    overtimes = TeacherOvertimePay.query.filter_by(
        unity_id=unity_id, month_base=month_base).order_by(TeacherOvertimePay.created_at).all()
    if not overtimes:
        flash(f'Erro: Não há lançamentos em {_rotulo_mes(month_base)} para fechar.', 'danger')
        return redirect(url_for('payments.list_overtime', month_base=month_base))

    db.session.add(OvertimeMonthClosure(
        unity_id=unity_id, month_base=month_base, closed_by_id=current_user.id))
    db.session.commit()

    output = _planilha_overtime(overtimes, month_base)
    if output is None:
        # Fechamento gravado, mas sem o modelo no servidor: avisa o operador
        # para restabelecer o arquivo e rebaixar pela Exportação.
        flash(f'Lançamentos de {_rotulo_mes(month_base)} fechados, mas o modelo '
              f'da planilha não foi encontrado no servidor.', 'warning')
        return redirect(url_for('payments.list_overtime', month_base=month_base))

    flash(f'Lançamentos de {_rotulo_mes(month_base)} fechados. A planilha final '
          f'do mês foi gerada para download.', 'success')
    return current_app.response_class(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': f'attachment; filename=hora_extra_{month_base}_fechada.xlsx'}
    )

# ================= MEAL ALLOWANCE ROUTES (RH) =================

def _meal_choices():
    return [(t.id, t.full_name) for t in _teachers_for_current_unity()]


def _course_type_choices():
    """Tipos de curso ativos (catálogo do Painel Admin) para o dropdown."""
    return [(ct.id, ct.name) for ct in
            CourseType.query.filter_by(is_active=True).order_by(CourseType.name).all()]


def _get_meal_scoped(entry_id):
    entry = db.get_or_404(TeacherMealAllowance, entry_id)
    if entry.unity_id != current_unity_id():
        abort(404)
    return entry


def _render_meal_allowance(form, teacher_filter=None):
    """Página completa do módulo (formulário + filtro + listagem) — usada no
    GET e no re-render do POST com erro de validação."""
    query = TeacherMealAllowance.query.filter_by(unity_id=current_unity_id())
    if teacher_filter:
        query = query.filter_by(teacher_id=teacher_filter)
    pagination = query.order_by(TeacherMealAllowance.created_at.desc(),
                                TeacherMealAllowance.id.desc()) \
        .paginate(page=request.args.get('page', 1, type=int),
                  per_page=PAYS_PER_PAGE, error_out=False)
    # Total da unidade (sem filtro): alimenta a confirmação do "Limpar Tudo".
    total_entries = TeacherMealAllowance.query \
        .filter_by(unity_id=current_unity_id()).count()
    return render_template('payments/meal_allowance.html', form=form,
                           entries=pagination.items, pagination=pagination,
                           list_teachers=_teachers_for_current_unity(),
                           filter_teacher=teacher_filter,
                           total_entries=total_entries)


@bp.route('/meal-allowance', methods=['GET'])
@login_required
@require_permission('meal:read')
@require_module('finance')
def list_meal_allowance():
    """Vale Alimentação - Professores: formulário de lançamento em cima e a
    listagem (com filtro por professor) abaixo, na mesma página."""
    form = FormValeAlimentacao()
    form.teacher.choices = _meal_choices()
    return _render_meal_allowance(
        form, teacher_filter=request.args.get('teacher_filter', type=int))


@bp.route('/meal-allowance/add', methods=['POST'])
@login_required
@require_permission('meal:create')
@require_module('finance')
def add_meal_allowance():
    form = FormValeAlimentacao()
    form.teacher.choices = _meal_choices()
    if form.validate_on_submit():
        professor = db.session.get(User, form.teacher.data)
        db.session.add(TeacherMealAllowance(
            teacher_id=form.teacher.data, days=form.days.data,
            unity_id=current_unity_id(), created_by_id=current_user.id))
        db.session.commit()
        flash(f'Lançamento adicionado: {professor.full_name} — '
              f'{form.days.data} dia(s) trabalhados.', 'success')
        # Mantém o filtro ativo: quem lançou filtrando por um professor
        # continua vendo a lista dele.
        return redirect_preserving_args('payments.list_meal_allowance')
    return _render_meal_allowance(
        form, teacher_filter=request.args.get('teacher_filter', type=int))


@bp.route('/meal-allowance/<int:entry_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('meal:edit')
@require_module('finance')
def edit_meal_allowance(entry_id):
    entry = _get_meal_scoped(entry_id)
    form = FormValeAlimentacao(obj=entry)
    form.teacher.choices = _meal_choices()

    if request.method == 'GET':
        # O relationship entry.teacher (objeto User) tem o mesmo nome do
        # campo: restaura a seleção pelo id, como na edição de Hora Extra.
        form.teacher.data = entry.teacher_id

    if form.validate_on_submit():
        entry.teacher_id = form.teacher.data
        entry.days = form.days.data
        db.session.commit()
        flash('Alteração realizada!', 'success')
        return redirect_preserving_args('payments.list_meal_allowance')

    return render_template('payments/meal_allowance_form.html', form=form, entry=entry)


@bp.route('/meal-allowance/<int:entry_id>/delete', methods=['POST'])
@login_required
@require_permission('meal:delete')
@require_module('finance')
def delete_meal_allowance(entry_id):
    entry = _get_meal_scoped(entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash('Lançamento do Vale Alimentação excluído.', 'success')
    return redirect_back('payments.list_meal_allowance')


@bp.route('/meal-allowance/clear', methods=['POST'])
@login_required
@require_permission('meal:delete')
@require_module('finance')
def clear_meal_allowance():
    """Remove TODOS os lançamentos de Vale Alimentação da unidade atual,
    independentemente do filtro aplicado na listagem."""
    qtde = (TeacherMealAllowance.query
            .filter_by(unity_id=current_unity_id())
            .delete(synchronize_session=False))
    db.session.commit()
    flash(f'{qtde} lançamento(s) do Vale Alimentação removido(s).',
          'success' if qtde else 'info')
    return redirect(url_for('payments.list_meal_allowance'))


@bp.route('/meal-allowance/export')
@login_required
@require_permission('meal:read')
@require_module('finance')
def export_meal_allowance():
    """Exportação simples do Vale Alimentação: uma linha por professor com o
    total de dias trabalhados (soma dos lançamentos), respeitando o filtro de
    professor quando ativo."""
    teacher_id = request.args.get('teacher_filter', type=int)
    query = TeacherMealAllowance.query.filter_by(unity_id=current_unity_id())
    if teacher_id:
        query = query.filter_by(teacher_id=teacher_id)
    entries = query.all()

    if not entries:
        flash('Nenhum lançamento de Vale Alimentação para exportar.', 'danger')
        return redirect(url_for('payments.list_meal_allowance'))

    totais = {}
    for entry in entries:
        nome = entry.teacher.full_name
        totais[nome] = totais.get(nome, 0) + entry.days

    wb = Workbook()
    ws = wb.active
    ws.title = 'Vale Alimentação'
    ws.append(['Professor', 'Dias Trabalhados'])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for nome in sorted(totais):
        ws.append([nome, totais[nome]])
    ws.column_dimensions['A'].width = 40
    ws.column_dimensions['B'].width = 18

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return current_app.response_class(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition':
                 'attachment; filename=vale_alimentacao_professores.xlsx'}
    )

def _planilha_overtime(overtimes, month_base):
    """Monta a planilha no modelo institucional (base_pagamento_extra.xlsx,
    aba Extra NEB). A carga horária sai em hora e minuto inteiros (4h30) —
    a planilha não usa mais a conversão para hora decimal. Retorna o BytesIO
    pronto para a resposta de download."""
    template_path = os.path.join(current_app.root_path, 'static', 'templates_excel', 'base_pagamento_extra.xlsx')
    if not os.path.exists(template_path):
        return None
    workbook = load_workbook(filename=template_path)
    ws = workbook['Extra NEB']

    if month_base:
        try:
            base_date = datetime.strptime(month_base, "%Y-%m").date()
            ws.cell(row=4, column=4, value=base_date)
        except ValueError:
            pass

    border = Border(left=Side(border_style='thin', color='FF000000'),
                    right=Side(border_style='thin', color='FF000000'),
                    top=Side(border_style='thin', color='FF000000'),
                    bottom=Side(border_style='thin', color='FF000000'))
    font = Font(name='Calibri', size=14)
    alignment = Alignment(horizontal='center', vertical='center', wrapText=True)

    for merged_cell in list(ws.merged_cells.ranges):
        ws.unmerge_cells(str(merged_cell))

    # Todas as linhas são inseridas de uma única vez antes de escrever os
    # dados (inserir dentro do loop deslocaria o conteúdo do template).
    ws.insert_rows(7, len(overtimes))

    for baseline, data in enumerate(overtimes, start=7):
        minutos = decimal_to_minutes(data.weekly_workload) if data.weekly_workload else 0
        # Ordem dos cabeçalhos do modelo (linha 6): Tipo de Curso logo após o
        # Nível de Docência, e Observação por último.
        cell_data = [
            (1, data.teacher.full_name),
            (2, data.teaching_level),
            (3, data.course_type.name if data.course_type else '—'),
            (4, f'{minutos // 60}h{minutos % 60:02d}'),
            (5, float(data.hourly_value) if data.hourly_value else 0),
            (6, data.multiple_dates or ''),
            (7, data.shift),
            (8, format_budget_code(data.budget_code)),
            (9, data.justification or ''),
            (10, data.observation or ''),
        ]

        for col, value in cell_data:
            cell = ws.cell(row=baseline, column=col, value=value)
            cell.border = border
            cell.font = font
            cell.alignment = alignment

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output


# ================= EXCEL EXPORT ROUTES =================

@bp.route('/export/overtime')
@login_required
@require_permission('payment:export')
@require_module('finance')
def export_excel_overtime():
    month_base = request.args.get('month_base', '')
    teacher_id = request.args.get('teacher_filter', type=int)

    if not month_base and not teacher_id:
        flash('Selecione pelo menos o Mês Base ou o Professor para exportar.', 'danger')
        return redirect(url_for('payments.list_overtime'))

    query = TeacherOvertimePay.query.filter_by(unity_id=current_unity_id())
    if month_base:
        query = query.filter_by(month_base=month_base)
    if teacher_id:
        query = query.filter_by(teacher_id=teacher_id)

    overtimes = query.all()

    if not overtimes:
        flash('Informações não encontradas para os filtros selecionados.', 'danger')
        return redirect(url_for('payments.list_overtime'))

    output = _planilha_overtime(overtimes, month_base)
    if output is None:
        flash('Modelo do Excel não encontrado no servidor.', 'danger')
        return redirect(url_for('payments.list_overtime'))
    return current_app.response_class(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=overtime_export.xlsx'}
    )
