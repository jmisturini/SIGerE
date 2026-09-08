import os
import re
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, abort
from flask_login import login_required, current_user
from app.models import User, TeacherOvertimePay
from app.forms import FormTeacherOvertimePay
from app.extensions import db
from app.unity_context import current_unity_id
from datetime import datetime, timedelta
from openpyxl import load_workbook
from openpyxl.styles import Border, Side, Font, Alignment
from io import BytesIO
from decimal import Decimal, InvalidOperation
from app.permissions import require_permission

bp = Blueprint('payments', __name__, url_prefix='/payments')

PAYS_PER_PAGE = 25

# ================= HELPER FUNCTIONS =================

def _teachers_for_current_unity():
    """Professores da unidade ativa + contas globais (para dropdowns de pagamento)."""
    uid = current_unity_id()
    return User.query.filter(
        User.profile_type == 'teacher',
        User.is_active_user == True,
        (User.unity_id == uid) | (User.unity_id.is_(None))
    ).order_by(User.full_name).all()

def _get_overtime_scoped(overtime_id):
    overtime = db.get_or_404(TeacherOvertimePay, overtime_id)
    if overtime.unity_id != current_unity_id():
        abort(404)
    return overtime

def validate_30_days_rule(created_at):
    if (datetime.now().date() - created_at.date() > timedelta(days=30)):
        flash('Erro: Registros com mais de 30 dias não podem ser alterados!', 'danger')
        return False
    return True

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

# ================= OVERTIME ROUTES =================

@bp.route('/overtime/list')
@login_required
@require_permission('payment:read')
def list_overtime():
    filter_month = request.args.get('month_base', '')
    filter_teacher = request.args.get('teacher_filter', type=int)

    # CORREÇÃO: a condição anterior era dead-code — @require_permission('payment:read') já garante
    # que qualquer usuário aqui tem payment:read, tornando o bloco de filtro por professor
    # inalcançável. Agora aplica os filtros normalmente para todos.
    query = TeacherOvertimePay.query.filter_by(unity_id=current_unity_id())
    if filter_month:
        query = query.filter_by(month_base=filter_month)
    if filter_teacher:
        query = query.filter_by(teacher_id=filter_teacher)

    pagination = db.paginate(query.order_by(TeacherOvertimePay.created_at.desc()),
                             page=request.args.get('page', 1, type=int),
                             per_page=PAYS_PER_PAGE, error_out=False)
    list_teachers = _teachers_for_current_unity()

    return render_template('payments/list_overtime.html', infos=pagination.items, pagination=pagination,
                           list_teachers=list_teachers, filter_month=filter_month, filter_teacher=filter_teacher)

@bp.route('/overtime/create', methods=['GET', 'POST'])
@login_required
@require_permission('payment:create')
def create_overtime():
    form = FormTeacherOvertimePay()
    form.teacher.choices = [(t.id, t.full_name) for t in _teachers_for_current_unity()]

    if request.method == 'GET':
        form.month_base.data = datetime.now().strftime('%Y-%m')

    if form.validate_on_submit():
        current_date = datetime.now()
        month_base_str = form.month_base.data

        if not re.match(r'^\d{4}-\d{2}$', month_base_str):
            flash('Erro: O formato do Mês Base é inválido. Utilize YYYY-MM (ex: 2024-05).', 'danger')
            return redirect(url_for('payments.create_overtime'))

        try:
            month_base = datetime.strptime(month_base_str, '%Y-%m')
        except ValueError:
            flash('Erro: O Mês Base inserido não é uma data válida.', 'danger')
            return redirect(url_for('payments.create_overtime'))

        if month_base.year == current_date.year and month_base.month == current_date.month and current_date.day > 25:
            flash('Erro: Lançamentos do mês atual só podem ser feitos até o dia 25.', 'danger')
            return redirect(url_for('payments.create_overtime'))

        hourly_value = parse_currency(form.hourly_value.data)
        if hourly_value is None or hourly_value <= 0:
            flash('Erro: O Valor H/a deve ser maior que 0.', 'danger')
            return redirect(url_for('payments.create_overtime'))

        overtime = TeacherOvertimePay(
            teacher_id=form.teacher.data, teaching_level=form.teaching_level.data,
            unity_id=current_unity_id(),
            weekly_workload=form.weekly_workload.data, hourly_value=hourly_value,
            budget_code=form.budget_code.data, shift=form.shift.data,
            multiple_dates=form.multiple_dates.data, justification=form.justification.data,
            month_base=form.month_base.data, accountable_id=current_user.id
        )
        db.session.add(overtime)
        db.session.commit()
        flash('Lançamento de Hora Extra realizado!', 'success')
        return redirect(url_for('payments.list_overtime'))

    return render_template('payments/form_overtime.html', form=form, title='Nova Hora Extra')

