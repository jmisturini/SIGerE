from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, jsonify
from flask_login import login_required, current_user
from contextlib import ExitStack
from app.models import Reservation, Classroom, User, Course, Subject, Holiday
from app.forms import ReservationForm
from app.extensions import db
from app.unity_context import current_unity_id
from datetime import date, datetime, time, timedelta
from app.permissions import require_permission, require_permission_or_owner
# Regras e gravação protegida contra condição de corrida vivem no serviço
# central — mantidos aqui por re-export para compatibilidade.
from app.services.scheduling import (check_conflict, check_schedule_restrictions,
                                     check_teacher_conflict, slot_locks,
                                     MAX_REPEAT_RANGE_DAYS)

RESERVATIONS_PER_PAGE = 25

bp = Blueprint('reservations', __name__, url_prefix='/reservations')

def _teachers_for_current_unity():
    """Professores da unidade ativa (contas globais sem unidade também aparecem)."""
    uid = current_unity_id()
    return User.query.filter(
        User.is_active_user == True,
        ((User.profile_type == 'teacher') | (User.is_teacher == True)),
        (User.unity_id == uid) | (User.unity_id.is_(None))
    ).order_by(User.full_name).all()

def _load_range_occupancy(classroom_id, teacher_id, start_date, end_date,
                          unity_id, start_time, end_time):
    """Pré-carrega a ocupação de um intervalo em 3 consultas (sala, docente,
    feriados) — substitui as 3 queries por dia da tela de repetição.

    Como o horário é fixo para todos os dias do lote, a sobreposição de janela
    é aplicada direto no SQL. Retorna:
        (sala_ocupada: set[date], docente_ocupado: set[date],
         feriados: dict[date, nome])
    """
    room_dates = {r.date for r in Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= start_date, Reservation.date <= end_date,
        Reservation.status == 'approved',
        Reservation.start_time < end_time,
        Reservation.end_time > start_time,
    ).all()}

    teacher_dates = set()
    if teacher_id:
        teacher_dates = {r.date for r in Reservation.query.filter(
            Reservation.teacher_id == teacher_id,
            Reservation.date >= start_date, Reservation.date <= end_date,
            Reservation.status.in_(['approved', 'pending']),
            Reservation.start_time < end_time,
            Reservation.end_time > start_time,
        ).all()}

    holidays = {h.date: h.name for h in Holiday.query.filter(
        Holiday.date >= start_date, Holiday.date <= end_date,
        Holiday.is_active == True,
        Holiday.unity_id == unity_id,
    ).all()}

    return room_dates, teacher_dates, holidays

def _courses_for_current_unity():
    return Course.query.filter_by(unity_id=current_unity_id(), is_active=True).order_by(Course.name).all()

def _subjects_for_current_unity():
    return Subject.query.filter_by(unity_id=current_unity_id(), is_active=True).order_by(Subject.name).all()

def _classrooms_for_current_unity():
    return Classroom.query.filter_by(unity_id=current_unity_id(), is_active=True).order_by(Classroom.code).all()

def _get_reservation_scoped(reservation_id):
    """Carrega a reserva da unidade ativa — reservas de outras unidades dão 404."""
    reservation = db.get_or_404(Reservation, reservation_id)
    if reservation.unity_id != current_unity_id():
        abort(404)
    return reservation

# Helper functions check_conflict, check_teacher_conflict,
# check_schedule_restrictions e slot_locks foram movidas para
# app/services/scheduling.py — ponto único de validação e gravação atômica
# (proteção contra condição de corrida) e re-exportados acima.

# AJAX endpoint to check for holiday/sunday warnings before form submission
@bp.route('/check_holiday', methods=['GET'])
@login_required
def check_holiday():
    date_str = request.args.get('date')
    if not date_str:
        return jsonify({'has_warning': False})

    try:
        check_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'has_warning': False})

    holiday = Holiday.query.filter_by(date=check_date, is_active=True, unity_id=current_unity_id()).first()
    if holiday:
        return jsonify({
            'has_warning': True,
            'message': f'Aviso: Esta data é um feriado ({holiday.name}). Reservas estão bloqueadas.'
        })

    if check_date.weekday() == 6:
        return jsonify({
            'has_warning': True,
            'message': 'Aviso: Reservas não podem ser agendadas aos domingos.'
        })

    return jsonify({'has_warning': False})

