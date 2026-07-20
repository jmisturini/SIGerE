from flask import Blueprint, render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user
from models import Reservation, Classroom, User, Course, Subject
from forms import ReservationForm
from extensions import db
from datetime import date

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


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.can_book:
        flash('Viewers can only request changes. Please contact a Room Booker or Admin.', 'warning')
        return redirect(url_for('classrooms.list_classrooms'))

    form = ReservationForm()
    
    # Populate Classroom choices
    classrooms = Classroom.query.filter_by(is_active=True).order_by(Classroom.code).all()
    form.classroom.choices = [
        (c.id, f"{c.code} - {c.name} ({c.building or 'N/A'}, cap {c.capacity})")
        for c in classrooms
    ]
    
    # Populate Course and Subject choices
    form.course.choices = [(0, '-- None --')] + [(c.id, c.name) for c in Course.query.filter_by(is_active=True).order_by(Course.name).all()]
    form.subject.choices = [(0, '-- None --')] + [(s.id, f"{s.name} ({s.course.name if s.course else 'General'})") for s in Subject.query.filter_by(is_active=True).order_by(Subject.name).all()]
    
    # NEW: Populate Teacher choices (Teachers OR Employees who are also teachers)
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

        classroom_id = form.classroom.data
        
        # 1. Check Classroom conflict
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

        # 2. Check Teacher conflict
        teacher_id = form.teacher.data if form.teacher.data > 0 else None
        if teacher_id:
            teacher_conflict = Reservation.query.filter(
                Reservation.teacher_id == teacher_id,
                Reservation.date == form.date.data,
                Reservation.status == 'approved',
                Reservation.start_time < form.end_time.data,
                Reservation.end_time > form.start_time.data
            ).first()
            
            if teacher_conflict and not form.acknowledge_teacher_conflict.data:
                flash(
                    f'Warning: {teacher_conflict.teacher.full_name} is already booked from '
                    f'{teacher_conflict.start_time.strftime("%H:%M")} to {teacher_conflict.end_time.strftime("%H:%M")}. '
                    f'You must check the acknowledgment box to proceed.', 'danger'
                )
                return render_template('reservations/create.html', form=form, classrooms=classrooms)

        reservation = Reservation(
            user_id=current_user.id,
            classroom_id=classroom_id,
            course_id=form.course.data if form.course.data > 0 else None,
            subject_id=form.subject.data if form.subject.data > 0 else None,
            teacher_id=teacher_id, # NEW
            title=form.title.data,
            description=form.description.data,
            date=form.date.data,
            start_time=form.start_time.data,
            end_time=form.end_time.data,
            status='approved'
        )
        db.session.add(reservation)
        db.session.commit()
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
    reservations = query.order_by(
        Reservation.date.desc(), Reservation.start_time
    ).all()
    return render_template(
        'reservations/my_reservations.html',
        reservations=reservations, current_status=status
    )

# NEW: Admin view to see all reservations
@bp.route('/all')
@login_required
def all_reservations():
    if not current_user.is_admin:
        abort(403)
    reservations = Reservation.query.order_by(
        Reservation.date.desc(), Reservation.start_time
    ).all()
    return render_template('reservations/all.html', reservations=reservations)


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