@bp.route('/overtime/edit/<int:overtime_id>', methods=['GET', 'POST'])
@login_required
@require_permission('payment:edit')
def edit_overtime(overtime_id):
    overtime = _get_overtime_scoped(overtime_id)

    # CORREÇÃO: comparação anterior usava apenas .month, ignorando o ano.
    # Ex.: registro de dez/2025 seria editável em jan/2026 pois 12 > 1.
    # Agora compara a data completa (ano + mês).
    now = datetime.now()
    record_ym = (overtime.created_at.year, overtime.created_at.month)
    now_ym = (now.year, now.month)
    if record_ym < now_ym or (now.date() - overtime.created_at.date() > timedelta(days=30)):
        flash('Erro: Registros dos meses anteriores não podem ser alterados.', 'danger')
        return redirect(url_for('payments.list_overtime'))

    form = FormTeacherOvertimePay(obj=overtime)
    form.teacher.choices = [(t.id, t.full_name) for t in _teachers_for_current_unity()]

    if request.method == 'GET':
        form.hourly_value.data = f"{overtime.hourly_value:.2f}".replace('.', ',')

    if form.validate_on_submit():
        month_base_str = form.month_base.data

        if not re.match(r'^\d{4}-\d{2}$', month_base_str):
            flash('Erro: O formato do Mês Base é inválido. Utilize YYYY-MM (ex: 2024-05).', 'danger')
            return redirect(url_for('payments.edit_overtime', overtime_id=overtime_id))

        try:
            datetime.strptime(month_base_str, '%Y-%m')
        except ValueError:
            flash('Erro: O Mês Base inserido não é uma data válida.', 'danger')
            return redirect(url_for('payments.edit_overtime', overtime_id=overtime_id))

        hourly_value = parse_currency(form.hourly_value.data)
        if hourly_value is None or hourly_value <= 0:
            flash('Erro: O Valor H/a deve ser maior que 0.', 'danger')
            return redirect(url_for('payments.edit_overtime', overtime_id=overtime_id))

        overtime.teacher_id = form.teacher.data
        overtime.teaching_level = form.teaching_level.data
        overtime.weekly_workload = form.weekly_workload.data
        overtime.hourly_value = hourly_value
        overtime.budget_code = form.budget_code.data
        overtime.shift = form.shift.data
        overtime.multiple_dates = form.multiple_dates.data
        overtime.justification = form.justification.data
        overtime.month_base = form.month_base.data
        overtime.accountable_id = current_user.id

        db.session.commit()
        flash('Alteração realizada!', 'success')
        return redirect(url_for('payments.list_overtime'))

    return render_template('payments/form_overtime.html', form=form, title='Editar Hora Extra')

@bp.route('/overtime/delete/<int:overtime_id>', methods=['POST'])
@login_required
@require_permission('payment:delete')
def delete_overtime(overtime_id):
    overtime = _get_overtime_scoped(overtime_id)
    # CORREÇÃO: mesma correção de ano aplicada no edit — compara (year, month) completo.
    now = datetime.now()
    record_ym = (overtime.created_at.year, overtime.created_at.month)
    now_ym = (now.year, now.month)
    if record_ym < now_ym or (now.date() - overtime.created_at.date() > timedelta(days=30)):
        flash('Erro: Registros dos meses anteriores não podem ser excluídos.', 'danger')
        return redirect(url_for('payments.list_overtime'))

    db.session.delete(overtime)
    db.session.commit()
    flash('Registro de Hora Extra excluído', 'success')
    return redirect(url_for('payments.list_overtime'))

# ================= EXCEL EXPORT ROUTES =================

@bp.route('/export/overtime')
@login_required
@require_permission('payment:export')
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

    template_path = os.path.join(current_app.root_path, 'static', 'templates_excel', 'base_pagamento_extra.xlsx')

    if not os.path.exists(template_path):
        flash('Modelo do Excel não encontrado no servidor.', 'danger')
        return redirect(url_for('payments.list_overtime'))

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

    # CORREÇÃO: antes, ws.insert_rows(baseline) era chamado a cada iteração do loop,
    # deslocando o conteúdo do template repetidamente. Agora todas as linhas são
    # inseridas de uma única vez antes de escrever os dados.
    ws.insert_rows(7, len(overtimes))

    for baseline, data in enumerate(overtimes, start=7):
        cell_data = [
            (1, data.teacher.full_name),
            (2, data.teaching_level),
            (3, data.weekly_workload),
            (4, float(data.hourly_value) if data.hourly_value else 0),
            (5, data.multiple_dates or ''),
            (6, data.shift),
            (7, data.budget_code),
            (8, data.justification or '')
        ]

        for col, value in cell_data:
            cell = ws.cell(row=baseline, column=col, value=value)
            cell.border = border
            cell.font = font
            cell.alignment = alignment

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    return current_app.response_class(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers={'Content-Disposition': 'attachment; filename=overtime_export.xlsx'}
    )