# Route to create a new reservation
@bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_permission('reservation:create')
def create():
    form = ReservationForm()

    classrooms = _classrooms_for_current_unity()
    form.classroom.choices = [(c.id, f"{c.name} ({c.code}) - Cap {c.capacity}") for c in classrooms]
    form.course.choices = [(0, '-- Nenhum --')] + [(c.id, c.name) for c in _courses_for_current_unity()]
    form.subject.choices = [(0, '-- Nenhum --')] + [(s.id, f"{s.name}") for s in _subjects_for_current_unity()]

    teachers = _teachers_for_current_unity()
    form.teacher.choices = [(0, '-- Selecionar Professor --')] + [(t.id, f"{t.full_name} ({t.department or t.sector or 'N/A'})") for t in teachers]

    preselect = request.args.get('classroom_id', type=int)
    if request.method == 'GET' and preselect:
        form.classroom.data = preselect

    if form.validate_on_submit():
        if form.date.data < date.today():
            flash('Não é possível reservar uma data no passado.', 'danger')
            return render_template('reservations/create.html', form=form, classrooms=classrooms)

        classroom_id = form.classroom.data
        # Multi-unidade: a sala precisa pertencer à unidade ativa
        classroom = db.session.get(Classroom, classroom_id)
        if not classroom or classroom.unity_id != current_unity_id():
            flash('Sala inválida para a unidade ativa.', 'danger')
            return render_template('reservations/create.html', form=form, classrooms=classrooms)

        # Gravação atômica: checagens e INSERT na mesma seção crítica por
        # (sala, data) — duas requisições simultâneas nunca gravam a mesma
        # janela (a segunda reexecuta as checagens após o commit da primeira).
        with slot_locks(classroom_id, [form.date.data]):
            allowed, restriction_msg = check_schedule_restrictions(
                form.date.data, form.start_time.data, form.end_time.data)
            if not allowed:
                flash(restriction_msg, 'danger')
                return render_template('reservations/create.html', form=form, classrooms=classrooms)

            conflict = check_conflict(classroom_id, form.date.data, form.start_time.data, form.end_time.data)
            if conflict:
                flash(f'Conflito de sala com "{conflict.title}" ({conflict.start_time.strftime("%H:%M")} - {conflict.end_time.strftime("%H:%M")})', 'danger')
                return render_template('reservations/create.html', form=form, classrooms=classrooms)

            teacher_id = form.teacher.data if form.teacher.data > 0 else None
            is_teacher_conflict = False
            if teacher_id:
                is_teacher_conflict = check_teacher_conflict(
                    teacher_id, form.date.data, form.start_time.data, form.end_time.data
                ) is not None

            status = 'pending' if is_teacher_conflict else 'approved'

            reservation = Reservation(
                user_id=current_user.id, classroom_id=classroom_id,
                course_id=form.course.data if form.course.data > 0 else None,
                subject_id=form.subject.data if form.subject.data > 0 else None,
                teacher_id=teacher_id, title=form.title.data,
                description=form.description.data, date=form.date.data,
                start_time=form.start_time.data, end_time=form.end_time.data,
                status=status,
                unity_id=classroom.unity_id
            )
            db.session.add(reservation)
            db.session.commit()

        if is_teacher_conflict:
            flash('Reserva criada como PENDENTE devido a conflito de professor.', 'warning')
            return redirect(url_for('reservations.teacher_conflict_warning', reservation_id=reservation.id))

        flash('Reserva agendada com sucesso!', 'success')
        return redirect(url_for('reservations.my_reservations'))

    return render_template('reservations/create.html', form=form, classrooms=classrooms)

# Route to view user's own reservations
@bp.route('/my')
@login_required
@require_permission('reservation:read_own')
def my_reservations():
    status = request.args.get('status', 'all')
    query = Reservation.query.filter_by(user_id=current_user.id)
    if status != 'all':
        query = query.filter_by(status=status)

    pagination = db.paginate(query.order_by(Reservation.date.desc(), Reservation.start_time),
                             page=request.args.get('page', 1, type=int),
                             per_page=RESERVATIONS_PER_PAGE, error_out=False)

    today = date.today()
    upcoming_reservations = [r for r in pagination.items if r.date >= today]
    past_reservations = [r for r in pagination.items if r.date < today]

    return render_template('reservations/my_reservations.html', pagination=pagination,
                           upcoming_reservations=upcoming_reservations, past_reservations=past_reservations, current_status=status)

