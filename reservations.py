from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, jsonify
from flask_login import login_required, current_user
from models import Reservation, Classroom, User, Course, Subject, Holiday
from forms import ReservationForm
from extensions import db
from datetime import date, time, datetime, timedelta
from permissions import require_permission, require_permission_or_owner

bp = Blueprint('reservations', __name__, url_prefix='/reservations')

# Helper function to check if a room is already booked
def check_conflict(classroom_id, reservation_date, start_time, end_time, exclude_id=None):
    query = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date == reservation_date,
        Reservation.status == 'approved',
        Reservation.start_time < end_time,
        Reservation.end_time > start_time
    )
    if exclude_id:
        query = query.filter(Reservation.id != exclude_id)
    return query.first()

# Helper function to check scheduling restrictions (Sundays, Holidays, Saturday nights)
def check_schedule_restrictions(res_date, start_time):
    if isinstance(res_date, str):
        try:
            res_date = datetime.strptime(res_date, '%Y-%m-%d').date()
        except ValueError:
            pass
            
    weekday = res_date.weekday()
    
    # 1. Block Sundays
    if weekday == 6:
        return False, "Reservas não podem ser agendadas aos domingos."
    
    # 2. Block Holidays (Query Database)
    holiday = Holiday.query.filter_by(date=res_date, is_active=True).first()
    if holiday:
        return False, f"Reservas não podem ser agendadas em feriados ({holiday.name})."
    
    # 3. Block Saturday Nights (After 18:00)
    if weekday == 5: 
        if start_time >= time(18, 0):
            return False, "Aos sábados, as reservas são permitidas apenas pela manhã e tarde (até 18:00)."
    
    return True, ""

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

    holiday = Holiday.query.filter_by(date=check_date, is_active=True).first()
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
    
    classrooms = Classroom.query.filter_by(is_active=True).order_by(Classroom.code).all()
    form.classroom.choices = [(c.id, f"{c.name} ({c.code}) - Cap {c.capacity}") for c in classrooms]
    form.course.choices = [(0, '-- Nenhum --')] + [(c.id, c.name) for c in Course.query.filter_by(is_active=True).order_by(Course.name).all()]
    form.subject.choices = [(0, '-- Nenhum --')] + [(s.id, f"{s.name}") for s in Subject.query.filter_by(is_active=True).order_by(Subject.name).all()]
    
    teachers = User.query.filter(
        User.is_active_user == True,
        ((User.profile_type == 'teacher') | (User.is_teacher == True))
    ).order_by(User.full_name).all()
    form.teacher.choices = [(0, '-- Selecionar Professor --')] + [(t.id, f"{t.full_name} ({t.department or t.sector or 'N/A'})") for t in teachers]

    preselect = request.args.get('classroom_id', type=int)
    if request.method == 'GET' and preselect:
        form.classroom.data = preselect

    if form.validate_on_submit():
        if form.date.data < date.today():
            flash('Não é possível reservar uma data no passado.', 'danger')
            return render_template('reservations/create.html', form=form, classrooms=classrooms)

        allowed, restriction_msg = check_schedule_restrictions(form.date.data, form.start_time.data)
        if not allowed:
            flash(restriction_msg, 'danger')
            return render_template('reservations/create.html', form=form, classrooms=classrooms)

        classroom_id = form.classroom.data
        
        conflict = check_conflict(classroom_id, form.date.data, form.start_time.data, form.end_time.data)
        if conflict:
            flash(f'Conflito de sala com "{conflict.title}" ({conflict.start_time.strftime("%H:%M")} - {conflict.end_time.strftime("%H:%M")})', 'danger')
            return render_template('reservations/create.html', form=form, classrooms=classrooms)

        teacher_id = form.teacher.data if form.teacher.data > 0 else None
        is_teacher_conflict = False
        
        if teacher_id:
            teacher_conflict = Reservation.query.filter(
                Reservation.teacher_id == teacher_id,
                Reservation.date == form.date.data,
                Reservation.status.in_(['approved', 'pending']),
                Reservation.start_time < form.end_time.data,
                Reservation.end_time > form.start_time.data
            ).first()
            if teacher_conflict:
                is_teacher_conflict = True

        status = 'pending' if is_teacher_conflict else 'approved'

        reservation = Reservation(
            user_id=current_user.id, classroom_id=classroom_id,
            course_id=form.course.data if form.course.data > 0 else None,
            subject_id=form.subject.data if form.subject.data > 0 else None,
            teacher_id=teacher_id, title=form.title.data,
            description=form.description.data, date=form.date.data,
            start_time=form.start_time.data, end_time=form.end_time.data,
            status=status
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
        
    all_res = query.order_by(Reservation.date.desc(), Reservation.start_time).all()
    
    today = date.today()
    upcoming_reservations = [r for r in all_res if r.date >= today]
    past_reservations = [r for r in all_res if r.date < today]
    
    return render_template('reservations/my_reservations.html', upcoming_reservations=upcoming_reservations, past_reservations=past_reservations, current_status=status)

# Admin route to view all reservations
@bp.route('/all')
@login_required
@require_permission('reservation:read_all')
def all_reservations():
    status = request.args.get('status', 'all')
    query = Reservation.query
    if status != 'all':
        query = query.filter_by(status=status)
        
    all_res = query.order_by(Reservation.date.desc(), Reservation.start_time).all()
    
    today = date.today()
    upcoming_reservations = [r for r in all_res if r.date >= today]
    past_reservations = [r for r in all_res if r.date < today]
    
    return render_template('reservations/all.html', upcoming_reservations=upcoming_reservations, past_reservations=past_reservations, current_status=status)

# Route to view details of a specific reservation
@bp.route('/<int:reservation_id>')
@login_required
def detail(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    # Permite ver se tem permissão global, OU se é o dono e tem permissão de ler as próprias
    if not current_user.has_permission('reservation:read_all'):
        if not (current_user.has_permission('reservation:read_own') and reservation.user_id == current_user.id):
            abort(403)
    return render_template('reservations/detail.html', reservation=reservation)

# Route to edit a reservation (Admin or Owner)
@bp.route('/<int:reservation_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission_or_owner('reservation:edit_all')
def edit(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.date < date.today():
        flash('Reservas passadas não podem ser editadas.', 'warning')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))

    form = ReservationForm()
    
    classrooms = Classroom.query.filter_by(is_active=True).order_by(Classroom.code).all()
    form.classroom.choices = [(c.id, f"{c.name} ({c.code}) - Cap {c.capacity}") for c in classrooms]
    form.course.choices = [(0, '-- Nenhum --')] + [(c.id, c.name) for c in Course.query.filter_by(is_active=True).order_by(Course.name).all()]
    form.subject.choices = [(0, '-- Nenhum --')] + [(s.id, f"{s.name}") for s in Subject.query.filter_by(is_active=True).order_by(Subject.name).all()]
    teachers = User.query.filter(User.is_active_user == True, ((User.profile_type == 'teacher') | (User.is_teacher == True))).order_by(User.full_name).all()
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
        allowed, restriction_msg = check_schedule_restrictions(form.date.data, form.start_time.data)
        if not allowed:
            flash(restriction_msg, 'danger')
            return render_template('reservations/edit.html', form=form, reservation=reservation)

        classroom_id = form.classroom.data
        conflict = check_conflict(classroom_id, form.date.data, form.start_time.data, form.end_time.data, exclude_id=reservation.id)
        if conflict:
            flash(f'Conflito de sala com "{conflict.title}"', 'danger')
            return render_template('reservations/edit.html', form=form, reservation=reservation)

        reservation.classroom_id = classroom_id
        reservation.course_id = form.course.data if form.course.data > 0 else None
        reservation.subject_id = form.subject.data if form.subject.data > 0 else None
        reservation.teacher_id = form.teacher.data if form.teacher.data > 0 else None
        reservation.title = form.title.data
        reservation.description = form.description.data
        reservation.date = form.date.data
        reservation.start_time = form.start_time.data
        reservation.end_time = form.end_time.data
        
        db.session.commit()
        flash('Reserva atualizada com sucesso.', 'success')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))

    return render_template('reservations/edit.html', form=form, reservation=reservation)

