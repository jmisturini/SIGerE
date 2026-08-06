from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, jsonify
from flask_login import login_required, current_user
from models import Reservation, Classroom, User, Course, Subject, Holiday
from forms import ReservationForm
from extensions import db
from datetime import date, time, datetime, timedelta

bp = Blueprint('reservations', __name__, url_prefix='/reservations')


def check_conflict(classroom_id, reservation_date, start_time, end_time, exclude_id=None):
    """Return a conflicting reservation, if any."""
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

def check_schedule_restrictions(res_date, start_time):
    """Check if the date is a Sunday, Holiday, or Saturday night."""
    
    # Ensure res_date is a date object
    if isinstance(res_date, str):
        try:
            res_date = datetime.strptime(res_date, '%Y-%m-%d').date()
        except ValueError:
            pass # Let it fail if it's completely invalid
            
    weekday = res_date.weekday()
    
    # 1. Block Sundays
    if weekday == 6:
        return False, "Reservations cannot be scheduled on Sundays."
    
    # 2. Block Holidays (Query Database)
    # We use .first() to check if any active holiday matches this exact date
    holiday = Holiday.query.filter_by(date=res_date, is_active=True).first()
    if holiday:
        return False, f"Reservations cannot be scheduled on Holidays ({holiday.name})."
    
    # 3. Block Saturday Nights (After 18:00)
    if weekday == 5: # Saturday
        if start_time >= time(18, 0):
            return False, "On Saturdays, reservations are only allowed in the Morning and Afternoon (until 18:00)."
    
    return True, ""


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.can_book:
        flash('Viewers can only request changes. Please contact a Room Booker or Admin.', 'warning')
        return redirect(url_for('classrooms.list_classrooms'))

    form = ReservationForm()
    
    classrooms = Classroom.query.filter_by(is_active=True).order_by(Classroom.code).all()
    form.classroom.choices = [
        (c.id, f"{c.name} ({c.code}) - Cap {c.capacity}")
        for c in classrooms
    ]
    form.course.choices = [(0, '-- None --')] + [(c.id, c.name) for c in Course.query.filter_by(is_active=True).order_by(Course.name).all()]
    form.subject.choices = [(0, '-- None --')] + [(s.id, f"{s.name} ({s.course.name if s.course else 'General'})") for s in Subject.query.filter_by(is_active=True).order_by(Subject.name).all()]
    
    teachers = User.query.filter(
        User.is_active_user == True,
        ((User.profile_type == 'teacher') | (User.is_teacher == True))
    ).order_by(User.full_name).all()
    form.teacher.choices = [(0, '-- Select Teacher --')] + [(t.id, f"{t.full_name} ({t.department or t.sector or 'N/A'})") for t in teachers]

    preselect = request.args.get('classroom_id', type=int)
    if request.method == 'GET' and preselect:
        form.classroom.data = preselect

    if form.validate_on_submit():
        if form.date.data < date.today():
            flash('Cannot reserve a date in the past.', 'danger')
            return render_template('reservations/create.html', form=form, classrooms=classrooms)

        # Check Sunday/Holiday/Saturday Night restrictions
        allowed, restriction_msg = check_schedule_restrictions(form.date.data, form.start_time.data)
        if not allowed:
            flash(restriction_msg, 'danger')
            return render_template('reservations/create.html', form=form, classrooms=classrooms)

        classroom_id = form.classroom.data
        
        # 1. Check Classroom conflict (Hard block)
        conflict = check_conflict(
            classroom_id, form.date.data,
            form.start_time.data, form.end_time.data
        )
        if conflict:
            flash(
                f'Classroom conflict with "{conflict.title}" '
                f'({conflict.start_time.strftime("%H:%M")} - '
                f'{conflict.end_time.strftime("%H:%M")})', 'danger'
            )
            return render_template('reservations/create.html', form=form, classrooms=classrooms)

        # 2. Check Teacher conflict (Triggers pending status)
        teacher_id = form.teacher.data if form.teacher.data > 0 else None
        is_teacher_conflict = False
        
        if teacher_id:
            teacher_conflict = Reservation.query.filter(
                Reservation.teacher_id == teacher_id,
                Reservation.date == form.date.data,
                Reservation.status.in_(['approved', 'pending']), # Check both approved and pending
                Reservation.start_time < form.end_time.data,
                Reservation.end_time > form.start_time.data
            ).first()
            
            if teacher_conflict:
                is_teacher_conflict = True

        # Determine status based on conflict
        status = 'pending' if is_teacher_conflict else 'approved'

        reservation = Reservation(
            user_id=current_user.id,
            classroom_id=classroom_id,
            course_id=form.course.data if form.course.data > 0 else None,
            subject_id=form.subject.data if form.subject.data > 0 else None,
            teacher_id=teacher_id,
            title=form.title.data,
            description=form.description.data,
            date=form.date.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
            status=status
        )
        db.session.add(reservation)
        db.session.commit()
        
        # Redirect to warning page if pending, else go to my reservations
        if is_teacher_conflict:
            flash('Reservation created as PENDING due to teacher conflict.', 'warning')
            return redirect(url_for('reservations.teacher_conflict_warning', reservation_id=reservation.id))
        
        flash('Reservation successfully booked!', 'success')
        return redirect(url_for('reservations.my_reservations'))

    return render_template('reservations/create.html', form=form, classrooms=classrooms)