# Admin route to view all reservations
@bp.route('/all')
@login_required
@require_permission('reservation:read_all')
def all_reservations():
    status = request.args.get('status', 'all')
    query = Reservation.query.filter_by(unity_id=current_unity_id())
    if status != 'all':
        query = query.filter_by(status=status)

    pagination = db.paginate(query.order_by(Reservation.date.desc(), Reservation.start_time),
                             page=request.args.get('page', 1, type=int),
                             per_page=RESERVATIONS_PER_PAGE, error_out=False)

    today = date.today()
    upcoming_reservations = [r for r in pagination.items if r.date >= today]
    past_reservations = [r for r in pagination.items if r.date < today]

    return render_template('reservations/all.html', pagination=pagination,
                           upcoming_reservations=upcoming_reservations, past_reservations=past_reservations, current_status=status)

# Route to view details of a specific reservation
@bp.route('/<int:reservation_id>')
@login_required
def detail(reservation_id):
    reservation = _get_reservation_scoped(reservation_id)
    # Permite ver se tem permissão global, OU se é o dono e tem permissão de ler as próprias
    if not current_user.has_permission('reservation:read_all'):
        if not (current_user.has_permission('reservation:read_own') and reservation.user_id == current_user.id):
            abort(403)
    series_count = _series_count(reservation)
    return render_template('reservations/detail.html', reservation=reservation,
                           series_count=series_count)

# Route to edit a reservation (Admin or Owner)
@bp.route('/<int:reservation_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission_or_owner('reservation:edit_all')
def edit(reservation_id):
    reservation = _get_reservation_scoped(reservation_id)
    if reservation.date < date.today():
        flash('Reservas passadas não podem ser editadas.', 'warning')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))

    form = ReservationForm()

    classrooms = _classrooms_for_current_unity()
    form.classroom.choices = [(c.id, f"{c.name} ({c.code}) - Cap {c.capacity}") for c in classrooms]
    form.course.choices = [(0, '-- Nenhum --')] + [(c.id, c.name) for c in _courses_for_current_unity()]
    form.subject.choices = [(0, '-- Nenhum --')] + [(s.id, f"{s.name}") for s in _subjects_for_current_unity()]
    teachers = _teachers_for_current_unity()
    form.teacher.choices = [(0, '-- Selecionar Professor --')] + [(t.id, f"{t.full_name} ({t.department or t.sector or 'N/A'})") for t in teachers]

    if request.method == 'GET':
        form.classroom.data = reservation.classroom_id
        form.course.data = reservation.course_id if reservation.course_id else 0
        form.subject.data = reservation.subject_id if reservation.subject_id else 0
        form.teacher.data = reservation.teacher_id if reservation.teacher_id else 0
        form.title.data = reservation.title
        form.description.data = reservation.description
        form.date.data = reservation.date
        form.start_time.data = reservation.start_time
        form.end_time.data = reservation.end_time

    if form.validate_on_submit():
        classroom_id = form.classroom.data
        # Multi-unidade: a sala precisa pertencer à unidade ativa
        classroom = db.session.get(Classroom, classroom_id)
        if not classroom or classroom.unity_id != current_unity_id():
            flash('Sala inválida para a unidade ativa.', 'danger')
            return render_template('reservations/edit.html', form=form, reservation=reservation)

        # Mesma seção crítica da criação: revalida restrições e conflitos já
        # enxergando o estado consolidado (edit + approve concorrentes).
        with slot_locks(classroom_id, [form.date.data]):
            allowed, restriction_msg = check_schedule_restrictions(
                form.date.data, form.start_time.data, form.end_time.data)
            if not allowed:
                flash(restriction_msg, 'danger')
                return render_template('reservations/edit.html', form=form, reservation=reservation)

            conflict = check_conflict(classroom_id, form.date.data, form.start_time.data,
                                      form.end_time.data, exclude_id=reservation.id)
            if conflict:
                flash(f'Conflito de sala com "{conflict.title}"', 'danger')
                return render_template('reservations/edit.html', form=form, reservation=reservation)

            reservation.classroom_id = classroom_id
            reservation.unity_id = classroom.unity_id
            reservation.course_id = form.course.data if form.course.data > 0 else None
            reservation.subject_id = form.subject.data if form.subject.data > 0 else None
            reservation.teacher_id = form.teacher.data if form.teacher.data > 0 else None
            reservation.title = form.title.data
            reservation.description = form.description.data
            reservation.date = form.date.data
            reservation.start_time = form.start_time.data
            reservation.end_time = form.end_time.data

            # Recheck de docente na edição (a criação já fazia; a edição não):
            # mudar data/horário/professor pode criar sobreposição — a reserva
            # volta a PENDENTE, mesmo critério da criação.
            teacher_conflict = False
            if reservation.teacher_id:
                teacher_conflict = check_teacher_conflict(
                    reservation.teacher_id, reservation.date, reservation.start_time,
                    reservation.end_time, exclude_id=reservation.id) is not None
            if teacher_conflict and reservation.status == 'approved':
                reservation.status = 'pending'

            db.session.commit()

        if teacher_conflict and reservation.status == 'pending':
            flash('Reserva atualizada como PENDENTE devido a conflito de professor.', 'warning')
        else:
            flash('Reserva atualizada com sucesso.', 'success')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))

    return render_template('reservations/edit.html', form=form, reservation=reservation)

