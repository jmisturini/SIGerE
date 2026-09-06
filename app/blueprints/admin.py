import secrets

import requests
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, current_app
from flask_login import login_required, current_user
from app.models import User, Classroom, Course, Subject, Holiday, Role, Permission, RoomCategory, Unity
from app.forms import (ClassroomForm, CourseForm, SubjectForm, TeacherForm, EmployeeForm, HolidayForm, RoleForm,
                   RoomCategoryForm, UnityForm)
from app.extensions import db
from wtforms.validators import Optional
from app.permissions import require_permission
from app.unity_context import current_unity_id

bp = Blueprint('admin', __name__, url_prefix='/admin')

USERS_PER_PAGE = 25

def _unity_choices():
    """Opções do select de unidades (todas as ativas)."""
    return [(u.id, u.name) for u in Unity.query.filter_by(is_active=True).order_by(Unity.name).all()]

def _unity_scoped_or_404(obj):
    """Garante que o recurso pertence à unidade ativa (contas globais sempre visíveis)."""
    if obj.unity_id is not None and obj.unity_id != current_unity_id():
        abort(404)
    return obj

# Admin dashboard route
@bp.route('/')
@login_required
@require_permission('system:dashboard')
def dashboard():
    uid = current_unity_id()
    users_count = User.query.filter((User.unity_id == uid) | (User.unity_id.is_(None))).count()
    rooms_count = Classroom.query.filter_by(unity_id=uid).count()
    active_rooms = Classroom.query.filter_by(unity_id=uid, is_active=True).count()
    courses_count = Course.query.filter_by(unity_id=uid).count()
    subjects_count = Subject.query.filter_by(unity_id=uid).count()

    return render_template('admin/dashboard.html',
                           users_count=users_count,
                           rooms_count=rooms_count,
                           active_rooms=active_rooms,
                           courses_count=courses_count,
                           subjects_count=subjects_count)

# ================= USER MANAGEMENT =================

@bp.route('/users')
@login_required
@require_permission('user:read')
def list_users():
    search_name = request.args.get('name', '')
    filter_type = request.args.get('type', '')

    # Multi-unidade: usuários da unidade ativa + contas globais (sem unidade)
    query = User.query.filter((User.unity_id == current_unity_id()) | (User.unity_id.is_(None)))
    if search_name:
        query = query.filter(User.full_name.ilike(f'%{search_name}%'))
    if filter_type in ['teacher', 'employee']:
        query = query.filter_by(profile_type=filter_type)

    users = db.paginate(query.order_by(User.role, User.full_name),
                        page=request.args.get('page', 1, type=int),
                        per_page=USERS_PER_PAGE, error_out=False)
    # users: Pagination (iterável) usado pela tabela; pagination: mesmo objeto
    # para os controles de página do template.
    return render_template('admin/users.html', users=users, pagination=users,
                           search_name=search_name, filter_type=filter_type)

@bp.route('/users/create-teacher', methods=['GET', 'POST'])
@login_required
@require_permission('user:create')
def create_teacher():
    form = TeacherForm()
    form.role_id.choices = [(r.id, r.label) for r in Role.query.order_by(Role.label).all()]
    form.unity_id.choices = _unity_choices()
    if not form.unity_id.data:
        form.unity_id.data = current_unity_id()
    if form.validate_on_submit():
        user = User(
            username=form.username.data, email=form.email.data, full_name=form.full_name.data,
            role='room', department=form.department.data, registration=form.registration.data,
            profile_type='teacher', is_active_user=form.is_active_user.data,
            unity_id=form.unity_id.data, role_id=form.role_id.data
        )
        user.set_password(form.password.data)
        user.force_password_change = True
        db.session.add(user)
        db.session.commit()
        flash('Professor cadastrado com sucesso.', 'success')
        return redirect(url_for('admin.list_users'))
    return render_template('admin/teacher_form.html', form=form, title='Cadastrar Novo Professor')

