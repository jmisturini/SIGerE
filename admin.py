import requests
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, abort, request
from flask_login import login_required, current_user
from models import User, Classroom, Reservation, Course, Subject, Holiday
from forms import ClassroomForm, CourseForm, SubjectForm, TeacherForm, EmployeeForm, HolidayForm
from extensions import db
from wtforms.validators import Optional

bp = Blueprint('admin', __name__, url_prefix='/admin')

@bp.route('/')
@login_required
def dashboard():
    if not current_user.is_admin:
        abort(403)
    users_count = User.query.count()
    rooms_count = Classroom.query.count()
    active_rooms = Classroom.query.filter_by(is_active=True).count()
    courses_count = Course.query.count()
    subjects_count = Subject.query.count()
    
    return render_template('admin/dashboard.html', 
                           users_count=users_count, 
                           rooms_count=rooms_count,
                           active_rooms=active_rooms,
                           courses_count=courses_count,
                           subjects_count=subjects_count)

# ================= USER MANAGEMENT =================

@bp.route('/users')
@login_required
def list_users():
    if not current_user.is_admin:
        abort(403)
        
    search_name = request.args.get('name', '')
    filter_type = request.args.get('type', '')
    
    query = User.query
    
    if search_name:
        query = query.filter(User.full_name.ilike(f'%{search_name}%'))
        
    if filter_type in ['teacher', 'employee']:
        query = query.filter_by(profile_type=filter_type)
        
    users = query.order_by(User.role, User.full_name).all()
    
    return render_template(
        'admin/users.html', 
        users=users,
        search_name=search_name,
        filter_type=filter_type
    )

@bp.route('/users/create-teacher', methods=['GET', 'POST'])
@login_required
def create_teacher():
    if not current_user.is_admin:
        abort(403)
    form = TeacherForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            full_name=form.full_name.data,
            role=form.role.data,
            department=form.department.data,
            registration=form.registration.data,
            profile_type='teacher',
            is_active_user=form.is_active_user.data
        )
        user.set_password(form.password.data)
        user.force_password_change = True
        db.session.add(user)
        db.session.commit()
        flash('Teacher created successfully.', 'success')
        return redirect(url_for('admin.list_users'))
    return render_template('admin/teacher_form.html', form=form, title='Register New Teacher')

@bp.route('/users/create-employee', methods=['GET', 'POST'])
@login_required
def create_employee():
    if not current_user.is_admin:
        abort(403)
    form = EmployeeForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data,
            email=form.email.data,
            full_name=form.full_name.data,
            role=form.role.data,
            sector=form.sector.data,
            function=form.function.data,
            registration=form.registration.data,
            profile_type='employee',
            is_teacher=form.is_teacher.data,
            is_active_user=form.is_active_user.data
        )
        user.set_password(form.password.data)
        user.force_password_change = True
        db.session.add(user)
        db.session.commit()
        flash('Employee created successfully.', 'success')
        return redirect(url_for('admin.list_users'))
    return render_template('admin/employee_form.html', form=form, title='Register New Employee')

@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    if not current_user.is_admin:
        abort(403)
    user = User.query.get_or_404(user_id)
    
    FormClass = TeacherForm if user.profile_type == 'teacher' else EmployeeForm
    form = FormClass(obj=user)
    form._obj_id = user.id
    
    form.password.validators = [Optional()]
    form.password.flags.required = False
    
    if form.validate_on_submit():
        if user.id == current_user.id and form.is_active_user.data == False:
            flash('You cannot deactivate your own account.', 'danger')
        elif user.id == current_user.id and form.role.data != 'admin':
            flash('You cannot change your own admin role.', 'danger')
        else:
            user.username = form.username.data
            user.email = form.email.data
            user.full_name = form.full_name.data
            user.role = form.role.data
            user.registration = form.registration.data
            user.is_active_user = form.is_active_user.data
            
            if user.profile_type == 'teacher':
                user.department = form.department.data
            else:
                user.sector = form.sector.data
                user.function = form.function.data
                user.is_teacher = form.is_teacher.data
                
            if form.password.data:
                user.set_password(form.password.data)
                user.force_password_change = True
            db.session.commit()
            flash('User updated successfully.', 'success')
            return redirect(url_for('admin.list_users'))
    return render_template('admin/edit_user.html', form=form, title='Edit User', user=user)

@bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
def toggle_user(user_id):
    if not current_user.is_admin:
        abort(403)
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin.list_users'))
    user.is_active_user = not user.is_active_user
    db.session.commit()
    status = 'activated' if user.is_active_user else 'deactivated'
    flash(f'User {user.full_name} {status}.', 'success')
    return redirect(url_for('admin.list_users'))

# ================= ROOM MANAGEMENT =================

@bp.route('/rooms')
@login_required
def list_rooms():
    if not current_user.is_admin:
        abort(403)
    rooms = Classroom.query.order_by(Classroom.code).all()
    return render_template('admin/rooms.html', rooms=rooms)

# Category abbreviation mapping
CATEGORY_ABBR = {
    'classroom': 'CR',
    'auditorium': 'AU',
    'kitchen': 'KI',
    'computer_lab': 'CP',
    'health_lab': 'HL'
}

@bp.route('/rooms/create', methods=['GET', 'POST'])
@login_required
def create_room():
    if not current_user.is_admin:
        abort(403)
    form = ClassroomForm()
    if form.validate_on_submit():
        abbr = CATEGORY_ABBR.get(form.category.data, 'XX')
        generated_code = f"{abbr}{form.room_number.data}"
        
        existing = Classroom.query.filter_by(code=generated_code).first()
        if existing:
            flash('A room with this type and number already exists.', 'danger')
            return render_template('admin/room_form.html', form=form, title='Create Classroom')

        classroom = Classroom(
            name=form.name.data, 
            code=generated_code, 
            room_number=form.room_number.data,
            building=form.building.data,
            floor=form.floor.data, 
            capacity=form.capacity.data,
            category=form.category.data,
            computer_count=form.computer_count.data if form.category.data == 'computer_lab' else 0,
            description=form.description.data, 
            is_active=form.is_active.data
        )
        db.session.add(classroom)
        db.session.commit()
        flash(f'Classroom {classroom.code} created!', 'success')
        return redirect(url_for('admin.list_rooms'))
    return render_template('admin/room_form.html', form=form, title='Create Classroom')