# Route to cancel a reservation
@bp.route('/<int:reservation_id>/cancel', methods=['POST'])
@login_required
@require_permission_or_owner('reservation:cancel_all')
def cancel(reservation_id):
    reservation = _get_reservation_scoped(reservation_id)
    if reservation.status == 'cancelled':
        flash('Esta reserva já está cancelada.', 'warning')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))
    if reservation.date < date.today() and not current_user.has_permission('reservation:cancel_all'):
        flash('Não é possível cancelar uma reserva passada.', 'warning')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))
    
    reservation.status = 'cancelled'
    db.session.commit()
    flash('Reserva cancelada.', 'info')
    if current_user.has_permission('reservation:read_all'):
        return redirect(url_for('reservations.all_reservations'))
    return redirect(url_for('reservations.my_reservations'))

# Route to permanently delete a reservation (Admin only)
@bp.route('/<int:reservation_id>/delete', methods=['POST'])
@login_required
@require_permission('reservation:delete_all')
def delete(reservation_id):
    reservation = _get_reservation_scoped(reservation_id)
    db.session.delete(reservation)
    db.session.commit()
    flash('Reserva excluída permanentemente.', 'info')
    return redirect(url_for('reservations.all_reservations'))

# Route to approve a pending reservation (Admin only)
@bp.route('/<int:reservation_id>/approve', methods=['POST'])
@login_required
@require_permission('reservation:approve')
def approve(reservation_id):
    reservation = _get_reservation_scoped(reservation_id)
    if reservation.status == 'pending':
        # Aprovar revalida o conflito de sala dentro da seção crítica:
        # enquanto a reserva estava pendente outra pode ter sido aprovada
        # sobre a mesma janela (ou estar sendo aprovada em paralelo).
        with slot_locks(reservation.classroom_id, [reservation.date]):
            conflict = check_conflict(
                reservation.classroom_id, reservation.date,
                reservation.start_time, reservation.end_time,
                exclude_id=reservation.id)
            if conflict:
                flash(f'Não é possível aprovar: a sala já possui a reserva aprovada '
                      f'"{conflict.title}" ({conflict.start_time.strftime("%H:%M")} - '
                      f'{conflict.end_time.strftime("%H:%M")}) nesta janela. '
                      f'A reserva permanece PENDENTE.', 'danger')
                return redirect(url_for('reservations.detail', reservation_id=reservation.id))
            reservation.status = 'approved'
            # Auditoria: registra quem aprovou (coluna antes nunca preenchida)
            reservation.reviewed_by = current_user.id
            db.session.commit()
        flash('Reserva aprovada.', 'success')
    return redirect(url_for('reservations.detail', reservation_id=reservation.id))

# Warning page for pending teacher conflicts
@bp.route('/<int:reservation_id>/pending-teacher-conflict')
@login_required
def teacher_conflict_warning(reservation_id):
    reservation = _get_reservation_scoped(reservation_id)
    if reservation.user_id != current_user.id and not current_user.has_permission('reservation:read_all'):
        abort(403)
    return render_template('reservations/pending_conflict.html', reservation=reservation)