@bp.route('/my')
@login_required
def my_reservations():
    status = request.args.get('status', 'all')
    query = Reservation.query.filter_by(user_id=current_user.id)
    if status != 'all':
        query = query.filter_by(status=status)
        
    all_res = query.order_by(Reservation.date.desc(), Reservation.start_time).all()
    
    today = date.today()
    # Split into upcoming/current and past
    upcoming_reservations = [r for r in all_res if r.date >= today]
    past_reservations = [r for r in all_res if r.date < today]
    
    return render_template(
        'reservations/my_reservations.html',
        upcoming_reservations=upcoming_reservations,
        past_reservations=past_reservations,
        current_status=status
    )

# NEW: Admin view to see all reservations
@bp.route('/all')
@login_required
def all_reservations():
    if not current_user.is_admin:
        abort(403)
        
    status = request.args.get('status', 'all')
    query = Reservation.query
    if status != 'all':
        query = query.filter_by(status=status)
        
    all_res = query.order_by(Reservation.date.desc(), Reservation.start_time).all()
    
    today = date.today()
    upcoming_reservations = [r for r in all_res if r.date >= today]
    past_reservations = [r for r in all_res if r.date < today]
    
    return render_template('reservations/all.html', 
                           upcoming_reservations=upcoming_reservations, 
                           past_reservations=past_reservations,
                           current_status=status)


@bp.route('/<int:reservation_id>')
@login_required
def detail(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template('reservations/detail.html', reservation=reservation)


# NEW: Admin edit route
@bp.route('/<int:reservation_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(reservation_id):
    if not current_user.is_admin:
        abort(403)
    
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.date < date.today():
        flash('Past reservations cannot be edited.', 'warning')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))
    form = ReservationForm(obj=reservation)
    
    classrooms = Classroom.query.filter_by(is_active=True).order_by(Classroom.code).all()
    form.classroom.choices = [
        (c.id, f"{c.code} - {c.name} ({c.building or 'N/A'}, cap {c.capacity})")
        for c in classrooms
    ]
    
    form.course.choices = [(0, '-- None --')] + [(c.id, c.name) for c in Course.query.filter_by(is_active=True).order_by(Course.name).all()]
    form.subject.choices = [(0, '-- None --')] + [(s.id, f"{s.name} ({s.course.name if s.course else 'General'})") for s in Subject.query.filter_by(is_active=True).order_by(Subject.name).all()]
    
    # NEW: Populate Teacher choices (Teachers OR Employees who are also teachers)
    teachers = User.query.filter(
        User.is_active_user == True,
        ((User.profile_type == 'teacher') | (User.is_teacher == True))
    ).order_by(User.full_name).all()
    form.teacher.choices = [(0, '-- Select Teacher --')] + [(t.id, f"{t.full_name} ({t.department or t.sector or 'N/A'})") for t in teachers]

    if form.validate_on_submit():
        # NEW: Check Sunday/Holiday/Saturday Night restrictions
        allowed, restriction_msg = check_schedule_restrictions(form.date.data, form.start_time.data)
        if not allowed:
            flash(restriction_msg, 'danger')
            return render_template('reservations/edit.html', form=form, reservation=reservation)
        
        classroom_id = form.classroom.data
        conflict = check_conflict(
            classroom_id, form.date.data,
            form.start_time.data, form.end_time.data,
            exclude_id=reservation.id
        )
        if conflict:
            flash(
                f'Classroom conflict with "{conflict.title}" '
                f'({conflict.start_time.strftime("%H:%M")} - '
                f'{conflict.end_time.strftime("%H:%M")})', 'danger'
            )
            return render_template('reservations/edit.html', form=form, reservation=reservation)

        # Check Teacher conflict (exclude current reservation)
        teacher_id = form.teacher.data if form.teacher.data > 0 else None
        if teacher_id:
            teacher_conflict = Reservation.query.filter(
                Reservation.teacher_id == teacher_id,
                Reservation.date == form.date.data,
                Reservation.status == 'approved',
                Reservation.id != reservation.id,
                Reservation.start_time < form.end_time.data,
                Reservation.end_time > form.start_time.data
            ).first()
            
            if teacher_conflict and not form.acknowledge_teacher_conflict.data:
                flash(
                    f'Warning: {teacher_conflict.teacher.full_name} is already booked from '
                    f'{teacher_conflict.start_time.strftime("%H:%M")} to {teacher_conflict.end_time.strftime("%H:%M")}. '
                    f'You must check the acknowledgment box to proceed.', 'danger'
                )
                return render_template('reservations/edit.html', form=form, reservation=reservation)

        reservation.classroom_id = classroom_id
        reservation.course_id = form.course.data if form.course.data > 0 else None
        reservation.subject_id = form.subject.data if form.subject.data > 0 else None
        reservation.teacher_id = teacher_id # NEW
        reservation.title = form.title.data
        reservation.description = form.description.data
        reservation.date = form.date.data
        reservation.start_time = form.start_time.data
        reservation.end_time = form.end_time.data
        
        db.session.commit()
        flash('Reservation updated successfully.', 'success')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))

    return render_template('reservations/edit.html', form=form, reservation=reservation)