# Route to cancel a reservation
@bp.route('/<int:reservation_id>/cancel', methods=['POST'])
@login_required
@require_permission_or_owner('reservation:cancel_all')
def cancel(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
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
    reservation = Reservation.query.get_or_404(reservation_id)
    db.session.delete(reservation)
    db.session.commit()
    flash('Reserva excluída permanentemente.', 'info')
    return redirect(url_for('reservations.all_reservations'))

# Route to approve a pending reservation (Admin only)
@bp.route('/<int:reservation_id>/approve', methods=['POST'])
@login_required
@require_permission('reservation:approve')
def approve(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.status == 'pending':
        reservation.status = 'approved'
        db.session.commit()
        flash('Reserva aprovada.', 'success')
    return redirect(url_for('reservations.detail', reservation_id=reservation.id))

# Warning page for pending teacher conflicts
@bp.route('/<int:reservation_id>/pending-teacher-conflict')
@login_required
def teacher_conflict_warning(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != current_user.id and not current_user.has_permission('reservation:read_all'):
        abort(403)
    return render_template('reservations/pending_conflict.html', reservation=reservation)

# ================= REPEAT RESERVATION FEATURE =================

@bp.route('/<int:reservation_id>/repeat', methods=['GET', 'POST'])
@login_required
@require_permission('reservation:create')
def repeat_view(reservation_id):
    res = Reservation.query.get_or_404(reservation_id)
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

        delta = end_date - start_date
        days = []
        for i in range(delta.days + 1):
            d = start_date + timedelta(days=i)
            
            if same_day and d.weekday() != original_weekday: continue
            if skip_weekend:
                if d.weekday() == 6: continue
                if d.weekday() == 5 and original_weekday != 5: continue
            
            allowed, msg = check_schedule_restrictions(d, res.start_time)
            conflict = check_conflict(res.classroom_id, d, res.start_time, res.end_time)
            teacher_conflict = False
            if res.teacher_id:
                tc = Reservation.query.filter(
                    Reservation.teacher_id == res.teacher_id, Reservation.date == d,
                    Reservation.status.in_(['approved', 'pending']),
                    Reservation.start_time < res.end_time, Reservation.end_time > res.start_time
                ).first()
                if tc: teacher_conflict = True

            is_available = allowed and not conflict and not teacher_conflict
            formatted_card_date = f"{dias_semana_curto[d.weekday()]}, {d.day} {meses_curto[d.month - 1]}"
            days.append({
                'date': d, 'formatted_date': formatted_card_date, 'is_available': is_available,
                'message': msg if not allowed else ("Sala Ocupada" if conflict else "Professor Ocupado" if teacher_conflict else "Disponível")
            })

        return render_template('reservations/repeat.html', res=res, start_date=start_date, end_date=end_date, days=days, same_day=same_day, skip_weekend=skip_weekend, res_weekday_str=res_weekday_str)

    return render_template('reservations/repeat.html', res=res, start_date=start_date, days=None, same_day=None, skip_weekend=None, res_weekday_str=res_weekday_str)

@bp.route('/<int:reservation_id>/repeat_schedule', methods=['POST'])
@login_required
@require_permission('reservation:create')
def repeat_schedule(reservation_id):
    res = Reservation.query.get_or_404(reservation_id)
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

    allowed, msg = check_schedule_restrictions(new_date, res.start_time)
    if not allowed:
        flash(msg, 'danger')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

    conflict = check_conflict(res.classroom_id, new_date, res.start_time, res.end_time)
    if conflict:
        flash(f'Conflito de sala em {new_date}.', 'danger')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

    new_res = Reservation(
        user_id=current_user.id, classroom_id=res.classroom_id, course_id=res.course_id,
        subject_id=res.subject_id, teacher_id=res.teacher_id, title=res.title,
        description=res.description, date=new_date, start_time=res.start_time,
        end_time=res.end_time, status='approved'
    )
    db.session.add(new_res)
    db.session.commit()
    flash(f'Reserva agendada com sucesso para {new_date}.', 'success')
    return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))

@bp.route('/<int:reservation_id>/repeat_schedule_all', methods=['POST'])
@login_required
@require_permission('reservation:create')
def repeat_schedule_all(reservation_id):
    res = Reservation.query.get_or_404(reservation_id)
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

    scheduled_count = 0
    current_date = start_date
    original_weekday = res.date.weekday()
    
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
        
        allowed, _ = check_schedule_restrictions(current_date, res.start_time)
        if allowed:
            conflict = check_conflict(res.classroom_id, current_date, res.start_time, res.end_time)
            if not conflict:
                teacher_conflict = False
                if res.teacher_id:
                    tc = Reservation.query.filter(
                        Reservation.teacher_id == res.teacher_id, Reservation.date == current_date,
                        Reservation.status.in_(['approved', 'pending']),
                        Reservation.start_time < res.end_time, Reservation.end_time > res.start_time
                    ).first()
                    if tc: teacher_conflict = True
                if not teacher_conflict:
                    new_res = Reservation(
                        user_id=current_user.id, classroom_id=res.classroom_id, course_id=res.course_id,
                        subject_id=res.subject_id, teacher_id=res.teacher_id, title=res.title,
                        description=res.description, date=current_date, start_time=res.start_time,
                        end_time=res.end_time, status='approved'
                    )
                    db.session.add(new_res)
                    scheduled_count += 1
        current_date += timedelta(days=1)
        
    db.session.commit()
    flash(f'{scheduled_count} novas reservas agendadas com sucesso.', 'success')
    return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str, same_day=same_day, skip_weekend=skip_weekend))