@bp.route('/users/create-employee', methods=['GET', 'POST'])
@login_required
@require_permission('user:create')
def create_employee():
    form = EmployeeForm()
    form.role_id.choices = [(r.id, r.label) for r in Role.query.order_by(Role.label).all()]
    form.unity_id.choices = _unity_choices()
    if not form.unity_id.data:
        form.unity_id.data = current_unity_id()
    if form.validate_on_submit():
        user = User(
            username=form.username.data, email=form.email.data, full_name=form.full_name.data,
            role='viewer', sector=form.sector.data, function=form.function.data,
            registration=form.registration.data, profile_type='employee', is_teacher=form.is_teacher.data,
            is_active_user=form.is_active_user.data,
            unity_id=form.unity_id.data, role_id=form.role_id.data
        )
        user.set_password(form.password.data)
        user.force_password_change = True
        db.session.add(user)
        db.session.commit()
        flash('Funcionário cadastrado com sucesso.', 'success')
        return redirect(url_for('admin.list_users'))
    return render_template('admin/employee_form.html', form=form, title='Cadastrar Novo Funcionário')

@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('user:edit')
def edit_user(user_id):
    user = _unity_scoped_or_404(db.get_or_404(User, user_id))

    FormClass = TeacherForm if user.profile_type == 'teacher' else EmployeeForm
    form = FormClass(obj=user)
    form._obj_id = user.id
    form.password.validators = [Optional()]
    form.password.flags.required = False

    form.role_id.choices = [(r.id, r.label) for r in Role.query.order_by(Role.label).all()]
    form.unity_id.choices = _unity_choices()
    if form.validate_on_submit():
        if user.id == current_user.id and form.is_active_user.data == False:
            flash('Você não pode desativar sua própria conta.', 'danger')
        else:
            user.username = form.username.data
            user.email = form.email.data
            user.full_name = form.full_name.data
            user.registration = form.registration.data
            user.is_active_user = form.is_active_user.data
            user.unity_id = form.unity_id.data or None
            user.role_id = form.role_id.data

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
            flash('Usuário atualizado com sucesso.', 'success')
            return redirect(url_for('admin.list_users'))
    return render_template('admin/edit_user.html', form=form, title='Editar Usuário', user=user)

@bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@require_permission('user:toggle')
def toggle_user(user_id):
    user = _unity_scoped_or_404(db.get_or_404(User, user_id))
    if user.id == current_user.id:
        flash('Você não pode desativar sua própria conta.', 'danger')
        return redirect(url_for('admin.list_users'))
    user.is_active_user = not user.is_active_user
    db.session.commit()
    flash(f'Usuário {user.full_name} {"ativado" if user.is_active_user else "desativado"}.', 'success')
    return redirect(url_for('admin.list_users'))

@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@require_permission('user:edit')
def reset_user_password(user_id):
    """Gera uma senha temporária aleatória, exibe UMA vez ao administrador e
    força a troca no próximo login do usuário."""
    user = _unity_scoped_or_404(db.get_or_404(User, user_id))
    temp_password = secrets.token_urlsafe(9)
    user.set_password(temp_password)
    user.force_password_change = True
    db.session.commit()
    flash(f'Senha de {user.full_name} redefinida. Senha temporária '
          f'(exibida apenas agora — copie e envie ao usuário): {temp_password}', 'success')
    return redirect(url_for('admin.list_users'))

# ================= ROOM MANAGEMENT =================


@bp.route('/rooms')
@login_required
@require_permission('room:read')
def list_rooms():
    rooms = Classroom.query.filter_by(unity_id=current_unity_id()).order_by(Classroom.code).all()
    return render_template('admin/rooms.html', rooms=rooms)

@bp.route('/rooms/create', methods=['GET', 'POST'])
@login_required
@require_permission('room:create')
def create_room():
    form = ClassroomForm()
    form.category_id.choices = [(c.id, c.name) for c in RoomCategory.query.filter_by(is_active=True).order_by(RoomCategory.name).all()]

    if form.validate_on_submit():
        cat = RoomCategory.query.get(form.category_id.data)
        generated_code = f"{cat.abbr}{form.room_number.data}" if cat.abbr else form.room_number.data

        # Unicidade do código de sala por unidade
        if Classroom.query.filter_by(unity_id=current_unity_id(), code=generated_code).first():
            flash('Uma sala com este código já existe nesta unidade.', 'danger')
            return render_template('admin/room_form.html', form=form, title='Criar Sala')

        classroom = Classroom(
            name=form.name.data, code=generated_code, room_number=form.room_number.data,
            building=form.building.data, floor=form.floor.data, capacity=form.capacity.data,
            category_id=form.category_id.data, unity_id=current_unity_id(),
            computer_count=form.computer_count.data if cat.code == 'computer_lab' else 0,
            description=form.description.data, is_active=form.is_active.data
        )
        db.session.add(classroom)
        db.session.commit()
        flash(f'Sala {classroom.code} criada!', 'success')
        return redirect(url_for('admin.list_rooms'))
    return render_template('admin/room_form.html', form=form, title='Criar Sala')