@bp.route('/<int:reservation_id>/cancel', methods=['POST'])
@login_required
def cancel(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if reservation.status == 'cancelled':
        flash('This reservation is already cancelled.', 'warning')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))
    if reservation.date < date.today() and not current_user.is_admin:
        flash('Cannot cancel a past reservation.', 'warning')
        return redirect(url_for('reservations.detail', reservation_id=reservation.id))
    
    reservation.status = 'cancelled'
    db.session.commit()
    flash('Reservation cancelled.', 'info')
    
    # Redirect admins back to all reservations, users back to theirs
    if current_user.is_admin:
        return redirect(url_for('reservations.all_reservations'))
    return redirect(url_for('reservations.my_reservations'))


# NEW: Admin hard-delete route
@bp.route('/<int:reservation_id>/delete', methods=['POST'])
@login_required
def delete(reservation_id):
    if not current_user.is_admin:
        abort(403)
    
    reservation = Reservation.query.get_or_404(reservation_id)
    db.session.delete(reservation)
    db.session.commit()
    flash('Reservation permanently deleted.', 'info')
    return redirect(url_for('reservations.all_reservations'))
# NEW: Warning page for pending teacher conflicts
@bp.route('/<int:reservation_id>/pending-teacher-conflict')
@login_required
def teacher_conflict_warning(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    return render_template('reservations/pending_conflict.html', reservation=reservation)

# NEW: Admin approval route for pending reservations
@bp.route('/<int:reservation_id>/approve', methods=['POST'])
@login_required
def approve(reservation_id):
    if not current_user.is_admin:
        abort(403)
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.status == 'pending':
        reservation.status = 'approved'
        db.session.commit()
        flash('Reservation has been approved.', 'success')
    return redirect(url_for('reservations.detail', reservation_id=reservation.id))

# ================= REPEAT RESERVATION FEATURE =================

@bp.route('/<int:reservation_id>/repeat', methods=['GET', 'POST'])
@login_required
def repeat_view(reservation_id):
    res = Reservation.query.get_or_404(reservation_id)
    if res.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    # Determine start date (tomorrow or original date if it's in the future)
    start_date = max(res.date + timedelta(days=1), date.today() + timedelta(days=1))

    # Allow receiving end_date from POST form OR GET URL parameters (for redirects)
    end_date_str = request.form.get('end_date') or request.args.get('end_date')

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid end date.', 'danger')
            return redirect(url_for('reservations.repeat_view', reservation_id=res.id))

        if end_date < start_date:
            flash('End date must be after the start date.', 'danger')
            return redirect(url_for('reservations.repeat_view', reservation_id=res.id))

        # Generate list of days
        delta = end_date - start_date
        days = []
        for i in range(delta.days + 1):
            d = start_date + timedelta(days=i)
            
            # Check restrictions (Sunday/Holiday/Saturday)
            allowed, msg = check_schedule_restrictions(d, res.start_time)
            
            # Check room conflict
            conflict = check_conflict(res.classroom_id, d, res.start_time, res.end_time)
            
            # Check teacher conflict
            teacher_conflict = False
            if res.teacher_id:
                tc = Reservation.query.filter(
                    Reservation.teacher_id == res.teacher_id,
                    Reservation.date == d,
                    Reservation.status.in_(['approved', 'pending']),
                    Reservation.start_time < res.end_time,
                    Reservation.end_time > res.start_time
                ).first()
                if tc:
                    teacher_conflict = True

            is_available = allowed and not conflict and not teacher_conflict
            
            days.append({
                'date': d,
                'is_available': is_available,
                'message': msg if not allowed else ("Room Occupied" if conflict else "Teacher Busy" if teacher_conflict else "Available")
            })

        return render_template('reservations/repeat.html', res=res, start_date=start_date, end_date=end_date, days=days)

    return render_template('reservations/repeat.html', res=res, start_date=start_date, days=None)


@bp.route('/<int:reservation_id>/repeat_schedule', methods=['POST'])
@login_required
def repeat_schedule(reservation_id):
    res = Reservation.query.get_or_404(reservation_id)
    if res.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    new_date_str = request.form.get('new_date')
    end_date_str = request.form.get('end_date') # Capture end_date to keep context
    
    try:
        new_date = datetime.strptime(new_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date.', 'danger')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str))

    # Re-validate conflicts just to be safe
    allowed, msg = check_schedule_restrictions(new_date, res.start_time)
    if not allowed:
        flash(msg, 'danger')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str))

    conflict = check_conflict(res.classroom_id, new_date, res.start_time, res.end_time)
    if conflict:
        flash(f'Room conflict on {new_date}.', 'danger')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str))

    # Create the new reservation
    new_res = Reservation(
        user_id=current_user.id,
        classroom_id=res.classroom_id,
        course_id=res.course_id,
        subject_id=res.subject_id,
        teacher_id=res.teacher_id,
        title=res.title,
        description=res.description,
        date=new_date,
        start_time=res.start_time,
        end_time=res.end_time,
        status='approved'
    )
    db.session.add(new_res)
    db.session.commit()
    flash(f'Reservation successfully scheduled for {new_date}.', 'success')
    
    # REDIRECT BACK TO THE REPEAT PAGE
    return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str))