# ================= REPEAT RESERVATION FEATURE =================

@bp.route('/<int:reservation_id>/repeat', methods=['GET', 'POST'])
@login_required
@require_permission('reservation:create')
def repeat_view(reservation_id):
    res = _get_reservation_scoped(reservation_id)
    if res.user_id != current_user.id and not current_user.has_permission('reservation:edit_all'):
        abort(403)

    start_date = max(res.date + timedelta(days=1), date.today() + timedelta(days=1))
    original_weekday = res.date.weekday()

    dias_semana_extenso = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
    dias_semana_curto = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
    meses_curto = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']
    
    res_weekday_str = dias_semana_extenso[original_weekday]

    end_date_str = request.form.get('end_date') or request.args.get('end_date')
    same_day = request.form.get('same_day') == 'true' or request.args.get('same_day') == 'true'
    skip_weekend = request.form.get('skip_weekend') == 'true' or request.args.get('skip_weekend') == 'true'

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Data final inválida.', 'danger')
            return redirect(url_for('reservations.repeat_view', reservation_id=res.id))

        if end_date < start_date:
            flash('A data final deve ser após a data inicial.', 'danger')
            return redirect(url_for('reservations.repeat_view', reservation_id=res.id))

        if (end_date - start_date).days + 1 > MAX_REPEAT_RANGE_DAYS:
            flash(f'O intervalo da repetição é limitado a {MAX_REPEAT_RANGE_DAYS} dias. '
                  'Crie repetições menores dentro desse limite.', 'warning')
            return redirect(url_for('reservations.repeat_view', reservation_id=res.id))

        # Ocupação do intervalo pré-carregada em 3 consultas (sala, docente e
        # feriados) — em vez de 3 queries por dia do intervalo.
        room_dates, teacher_dates, holiday_names = _load_range_occupancy(
            res.classroom_id, res.teacher_id, start_date, end_date,
            current_unity_id(), res.start_time, res.end_time)

        delta = end_date - start_date
        days = []
        for i in range(delta.days + 1):
            d = start_date + timedelta(days=i)

            if same_day and d.weekday() != original_weekday: continue
            if skip_weekend:
                if d.weekday() == 6: continue
                if d.weekday() == 5 and original_weekday != 5: continue

            # Mesmas regras de check_schedule_restrictions, com os feriados já
            # pré-carregados (o horário é fixo no lote).
            if d.weekday() == 6:
                allowed, msg = False, "Reservas não podem ser agendadas aos domingos."
            elif d in holiday_names:
                allowed, msg = False, f"Reservas não podem ser agendadas em feriados ({holiday_names[d]})."
            elif d.weekday() == 5 and (res.start_time >= time(18, 0) or res.end_time > time(18, 0)):
                allowed, msg = False, "Aos sábados, as reservas são permitidas apenas pela manhã e tarde (até 18:00)."
            else:
                allowed, msg = True, ""

            conflict = d in room_dates
            teacher_conflict = d in teacher_dates

            is_available = allowed and not conflict and not teacher_conflict
            formatted_card_date = f"{dias_semana_curto[d.weekday()]}, {d.day} {meses_curto[d.month - 1]}"
            days.append({
                'date': d, 'formatted_date': formatted_card_date, 'is_available': is_available,
                'message': msg if not allowed else ("Sala Ocupada" if conflict else "Professor Ocupado" if teacher_conflict else "Disponível")
            })

        return render_template('reservations/repeat.html', res=res, start_date=start_date, end_date=end_date, days=days, same_day=same_day, skip_weekend=skip_weekend, res_weekday_str=res_weekday_str, series_count=_series_count(res))

    return render_template('reservations/repeat.html', res=res, start_date=start_date, days=None, same_day=None, skip_weekend=None, res_weekday_str=res_weekday_str, series_count=_series_count(res))