@bp.route('/rooms/<int:room_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_room(room_id):
    if not current_user.is_admin:
        abort(403)
    classroom = Classroom.query.get_or_404(room_id)
    form = ClassroomForm(obj=classroom)
    
    if form.validate_on_submit():
        abbr = CATEGORY_ABBR.get(form.category.data, 'XX')
        generated_code = f"{abbr}{form.room_number.data}"
        
        existing = Classroom.query.filter(Classroom.code == generated_code, Classroom.id != classroom.id).first()
        if existing:
            flash('A room with this type and number already exists.', 'danger')
            return render_template('admin/room_form.html', form=form, title='Edit Classroom')

        classroom.name = form.name.data
        classroom.code = generated_code
        classroom.room_number = form.room_number.data
        classroom.building = form.building.data
        classroom.floor = form.floor.data
        classroom.capacity = form.capacity.data
        classroom.category = form.category.data
        classroom.computer_count = form.computer_count.data if form.category.data == 'computer_lab' else 0
        classroom.description = form.description.data
        classroom.is_active = form.is_active.data
        
        db.session.commit()
        flash('Classroom updated.', 'success')
        return redirect(url_for('admin.list_rooms'))
    return render_template('admin/room_form.html', form=form, title='Edit Classroom')

@bp.route('/rooms/<int:room_id>/toggle', methods=['POST'])
@login_required
def toggle_room(room_id):
    if not current_user.is_admin:
        abort(403)
    classroom = Classroom.query.get_or_404(room_id)
    classroom.is_active = not classroom.is_active
    db.session.commit()
    status = 'activated' if classroom.is_active else 'deactivated'
    flash(f'Classroom {classroom.code} {status}.', 'success')
    return redirect(url_for('admin.list_rooms'))

# ================= COURSE MANAGEMENT =================

@bp.route('/courses')
@login_required
def list_courses():
    if not current_user.is_admin:
        abort(403)
    courses = Course.query.order_by(Course.name).all()
    return render_template('admin/courses.html', courses=courses)

@bp.route('/courses/create', methods=['GET', 'POST'])
@login_required
def create_course():
    if not current_user.is_admin:
        abort(403)
    form = CourseForm()
    if form.validate_on_submit():
        course = Course(
            name=form.name.data, code=form.code.data,
            description=form.description.data, is_active=form.is_active.data
        )
        db.session.add(course)
        db.session.commit()
        flash('Course created successfully.', 'success')
        return redirect(url_for('admin.list_courses'))
    return render_template('admin/course_form.html', form=form, title='Register New Course')

@bp.route('/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_course(course_id):
    if not current_user.is_admin:
        abort(403)
    course = Course.query.get_or_404(course_id)
    form = CourseForm(obj=course)
    form._obj_id = course.id
    if form.validate_on_submit():
        course.name = form.name.data
        course.code = form.code.data
        course.description = form.description.data
        course.is_active = form.is_active.data
        db.session.commit()
        flash('Course updated.', 'success')
        return redirect(url_for('admin.list_courses'))
    return render_template('admin/course_form.html', form=form, title='Edit Course')

@bp.route('/courses/<int:course_id>/toggle', methods=['POST'])
@login_required
def toggle_course(course_id):
    if not current_user.is_admin:
        abort(403)
    course = Course.query.get_or_404(course_id)
    course.is_active = not course.is_active
    db.session.commit()
    flash(f'Course {course.code} {"activated" if course.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin.list_courses'))

# ================= SUBJECT MANAGEMENT =================

@bp.route('/subjects')
@login_required
def list_subjects():
    if not current_user.is_admin:
        abort(403)
    subjects = Subject.query.order_by(Subject.name).all()
    return render_template('admin/subjects.html', subjects=subjects)

@bp.route('/subjects/create', methods=['GET', 'POST'])
@login_required
def create_subject():
    if not current_user.is_admin:
        abort(403)
    form = SubjectForm()
    form.course_id.choices = [(c.id, c.name) for c in Course.query.filter_by(is_active=True).order_by(Course.name).all()]
    form.course_id.choices.insert(0, (0, '-- No Specific Course --'))

    if form.validate_on_submit():
        subj = Subject(
            name=form.name.data, code=form.code.data,
            course_id=form.course_id.data if form.course_id.data > 0 else None,
            description=form.description.data, is_active=form.is_active.data
        )
        db.session.add(subj)
        db.session.commit()
        flash('Subject created successfully.', 'success')
        return redirect(url_for('admin.list_subjects'))
    return render_template('admin/subject_form.html', form=form, title='Register New Subject')

@bp.route('/subjects/<int:subject_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_subject(subject_id):
    if not current_user.is_admin:
        abort(403)
    subj = Subject.query.get_or_404(subject_id)
    form = SubjectForm(obj=subj)
    form._obj_id = subj.id
    form.course_id.choices = [(c.id, c.name) for c in Course.query.filter_by(is_active=True).order_by(Course.name).all()]
    form.course_id.choices.insert(0, (0, '-- No Specific Course --'))

    if form.validate_on_submit():
        subj.name = form.name.data
        subj.code = form.code.data
        subj.course_id = form.course_id.data if form.course_id.data > 0 else None
        subj.description = form.description.data
        subj.is_active = form.is_active.data
        db.session.commit()
        flash('Subject updated.', 'success')
        return redirect(url_for('admin.list_subjects'))
    return render_template('admin/subject_form.html', form=form, title='Edit Subject')

@bp.route('/subjects/<int:subject_id>/toggle', methods=['POST'])
@login_required
def toggle_subject(subject_id):
    if not current_user.is_admin:
        abort(403)
    subj = Subject.query.get_or_404(subject_id)
    subj.is_active = not subj.is_active
    db.session.commit()
    flash(f'Subject {subj.code} {"activated" if subj.is_active else "deactivated"}.', 'success')
    return redirect(url_for('admin.list_subjects'))

# ================= HOLIDAY MANAGEMENT =================

@bp.route('/holidays')
@login_required
def list_holidays():
    if not current_user.is_admin:
        abort(403)
    holidays = Holiday.query.order_by(Holiday.date).all()
    return render_template('admin/holidays.html', holidays=holidays)

@bp.route('/holidays/create', methods=['GET', 'POST'])
@login_required
def create_holiday():
    if not current_user.is_admin:
        abort(403)
    form = HolidayForm()
    if form.validate_on_submit():
        existing = Holiday.query.filter_by(date=form.date.data).first()
        if existing:
            flash('A holiday on this date already exists.', 'danger')
        else:
            h = Holiday(name=form.name.data, date=form.date.data, is_active=form.is_active.data)
            db.session.add(h)
            db.session.commit()
            flash('Holiday added successfully.', 'success')
            return redirect(url_for('admin.list_holidays'))
    return render_template('admin/holiday_form.html', form=form, title='Add Holiday')

@bp.route('/holidays/<int:holiday_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_holiday(holiday_id):
    if not current_user.is_admin:
        abort(403)
    h = Holiday.query.get_or_404(holiday_id)
    form = HolidayForm(obj=h)
    if form.validate_on_submit():
        h.name = form.name.data
        h.date = form.date.data
        h.is_active = form.is_active.data
        db.session.commit()
        flash('Holiday updated.', 'success')
        return redirect(url_for('admin.list_holidays'))
    return render_template('admin/holiday_form.html', form=form, title='Edit Holiday')

@bp.route('/holidays/<int:holiday_id>/delete', methods=['POST'])
@login_required
def delete_holiday(holiday_id):
    if not current_user.is_admin:
        abort(403)
    h = Holiday.query.get_or_404(holiday_id)
    db.session.delete(h)
    db.session.commit()
    flash('Holiday deleted.', 'info')
    return redirect(url_for('admin.list_holidays'))

@bp.route('/holidays/import', methods=['POST'])
@login_required
def import_holidays():
    if not current_user.is_admin:
        abort(403)
    
    country = request.form.get('country', 'BR')
    year = request.form.get('year', datetime.now().year, type=int)
    
    # Using the new NagerHoliday API
    url = f"https://nagerholidays.com/api/v4/Holidays/{country}/{year}"
    
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        imported_count = 0
        skipped_count = 0
        
        for item in data:
            # Nager API uses 'date' and 'name' (or 'localName')
            # Slice [:10] ensures we only get 'YYYY-MM-DD' even if time is included
            dt_str = item.get('date', '')[:10]
            name = item.get('name') or item.get('localName') or 'Public Holiday'
            
            if not dt_str:
                continue
                
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d').date()
            except ValueError:
                continue  # Skip if date is malformed
            
            exists = Holiday.query.filter_by(date=dt).first()
            if not exists:
                h = Holiday(name=name, date=dt, is_active=True)
                db.session.add(h)
                imported_count += 1
            else:
                skipped_count += 1
                
        db.session.commit()
        flash(f'Successfully imported {imported_count} new holidays. Skipped {skipped_count} existing.', 'success')
        
    except requests.exceptions.RequestException as e:
        flash(f'Failed to fetch from API: {str(e)}', 'danger')
    except Exception as e:
        flash(f'An error occurred: {str(e)}', 'danger')
        
    return redirect(url_for('admin.list_holidays'))