@bp.route('/rooms/<int:room_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('room:edit')
def edit_room(room_id):
    classroom = _unity_scoped_or_404(db.get_or_404(Classroom, room_id))
    form = ClassroomForm(obj=classroom)
    form.category_id.choices = [(c.id, c.name) for c in RoomCategory.query.filter_by(is_active=True).order_by(RoomCategory.name).all()]

    if form.validate_on_submit():
        cat = RoomCategory.query.get(form.category_id.data)
        generated_code = f"{cat.abbr}{form.room_number.data}" if cat.abbr else form.room_number.data

        if Classroom.query.filter(Classroom.code == generated_code, Classroom.unity_id == current_unity_id(),
                                  Classroom.id != classroom.id).first():
            flash('Uma sala com este código já existe nesta unidade.', 'danger')
            return render_template('admin/room_form.html', form=form, title='Editar Sala')

        classroom.name = form.name.data
        classroom.code = generated_code
        classroom.room_number = form.room_number.data
        classroom.building = form.building.data
        classroom.floor = form.floor.data
        classroom.capacity = form.capacity.data
        classroom.category_id = form.category_id.data
        classroom.computer_count = form.computer_count.data if cat.code == 'computer_lab' else 0
        classroom.description = form.description.data
        classroom.is_active = form.is_active.data
        db.session.commit()
        flash('Sala atualizada.', 'success')
        return redirect(url_for('admin.list_rooms'))
    return render_template('admin/room_form.html', form=form, title='Editar Sala')

@bp.route('/rooms/<int:room_id>/toggle', methods=['POST'])
@login_required
@require_permission('room:toggle')
def toggle_room(room_id):
    classroom = _unity_scoped_or_404(db.get_or_404(Classroom, room_id))
    classroom.is_active = not classroom.is_active
    db.session.commit()
    flash(f'Sala {classroom.code} {"ativada" if classroom.is_active else "desativada"}.', 'success')
    return redirect(url_for('admin.list_rooms'))

# ================= COURSE MANAGEMENT =================

@bp.route('/courses')
@login_required
@require_permission('course:read')
def list_courses():
    courses = Course.query.filter_by(unity_id=current_unity_id()).order_by(Course.name).all()
    return render_template('admin/courses.html', courses=courses)

@bp.route('/courses/create', methods=['GET', 'POST'])
@login_required
@require_permission('course:create')
def create_course():
    form = CourseForm()
    if form.validate_on_submit():
        db.session.add(Course(name=form.name.data, code=form.code.data, description=form.description.data,
                              is_active=form.is_active.data, unity_id=current_unity_id()))
        db.session.commit()
        flash('Curso criado com sucesso.', 'success')
        return redirect(url_for('admin.list_courses'))
    return render_template('admin/course_form.html', form=form, title='Cadastrar Novo Curso')

@bp.route('/courses/<int:course_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('course:edit')
def edit_course(course_id):
    course = _unity_scoped_or_404(db.get_or_404(Course, course_id))
    form = CourseForm(obj=course); form._obj_id = course.id
    if form.validate_on_submit():
        course.name=form.name.data; course.code=form.code.data; course.description=form.description.data; course.is_active=form.is_active.data
        db.session.commit()
        flash('Curso atualizado.', 'success')
        return redirect(url_for('admin.list_courses'))
    return render_template('admin/course_form.html', form=form, title='Editar Curso')

@bp.route('/courses/<int:course_id>/toggle', methods=['POST'])
@login_required
@require_permission('course:toggle')
def toggle_course(course_id):
    course = _unity_scoped_or_404(db.get_or_404(Course, course_id))
    course.is_active = not course.is_active
    db.session.commit()
    flash(f'Curso {course.code} {"ativado" if course.is_active else "desativado"}.', 'success')
    return redirect(url_for('admin.list_courses'))

# ================= SUBJECT MANAGEMENT =================

@bp.route('/subjects')
@login_required
@require_permission('course:read')
def list_subjects():
    subjects = Subject.query.filter_by(unity_id=current_unity_id()).order_by(Subject.name).all()
    return render_template('admin/subjects.html', subjects=subjects)

@bp.route('/subjects/create', methods=['GET', 'POST'])
@login_required
@require_permission('course:create')
def create_subject():
    form = SubjectForm()
    form.course_id.choices = [(c.id, c.name) for c in Course.query.filter_by(unity_id=current_unity_id(), is_active=True).order_by(Course.name).all()]
    form.course_id.choices.insert(0, (0, '-- Nenhum Curso Específico --'))
    if form.validate_on_submit():
        db.session.add(Subject(name=form.name.data, code=form.code.data, unity_id=current_unity_id(),
                               course_id=form.course_id.data if form.course_id.data > 0 else None, description=form.description.data, is_active=form.is_active.data))
        db.session.commit()
        flash('Disciplina criada com sucesso.', 'success')
        return redirect(url_for('admin.list_subjects'))
    return render_template('admin/subject_form.html', form=form, title='Cadastrar Nova Disciplina')

@bp.route('/subjects/<int:subject_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('course:edit')
def edit_subject(subject_id):
    subj = _unity_scoped_or_404(db.get_or_404(Subject, subject_id))
    form = SubjectForm(obj=subj); form._obj_id = subj.id
    form.course_id.choices = [(c.id, c.name) for c in Course.query.filter_by(unity_id=current_unity_id(), is_active=True).order_by(Course.name).all()]
    form.course_id.choices.insert(0, (0, '-- Nenhum Curso Específico --'))
    if form.validate_on_submit():
        subj.name=form.name.data; subj.code=form.code.data; subj.course_id=form.course_id.data if form.course_id.data > 0 else None; subj.description=form.description.data; subj.is_active=form.is_active.data
        db.session.commit()
        flash('Disciplina atualizada.', 'success')
        return redirect(url_for('admin.list_subjects'))
    return render_template('admin/subject_form.html', form=form, title='Editar Disciplina')

@bp.route('/subjects/<int:subject_id>/toggle', methods=['POST'])
@login_required
@require_permission('course:toggle')
def toggle_subject(subject_id):
    subj = _unity_scoped_or_404(db.get_or_404(Subject, subject_id))
    subj.is_active = not subj.is_active
    db.session.commit()
    flash(f'Disciplina {subj.code} {"ativada" if subj.is_active else "desativada"}.', 'success')
    return redirect(url_for('admin.list_subjects'))

# ================= HOLIDAY MANAGEMENT =================

@bp.route('/holidays')
@login_required
@require_permission('holiday:read')
def list_holidays():
    holidays = Holiday.query.filter_by(unity_id=current_unity_id()).order_by(Holiday.date).all()
    return render_template('admin/holidays.html', holidays=holidays)

@bp.route('/holidays/create', methods=['GET', 'POST'])
@login_required
@require_permission('holiday:create')
def create_holiday():
    form = HolidayForm()
    if form.validate_on_submit():
        if Holiday.query.filter_by(unity_id=current_unity_id(), date=form.date.data).first():
            flash('Um feriado nesta data já existe nesta unidade.', 'danger')
        else:
            db.session.add(Holiday(name=form.name.data, date=form.date.data, is_active=form.is_active.data,
                                   unity_id=current_unity_id()))
            db.session.commit()
            flash('Feriado adicionado com sucesso.', 'success')
            return redirect(url_for('admin.list_holidays'))
    return render_template('admin/holiday_form.html', form=form, title='Adicionar Feriado')

@bp.route('/holidays/<int:holiday_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('holiday:edit')
def edit_holiday(holiday_id):
    h = _unity_scoped_or_404(db.get_or_404(Holiday, holiday_id))
    form = HolidayForm(obj=h)
    if form.validate_on_submit():
        h.name=form.name.data; h.date=form.date.data; h.is_active=form.is_active.data
        db.session.commit()
        flash('Feriado atualizado.', 'success')
        return redirect(url_for('admin.list_holidays'))
    return render_template('admin/holiday_form.html', form=form, title='Editar Feriado')

@bp.route('/holidays/<int:holiday_id>/delete', methods=['POST'])
@login_required
@require_permission('holiday:delete')
def delete_holiday(holiday_id):
    h = _unity_scoped_or_404(db.get_or_404(Holiday, holiday_id))
    db.session.delete(h)
    db.session.commit()
    flash('Feriado excluído.', 'info')
    return redirect(url_for('admin.list_holidays'))

@bp.route('/holidays/import', methods=['POST'])
@login_required
@require_permission('holiday:import')
def import_holidays():
    year = request.form.get('year', datetime.now().year, type=int)

    if not (2000 <= year <= 2100):
        flash('Ano inválido. Use um valor entre 2000 e 2100.', 'danger')
        return redirect(url_for('admin.list_holidays'))

    url = f"https://brasilapi.com.br/api/feriados/v1/{year}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        imported_count, skipped_count = 0, 0

        for item in data:
            dt_str = item.get('date', '')[:10]
            name = item.get('name', 'Feriado Nacional')
            if not dt_str: continue
            try: dt = datetime.strptime(dt_str, '%Y-%m-%d').date()
            except ValueError: continue

            # Feriados importados são vinculados à unidade ativa
            if not Holiday.query.filter_by(unity_id=current_unity_id(), date=dt).first():
                db.session.add(Holiday(name=name, date=dt, is_active=True, unity_id=current_unity_id()))
                imported_count += 1
            else: skipped_count += 1

        db.session.commit()
        flash(f'{imported_count} novos feriados importados. {skipped_count} ignorados.', 'success')
    except Exception:
        current_app.logger.exception('Falha ao importar feriados da BrasilAPI')
        flash('Erro ao buscar os feriados na BrasilAPI. Tente novamente mais tarde.', 'danger')
    return redirect(url_for('admin.list_holidays'))

# ================= ROLE MANAGEMENT =================

@bp.route('/roles')
@login_required
@require_permission('role:read')
def list_roles():
    roles = Role.query.order_by(Role.name).all()
    return render_template('admin/roles.html', roles=roles)

@bp.route('/roles/create', methods=['GET', 'POST'])
@login_required
@require_permission('role:create')
def create_role():
    form = RoleForm()
    form.permissions.choices = [(p.id, f"{p.module}: {p.action} ({p.code})") for p in Permission.query.order_by(Permission.module, Permission.action).all()]
    
    if form.validate_on_submit():
        role = Role(name=form.name.data, label=form.label.data, description=form.description.data, is_system=False)
        if form.permissions.data:
            role.permissions = Permission.query.filter(Permission.id.in_(form.permissions.data)).all()
        db.session.add(role)
        db.session.commit()
        flash('Papel criado com sucesso.', 'success')
        return redirect(url_for('admin.list_roles'))
    return render_template('admin/role_form.html', form=form, title='Criar Papel')

@bp.route('/roles/<int:role_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('role:edit')
def edit_role(role_id):
    role = db.get_or_404(Role, role_id)
    form = RoleForm(obj=role)
    form.permissions.choices = [(p.id, f"{p.module}: {p.action} ({p.code})") for p in Permission.query.order_by(Permission.module, Permission.action).all()]
    
    if request.method == 'GET':
        form.permissions.data = [p.id for p in role.permissions]
        
    if form.validate_on_submit():
        role.label = form.label.data
        role.description = form.description.data
        if form.permissions.data:
            role.permissions = Permission.query.filter(Permission.id.in_(form.permissions.data)).all()
        else:
            role.permissions = []
        db.session.commit()
        flash('Papel atualizado com sucesso.', 'success')
        return redirect(url_for('admin.list_roles'))
    return render_template('admin/role_form.html', form=form, title='Editar Papel')

@bp.route('/roles/<int:role_id>/delete', methods=['POST'])
@login_required
@require_permission('role:delete')
def delete_role(role_id):
    role = db.get_or_404(Role, role_id)
    if role.is_system:
        flash('Papéis do sistema não podem ser excluídos.', 'danger')
        return redirect(url_for('admin.list_roles'))
    if len(role.users) > 0:
        flash('Não é possível excluir um papel que possui usuários vinculados. Mude os usuários de papel primeiro.', 'danger')
        return redirect(url_for('admin.list_roles'))
        
    db.session.delete(role)
    db.session.commit()
    flash('Papel excluído.', 'info')
    return redirect(url_for('admin.list_roles'))

# ================= ROOM CATEGORY MANAGEMENT =================

@bp.route('/categories')
@login_required
@require_permission('room:read')
def list_categories():
    categories = RoomCategory.query.order_by(RoomCategory.name).all()
    return render_template('admin/categories.html', categories=categories)

@bp.route('/categories/create', methods=['GET', 'POST'])
@login_required
@require_permission('room:create')
def create_category():
    form = RoomCategoryForm()
    if form.validate_on_submit():
        exists = RoomCategory.query.filter_by(code=form.code.data).first()
        if exists:
            flash('Já existe uma categoria com este código.', 'danger')
        else:
            cat = RoomCategory(
                name=form.name.data, code=form.code.data, 
                abbr=form.abbr.data.upper() if form.abbr.data else None, 
                is_active=form.is_active.data
            )
            db.session.add(cat)
            db.session.commit()
            flash('Categoria criada com sucesso.', 'success')
            return redirect(url_for('admin.list_categories'))
    return render_template('admin/category_form.html', form=form, title='Criar Categoria')

@bp.route('/categories/<int:cat_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('room:edit')
def edit_category(cat_id):
    cat = db.get_or_404(RoomCategory, cat_id)
    form = RoomCategoryForm(obj=cat)
    if form.validate_on_submit():
        cat.name = form.name.data
        cat.code = form.code.data
        cat.abbr = form.abbr.data.upper() if form.abbr.data else None
        cat.is_active = form.is_active.data
        db.session.commit()
        flash('Categoria atualizada.', 'success')
        return redirect(url_for('admin.list_categories'))
    return render_template('admin/category_form.html', form=form, title='Editar Categoria')

@bp.route('/categories/<int:cat_id>/toggle', methods=['POST'])
@login_required
@require_permission('room:toggle')
def toggle_category(cat_id):
    cat = db.get_or_404(RoomCategory, cat_id)
    cat.is_active = not cat.is_active
    db.session.commit()
    flash(f'Categoria {cat.name} {"ativada" if cat.is_active else "desativada"}.', 'success')
    return redirect(url_for('admin.list_categories'))

# ================= UNITY MANAGEMENT (Multi-unidade) =================

@bp.route('/unities')
@login_required
@require_permission('unity:read')
def list_unities():
    unities = Unity.query.order_by(Unity.name).all()
    # Contagem de recursos por unidade para exibição na listagem
    counts = {u.id: Classroom.query.filter_by(unity_id=u.id).count() for u in unities}
    users_count = {}
    for u in unities:
        users_count[u.id] = User.query.filter(User.unity_id == u.id).count()
    return render_template('admin/unities.html', unities=unities, room_counts=counts, users_count=users_count)

@bp.route('/unities/create', methods=['GET', 'POST'])
@login_required
@require_permission('unity:create')
def create_unity():
    form = UnityForm()
    if form.validate_on_submit():
        unity = Unity(name=form.name.data, code=form.code.data.upper(),
                      address=form.address.data, phone=form.phone.data,
                      is_active=form.is_active.data)
        db.session.add(unity)
        db.session.commit()
        flash(f'Unidade "{unity.name}" criada com sucesso.', 'success')
        return redirect(url_for('admin.list_unities'))
    return render_template('admin/unity_form.html', form=form, title='Nova Unidade Educacional')

@bp.route('/unities/<int:unity_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('unity:edit')
def edit_unity(unity_id):
    unity = db.get_or_404(Unity, unity_id)
    form = UnityForm(obj=unity); form._obj_id = unity.id
    if form.validate_on_submit():
        unity.name = form.name.data
        unity.code = form.code.data.upper()
        unity.address = form.address.data
        unity.phone = form.phone.data
        unity.is_active = form.is_active.data
        db.session.commit()
        flash('Unidade atualizada.', 'success')
        return redirect(url_for('admin.list_unities'))
    return render_template('admin/unity_form.html', form=form, title='Editar Unidade')

@bp.route('/unities/<int:unity_id>/toggle', methods=['POST'])
@login_required
@require_permission('unity:toggle')
def toggle_unity(unity_id):
    unity = db.get_or_404(Unity, unity_id)
    if unity.is_active and unity.id == current_unity_id():
        flash('Não é possível desativar a unidade em que você está operando.', 'danger')
        return redirect(url_for('admin.list_unities'))
    unity.is_active = not unity.is_active
    db.session.commit()
    flash(f'Unidade {unity.name} {"ativada" if unity.is_active else "desativada"}.', 'success')
    return redirect(url_for('admin.list_unities'))