@bp.route('/<int:reservation_id>/repeat_schedule', methods=['POST'])
@login_required
@require_permission('reservation:create')
def repeat_schedule(reservation_id):
    res = _get_reservation_scoped(reservation_id)
    if res.user_id != current_user.id and not current_user.has_permission('reservation:edit_all'):
        abort(403)

    new_date_str = request.form.get('new_date')
    end_date_str = request.form.get('end_date')
    same_day = request.form.get('same_day') == 'true'
    skip_weekend = request.form.get('skip_weekend') == 'true'
    
    try:
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Data inválida.', 'danger')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

    with slot_locks(res.classroom_id, [new_date]):
        allowed, msg = check_schedule_restrictions(new_date, res.start_time, res.end_time)
        if not allowed:
            flash(msg, 'danger')
            return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

        conflict = check_conflict(res.classroom_id, new_date, res.start_time, res.end_time)
        if conflict:
            flash(f'Conflito de sala em {new_date}.', 'danger')
            return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

        # Série de repetição: origem e geradas compartilham o mesmo grupo
        if res.repeat_group_id is None:
            res.repeat_group_id = res.id
        new_res = Reservation(
            user_id=current_user.id, classroom_id=res.classroom_id, course_id=res.course_id,
            subject_id=res.subject_id, teacher_id=res.teacher_id, title=res.title,
            description=res.description, date=new_date, start_time=res.start_time,
            end_time=res.end_time, status='approved', unity_id=res.unity_id,
            repeat_group_id=res.repeat_group_id
        )
        db.session.add(new_res)
        db.session.commit()
    flash(f'Reserva agendada com sucesso para {new_date}.', 'success')
    return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

@bp.route('/<int:reservation_id>/repeat_schedule_all', methods=['POST'])
@login_required
@require_permission('reservation:create')
def repeat_schedule_all(reservation_id):
    res = _get_reservation_scoped(reservation_id)
    if res.user_id != current_user.id and not current_user.has_permission('reservation:edit_all'):
        abort(403)

    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    same_day = request.form.get('same_day') == 'true'
    skip_weekend = request.form.get('skip_weekend') == 'true'
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Datas inválidas.', 'danger')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

    if (end_date - start_date).days + 1 > MAX_REPEAT_RANGE_DAYS:
        flash(f'O intervalo da repetição é limitado a {MAX_REPEAT_RANGE_DAYS} dias. '
              'Crie repetições menores dentro desse limite.', 'warning')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

    scheduled_count = 0
    current_date = start_date
    original_weekday = res.date.weekday()

    # Seção crítica de todo o intervalo: as checagens das N datas enxergam o
    # estado consolidado e nenhuma reserva concorrente grava no meio do lote.
    range_dates = []
    d = start_date
    while d <= end_date:
        range_dates.append(d)
        d += timedelta(days=1)

    with slot_locks(res.classroom_id, range_dates):
        while current_date <= end_date:
            if same_day and current_date.weekday() != original_weekday:
                current_date += timedelta(days=1)
                continue
            if skip_weekend:
                if current_date.weekday() == 6:
                    current_date += timedelta(days=1)
                    continue
                if current_date.weekday() == 5 and original_weekday != 5:
                    current_date += timedelta(days=1)
                    continue

            allowed, _ = check_schedule_restrictions(current_date, res.start_time, res.end_time)
            if allowed:
                conflict = check_conflict(res.classroom_id, current_date, res.start_time, res.end_time)
                if not conflict:
                    teacher_conflict = False
                    if res.teacher_id:
                        teacher_conflict = check_teacher_conflict(
                            res.teacher_id, current_date, res.start_time, res.end_time) is not None
                    if not teacher_conflict:
                        # Série de repetição: origem e geradas no mesmo grupo
                        if res.repeat_group_id is None:
                            res.repeat_group_id = res.id
                        new_res = Reservation(
                            user_id=current_user.id, classroom_id=res.classroom_id, course_id=res.course_id,
                            subject_id=res.subject_id, teacher_id=res.teacher_id, title=res.title,
                            description=res.description, date=current_date, start_time=res.start_time,
                            end_time=res.end_time, status='approved', unity_id=res.unity_id,
                            repeat_group_id=res.repeat_group_id
                        )
                        db.session.add(new_res)
                        scheduled_count += 1
            current_date += timedelta(days=1)

        db.session.commit()
    flash(f'{scheduled_count} novas reservas agendadas com sucesso.', 'success')
    return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

# ================= SERIES MANAGEMENT (agendamentos repetidos) =================