@bp.route('/<int:reservation_id>/repeat_schedule_all', methods=['POST'])
@login_required
def repeat_schedule_all(reservation_id):
    res = Reservation.query.get_or_404(reservation_id)
    if res.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    start_date_str = request.form.get('start_date')
    end_date_str = request.form.get('end_date')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid dates.', 'danger')
        return redirect(url_for('reservations.repeat_view', reservation_id=res.id))

    scheduled_count = 0
    current_date = start_date
    
    while current_date <= end_date:
        # Check restrictions
        allowed, _ = check_schedule_restrictions(current_date, res.start_time)
        if allowed:
            # Check room conflict
            conflict = check_conflict(res.classroom_id, current_date, res.start_time, res.end_time)
            if not conflict:
                # Check teacher conflict
                teacher_conflict = False
                if res.teacher_id:
                    tc = Reservation.query.filter(
                        Reservation.teacher_id == res.teacher_id,
                        Reservation.date == current_date,
                        Reservation.status.in_(['approved', 'pending']),
                        Reservation.start_time < res.end_time,
                        Reservation.end_time > res.start_time
                    ).first()
                    if tc:
                        teacher_conflict = True
                
                if not teacher_conflict:
                    new_res = Reservation(
                        user_id=current_user.id,
                        classroom_id=res.classroom_id,
                        course_id=res.course_id,
                        subject_id=res.subject_id,
                        teacher_id=res.teacher_id,
                        title=res.title,
                        description=res.description,
                        date=current_date,
                        start_time=res.start_time,
                        end_time=res.end_time,
                        status='approved'
                    )
                    db.session.add(new_res)
                    scheduled_count += 1
        current_date += timedelta(days=1)
        
    db.session.commit()
    flash(f'Successfully scheduled {scheduled_count} new reservations.', 'success')
    
    # REDIRECT BACK TO THE REPEAT PAGE
    return redirect(url_for('reservations.repeat_view', reservation_id=res.id, end_date=end_date_str))

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

    # 1. Check Holiday Database
    holiday = Holiday.query.filter_by(date=check_date, is_active=True).first()
    if holiday:
        return jsonify({
            'has_warning': True, 
            'message': f'Warning: This date is a holiday ({holiday.name}). Reservations are blocked.'
        })

    # 2. Check Sunday
    if check_date.weekday() == 6:
        return jsonify({
            'has_warning': True, 
            'message': 'Warning: Reservations cannot be scheduled on Sundays.'
        })

    return jsonify({'has_warning': False})