def _series_members(res):
    """Reservas da série de repetição (origem + geradas pela tela Repetir).

    A origem recebe repeat_group_id = próprio id no momento em que a primeira
    repetição é criada; toda reserva gerada carrega o mesmo grupo.
    """
    group_id = res.repeat_group_id or res.id
    members = Reservation.query.filter(
        Reservation.repeat_group_id == group_id
    ).order_by(Reservation.date, Reservation.start_time).all()
    return group_id, members


def _series_count(res):
    group_id = res.repeat_group_id or res.id
    return db.session.query(Reservation.id).filter(
        Reservation.repeat_group_id == group_id).count()


def _check_series_view_access(res):
    """Ver a série: dono da reserva ou quem lê todas."""
    if res.user_id != current_user.id and not current_user.has_permission('reservation:read_all'):
        abort(403)


@bp.route('/<int:reservation_id>/series')
@login_required
def series_manage(reservation_id):
    res = _get_reservation_scoped(reservation_id)
    _check_series_view_access(res)

    _, members = _series_members(res)
    if len(members) < 2:
        flash('Esta reserva não possui repetições geradas.', 'info')
        return redirect(url_for('reservations.detail', reservation_id=res.id))

    today = date.today()
    upcoming = [m for m in members if m.date >= today and m.status != 'cancelled']
    upcoming_ids = {m.id for m in upcoming}
    finished = [m for m in members if m.id not in upcoming_ids]

    return render_template('reservations/series.html', res=res,
                           upcoming=upcoming, finished=finished,
                           classrooms=_classrooms_for_current_unity(),
                           can_edit=(res.user_id == current_user.id
                                     or current_user.has_permission('reservation:edit_all')),
                           can_cancel=(current_user.has_permission('reservation:cancel_all')
                                       or (current_user.has_permission('reservation:cancel_own')
                                           and res.user_id == current_user.id)),
                           can_delete=current_user.has_permission('reservation:delete_all'))

@bp.route('/<int:reservation_id>/series/edit', methods=['POST'])
@login_required
def series_edit(reservation_id):
    res = _get_reservation_scoped(reservation_id)
    _check_series_view_access(res)
    if res.user_id != current_user.id and not current_user.has_permission('reservation:edit_all'):
        abort(403)

    selected = _selected_series_members(res)
    today = date.today()
    is_admin = current_user.has_permission('reservation:edit_all')
    targets = [m for m in selected
               if m.date >= today and m.status != 'cancelled'
               and (is_admin or m.user_id == current_user.id)]
    if not targets:
        flash('Selecione ao menos uma reserva futura da série para editar.', 'warning')
        return redirect(url_for('reservations.series_manage', reservation_id=res.id))

    def _parse_time(value):
        """time a partir de 'HH:MM'; None quando vazio; erro se inválido."""
        if not value:
            return None
        try:
            return datetime.strptime(value, '%H:%M').time()
        except ValueError:
            raise ValueError('Horário inválido.')

    try:
        new_start = _parse_time(request.form.get('start_time'))
        new_end = _parse_time(request.form.get('end_time'))
    except ValueError:
        flash('Horário inválido.', 'danger')
        return redirect(url_for('reservations.series_manage', reservation_id=res.id))
    if new_start and new_end and new_end <= new_start:
        flash('O horário de término deve ser após o início.', 'danger')
        return redirect(url_for('reservations.series_manage', reservation_id=res.id))

    # Campos opcionais: vazio = mantém o valor atual de cada reserva
    title = (request.form.get('title') or '').strip() or None
    if title and len(title) > 200:
        flash('O título deve ter no máximo 200 caracteres.', 'danger')
        return redirect(url_for('reservations.series_manage', reservation_id=res.id))
    description = (request.form.get('description') or '').strip() or None

    classroom = None
    classroom_id = request.form.get('classroom_id', type=int)
    if classroom_id:
        classroom = db.session.get(Classroom, classroom_id)
        if not classroom or classroom.unity_id != current_unity_id():
            flash('Sala inválida para a unidade ativa.', 'danger')
            return redirect(url_for('reservations.series_manage', reservation_id=res.id))

    # Agrupa por sala-alvo (a nova, se escolhida; senão a atual de cada uma)
    by_classroom = {}
    for m in targets:
        by_classroom.setdefault(classroom.id if classroom else m.classroom_id, []).append(m)

    updated, skipped = [], []
    with ExitStack() as stack:
        for room_id, room_targets in by_classroom.items():
            stack.enter_context(slot_locks(room_id, [m.date for m in room_targets]))
        for room_targets in by_classroom.values():
            for m in room_targets:
                start = new_start or m.start_time
                end = new_end or m.end_time
                allowed, msg = check_schedule_restrictions(m.date, start, end)
                if not allowed:
                    skipped.append((m, msg))
                    continue
                conflict = check_conflict(m.classroom_id if classroom is None else classroom.id,
                                          m.date, start, end, exclude_id=m.id)
                if conflict:
                    skipped.append((m, f'Sala ocupada por "{conflict.title}"'))
                    continue
                if classroom:
                    m.classroom_id = classroom.id
                    m.unity_id = classroom.unity_id
                m.start_time = start
                m.end_time = end
                if title:
                    m.title = title
                if description:
                    m.description = description
                # Docente sobreposto após a mudança → mesma regra da edição
                # individual: a reserva volta a PENDENTE para revisão.
                if m.teacher_id and check_teacher_conflict(
                        m.teacher_id, m.date, m.start_time, m.end_time,
                        exclude_id=m.id) and m.status == 'approved':
                    m.status = 'pending'
                updated.append(m)
        db.session.commit()

    if updated:
        flash(f'{len(updated)} reservas da série atualizadas.', 'success')
    if skipped:
        datas = ', '.join(m.date.strftime('%d/%m') for m, _ in skipped)
        flash(f'{len(skipped)} reserva(s) não alterada(s) ({datas}).', 'warning')
    if not updated and not skipped:
        flash('Nenhuma alteração a aplicar.', 'info')
    return redirect(url_for('reservations.series_manage', reservation_id=res.id))

@bp.route('/<int:reservation_id>/series/delete', methods=['POST'])
@login_required
def series_delete(reservation_id):
    res = _get_reservation_scoped(reservation_id)
    _check_series_view_access(res)

    mode = request.form.get('mode')
    selected = _selected_series_members(res)
    if not selected:
        flash('Selecione ao menos uma reserva da série.', 'warning')
        return redirect(url_for('reservations.series_manage', reservation_id=res.id))

    today = date.today()

    if mode == 'delete':
        # Exclusão permanente: mesmo critério da exclusão individual (admin)
        if not current_user.has_permission('reservation:delete_all'):
            abort(403)
        for m in selected:
            db.session.delete(m)
        db.session.commit()
        flash(f'{len(selected)} reserva(s) da série excluída(s) permanentemente.', 'success')
        if any(m.id == res.id for m in selected):
            return redirect(url_for('reservations.all_reservations')
                            if current_user.has_permission('reservation:read_all')
                            else url_for('reservations.my_reservations'))
        return redirect(url_for('reservations.series_manage', reservation_id=res.id))

    # Cancelamento (soft) — mesma regra da rota individual de cancelamento
    is_admin_cancel = current_user.has_permission('reservation:cancel_all')
    if not (is_admin_cancel or (current_user.has_permission('reservation:cancel_own')
                                and res.user_id == current_user.id)):
        abort(403)

    cancelled, skipped_past, skipped_other = 0, 0, 0
    for m in selected:
        if m.status == 'cancelled':
            continue
        if m.date < today and not is_admin_cancel:
            skipped_past += 1
            continue
        if not is_admin_cancel and m.user_id != current_user.id:
            skipped_other += 1
            continue
        m.status = 'cancelled'
        cancelled += 1
    db.session.commit()

    flash(f'{cancelled} reserva(s) da série cancelada(s).', 'info')
    if skipped_past:
        flash(f'{skipped_past} reserva(s) passada(s) não cancelada(s) — apenas quem '
              'tem cancelamento global pode cancelar reservas passadas.', 'warning')
    if skipped_other:
        flash(f'{skipped_other} reserva(s) de outro usuário não cancelada(s).', 'warning')
    return redirect(url_for('reservations.series_manage', reservation_id=res.id))


def _selected_series_members(res):
    """Reservas do formulário (ids em 'selected') limitadas à série da reserva.

    O filtro pelo grupo é o que impede que ids arbitrários de reservas fora da
    série sejam editados/excluídos via POST forjado.
    """
    _, members = _series_members(res)
    by_id = {m.id: m for m in members}
    ids = {v for v in request.form.getlist('selected') if str(v).isdigit()}
    return [by_id[int(i)] for i in ids if int(i) in by_id]