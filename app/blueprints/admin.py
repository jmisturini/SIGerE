import hashlib
import os
import secrets

import requests
from datetime import datetime, timedelta, timezone
from flask import Blueprint, render_template, redirect, url_for, flash, abort, request, jsonify, current_app
from flask_login import login_required, current_user
from app.models import User, Classroom, Course, Subject, Holiday, Role, Permission, RoomCategory, Unity, ApiToken
from app.forms import (ClassroomForm, CourseForm, SubjectForm, TeacherForm, EmployeeForm, HolidayForm, RoleForm,
                   RoomCategoryForm, UnityForm)
from app.extensions import db
from app.commands import UNIDADES_JSON_PADRAO, _seed_unidades
from wtforms.validators import Optional
from app.permissions import require_permission
from app.utils import gerar_slug, slug_unico
from app.unity_context import current_unity_id, unity_module_enabled

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

def _unity_visivel_or_404(unity):
    """Escopo de visibilidade da PRÓPRIA unidade: administrador vinculado a
    uma unidade acessa apenas a sua — as demais ficam escondidas (404, sem
    revelar que existem). Super-admin (*) e contas globais sem vínculo
    acessam todas."""
    if current_user.has_permission('*') or not current_user.unity_id:
        return unity
    if unity.id != current_user.unity_id:
        abort(404)
    return unity

def _setup_checklist():
    """Passos da configuração inicial do sistema, cada um com o estado real
    dos dados no banco — aparece no painel do super-admin enquanto houver
    pendências e desaparece sozinho quando tudo estiver cadastrado."""
    funcionarios = User.query.filter(
        User.profile_type == 'employee', User.id != current_user.id).count()
    return [
        {'titulo': 'Cadastrar Unidade',
         'descricao': 'A unidade educacional à qual salas, usuários e reservas pertencem.',
         'url': url_for('admin.create_unity'),
         'concluido': Unity.query.count() > 0},
        {'titulo': 'Cadastrar Categorias de Sala',
         'descricao': 'Tipos de espaço (sala de aula, laboratório, auditório...) com cor e ícone no totem.',
         'url': url_for('admin.create_category'),
         'concluido': RoomCategory.query.count() > 0},
        {'titulo': 'Cadastrar Sala',
         'descricao': 'Os espaços físicos que receberão as reservas.',
         'url': url_for('admin.create_room'),
         'concluido': Classroom.query.count() > 0},
        {'titulo': 'Cadastrar Professor',
         'descricao': 'Docentes que podem ser designados nas reservas.',
         'url': url_for('admin.create_teacher'),
         'concluido': User.query.filter_by(profile_type='teacher').count() > 0},
        {'titulo': 'Cadastrar Funcionário',
         'descricao': 'Equipe administrativa e de apoio.',
         'url': url_for('admin.create_employee'),
         'concluido': funcionarios > 0},
        {'titulo': 'Cadastrar Curso',
         'descricao': 'Cursos vinculáveis às reservas e às disciplinas.',
         'url': url_for('admin.create_course'),
         'concluido': Course.query.count() > 0},
        {'titulo': 'Cadastrar Disciplina',
         'descricao': 'Disciplinas ministradas dentro de um curso.',
         'url': url_for('admin.create_subject'),
         'concluido': Subject.query.count() > 0},
        {'titulo': 'Importar os feriados',
         'descricao': 'Feriados nacionais (via BrasilAPI) bloqueiam reservas nas datas.',
         'url': url_for('admin.list_holidays'),
         'concluido': Holiday.query.count() > 0},
    ]


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

    # Checklist de configuração inicial: apenas o super-admin (curinga *).
    setup_checklist = _setup_checklist() if current_user.has_permission('*') else None
    if setup_checklist and all(p['concluido'] for p in setup_checklist):
        setup_checklist = None  # tudo pronto: o painel volta ao normal

    return render_template('admin/dashboard.html',
                           users_count=users_count,
                           rooms_count=rooms_count,
                           active_rooms=active_rooms,
                           courses_count=courses_count,
                           subjects_count=subjects_count,
                           setup_checklist=setup_checklist)

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
    # O nome de usuário é a parte anterior ao @ do e-mail informado.
    if request.method == 'POST':
        form.username.data = (request.form.get('email') or '').strip().split('@')[0]
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
    # O nome de usuário é a parte anterior ao @ do e-mail informado.
    if request.method == 'POST':
        form.username.data = (request.form.get('email') or '').strip().split('@')[0]
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
            # Nome opcional: sem ele, o próprio código identifica a sala.
            name=(form.name.data or '').strip() or generated_code,
            code=generated_code, room_number=form.room_number.data,
            building=form.building.data, floor=form.floor.data, capacity=form.capacity.data,
            category_id=form.category_id.data, unity_id=current_unity_id(),
            computer_count=form.computer_count.data if cat.controla_computadores else 0,
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

        classroom.name = (form.name.data or '').strip() or generated_code
        classroom.code = generated_code
        classroom.room_number = form.room_number.data
        classroom.building = form.building.data
        classroom.floor = form.floor.data
        classroom.capacity = form.capacity.data
        classroom.category_id = form.category_id.data
        classroom.computer_count = form.computer_count.data if cat.controla_computadores else 0
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

# Rótulos amigáveis dos módulos de permissão (agrupamento da tela de papéis)
MODULO_LABELS = {
    'course': 'Cursos', 'holiday': 'Feriados', 'kitchen': 'Cozinha',
    'payment': 'Financeiro', 'reservation': 'Reservas', 'role': 'Papéis',
    'room': 'Salas', 'system': 'Sistema', 'unity': 'Unidades',
    'user': 'Usuários',
}

# Módulos de permissão que dependem de um módulo ligável por unidade:
# mapeiam o módulo da permissão para o código do módulo na Unity. Grupos
# fora deste mapa não dependem de módulo (o aviso contextual nunca aparece).
MODULO_PERMISSAO_PARA_MODULO_UNIDADE = {
    'kitchen': Unity.MODULE_KITCHEN,
    'payment': Unity.MODULE_FINANCE,
}


def _grupos_de_permissoes():
    """Permissões agrupadas por módulo — [(rótulo, [Permission...],
    modulo_unidade), ...] — alimentando a grade de checkboxes (com
    marcar/limpar por módulo). modulo_unidade é o código do módulo ligável
    por unidade que controla o grupo (None quando não depende de módulo) e
    serve ao aviso contextual de módulo desligado no formulário de papéis."""
    grupos, ordem = {}, []
    for p in Permission.query.order_by(Permission.module, Permission.action).all():
        if p.module not in grupos:
            grupos[p.module] = []
            ordem.append(p.module)
        grupos[p.module].append(p)
    return [(MODULO_LABELS.get(m, m.title()), grupos[m],
             MODULO_PERMISSAO_PARA_MODULO_UNIDADE.get(m)) for m in ordem]


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
        # Nome de sistema gerado automaticamente do rótulo (slug único).
        names = {r.name for r in Role.query.all()}
        role = Role(name=slug_unico(gerar_slug(form.label.data), names),
                    label=form.label.data, description=form.description.data, is_system=False)
        if form.permissions.data:
            role.permissions = Permission.query.filter(Permission.id.in_(form.permissions.data)).all()
        db.session.add(role)
        db.session.commit()
        flash('Papel criado com sucesso.', 'success')
        return redirect(url_for('admin.list_roles'))
    return render_template('admin/role_form.html', form=form, title='Criar Papel',
                           grupos_permissoes=_grupos_de_permissoes())

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
        selecionadas = set(form.permissions.data or [])
        # Checkboxes de módulos desligados na unidade ativa não chegam no
        # POST (inputs desabilitados não são enviados): preserva o que o
        # papel já tem desses módulos, para a edição não revogar acessos
        # que seguem valendo nas outras unidades. Tornam a ser editáveis
        # quando o módulo for reativado.
        for p in role.permissions:
            modulo = MODULO_PERMISSAO_PARA_MODULO_UNIDADE.get(p.module)
            if modulo and not unity_module_enabled(modulo):
                selecionadas.add(p.id)
        if selecionadas:
            role.permissions = Permission.query.filter(Permission.id.in_(selecionadas)).all()
        else:
            role.permissions = []
        db.session.commit()
        flash('Papel atualizado com sucesso.', 'success')
        return redirect(url_for('admin.list_roles'))
    return render_template('admin/role_form.html', form=form, title='Editar Papel',
                           grupos_permissoes=_grupos_de_permissoes())

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
        # Código interno é gerado automaticamente do nome (slug único) — o
        # usuário final só informa o nome da categoria.
        codes = {c.code for c in RoomCategory.query.all()}
        cat = RoomCategory(
            name=form.name.data,
            code=slug_unico(gerar_slug(form.name.data), codes),
            abbr=form.abbr.data.upper() if form.abbr.data else None,
            color=(form.color.data or '').lower() or None,
            icon=form.icon.data or None,
            totem_window=form.totem_window.data,
            controla_computadores=form.controla_computadores.data,
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
        cat.abbr = form.abbr.data.upper() if form.abbr.data else None
        cat.color = (form.color.data or '').lower() or None
        cat.icon = form.icon.data or None
        cat.totem_window = form.totem_window.data
        cat.controla_computadores = form.controla_computadores.data
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
    # Administrador vinculado a uma unidade vê apenas a sua — as demais
    # ficam escondidas. Super-admin (*) e contas globais veem todas.
    if current_user.has_permission('*') or not current_user.unity_id:
        unities = Unity.query.all()
    else:
        unities = Unity.query.filter_by(id=current_user.unity_id).all()
    # Contagem de recursos por unidade para exibição na listagem
    counts = {u.id: Classroom.query.filter_by(unity_id=u.id).count() for u in unities}
    users_count = {}
    for u in unities:
        users_count[u.id] = User.query.filter(User.unity_id == u.id).count()

    # Ordenação clicando nos cabeçalhos (?sort=<campo>&dir=asc|desc)
    sort = request.args.get('sort', 'name')
    reverse = request.args.get('dir', 'asc') == 'desc'
    chaves = {
        'id': lambda u: u.id,
        'name': lambda u: u.name.lower(),
        'code': lambda u: (u.code or '').lower(),
        'rooms': lambda u: counts.get(u.id, 0),
        'users': lambda u: users_count.get(u.id, 0),
        'status': lambda u: 0 if u.is_active else 1,  # asc = ativas primeiro
    }
    unities = sorted(unities, key=chaves.get(sort, chaves['name']), reverse=reverse)

    return render_template('admin/unities.html', unities=unities, room_counts=counts,
                           users_count=users_count, sort=sort, reverse=reverse)

@bp.route('/unities/sync', methods=['POST'])
@login_required
@require_permission('unity:create')
def sync_unities():
    """Relê docs/unidades-senac-sc.json pela mesma lógica do comando
    `seed-unidades`: cria as unidades ausentes e atualiza endereço/telefone
    das existentes, sem duplicar (idempotente)."""
    if not os.path.exists(UNIDADES_JSON_PADRAO):
        flash(f'Arquivo de unidades não encontrado: {UNIDADES_JSON_PADRAO}', 'danger')
        return redirect(url_for('admin.list_unities'))
    try:
        criadas, atualizadas, ignorados = _seed_unidades(UNIDADES_JSON_PADRAO)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Falha ao reler o arquivo de unidades.')
        flash(f'Falha ao reler o arquivo de unidades: {exc}', 'danger')
        return redirect(url_for('admin.list_unities'))
    flash(f'Unidades atualizadas do arquivo do portal. Criadas: {criadas} | Atualizadas: {atualizadas}.', 'success')
    if ignorados:
        flash('Ignorados (sem cadastro_sugerido no JSON): ' + ', '.join(ignorados), 'info')
    return redirect(url_for('admin.list_unities'))

@bp.route('/unities/create', methods=['GET', 'POST'])
@login_required
@require_permission('unity:create')
def create_unity():
    form = UnityForm()
    if form.validate_on_submit():
        unity = Unity(name=form.name.data, code=form.code.data.upper(),
                      address=form.address.data, phone=form.phone.data,
                      weather_latitude=form.weather_latitude.data,
                      weather_longitude=form.weather_longitude.data,
                      weather_city=form.weather_city.data,
                      kitchen_enabled=form.kitchen_enabled.data,
                      finance_enabled=form.finance_enabled.data,
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
    unity = _unity_visivel_or_404(db.get_or_404(Unity, unity_id))
    form = UnityForm(obj=unity); form._obj_id = unity.id
    if form.validate_on_submit():
        unity.name = form.name.data
        unity.code = form.code.data.upper()
        unity.address = form.address.data
        unity.phone = form.phone.data
        unity.weather_latitude = form.weather_latitude.data
        unity.weather_longitude = form.weather_longitude.data
        unity.weather_city = form.weather_city.data
        unity.is_active = form.is_active.data
        # Módulos NÃO vêm do formulário: na edição eles mudam apenas pelos
        # botões da própria página, que exigem vínculo com a unidade (a
        # permissão unity:edit sozinha não autoriza ligar/desligar módulos).
        db.session.commit()
        flash('Unidade atualizada.', 'success')
        return redirect(url_for('admin.list_unities'))
    return render_template('admin/unity_form.html', form=form, title='Editar Unidade',
                           unity=unity, toggleable_modules=Unity.TOGGLEABLE_MODULES)

@bp.route('/unities/geocode')
@login_required
@require_permission('unity:edit')
def geocode_unity():
    """Converte um endereço/cidade em coordenadas (busca do clima da unidade).

    Usa o Nominatim (OpenStreetMap) — serviço público e sem chave; o User-Agent
    identificando a aplicação é exigido pela política de uso deles.
    """
    query = (request.args.get('q') or '').strip()
    if len(query) < 3:
        return jsonify({'results': [], 'error': 'Informe pelo menos 3 caracteres para buscar.'}), 400
    try:
        resp = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': query, 'format': 'jsonv2', 'limit': 5,
                    'addressdetails': 1, 'accept-language': 'pt-BR'},
            headers={'User-Agent': 'SIGerE/1.0 (painel administrativo)'},
            timeout=8)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError):
        return jsonify({'results': [], 'error': 'Falha ao consultar o serviço de endereços. Tente novamente.'}), 502

    results = []
    for item in data:
        addr = item.get('address', {})
        # Rótulo curto para preencher o campo "cidade exibida": cidade + estado
        city = ', '.join(filter(None, [addr.get('city') or addr.get('town')
                                       or addr.get('village') or addr.get('municipality'),
                                       addr.get('state')]))
        results.append({
            'label': item.get('display_name'),
            'latitude': float(item['lat']),
            'longitude': float(item['lon']),
            'city': city,
        })
    return jsonify({'results': results})

@bp.route('/unities/<int:unity_id>/toggle', methods=['POST'])
@login_required
@require_permission('unity:toggle')
def toggle_unity(unity_id):
    unity = _unity_visivel_or_404(db.get_or_404(Unity, unity_id))
    if unity.is_active and unity.id == current_unity_id():
        flash('Não é possível desativar a unidade em que você está operando.', 'danger')
        return redirect(url_for('admin.list_unities'))
    unity.is_active = not unity.is_active
    db.session.commit()
    flash(f'Unidade {unity.name} {"ativada" if unity.is_active else "desativada"}.', 'success')
    return redirect(url_for('admin.list_unities'))


@bp.route('/unities/<int:unity_id>/modules/<module_code>/toggle', methods=['POST'])
@login_required
@require_permission('unity:modules')
def toggle_unity_module(unity_id, module_code):
    """Liga/desliga um módulo opcional (Cozinha, Financeiro) da unidade.

    Os botões ficam na página de edição da unidade. Pode alternar apenas o
    super-admin (curinga *) ou o administrador vinculado à própria unidade —
    contas globais sem vínculo e admins de outras unidades recebem 403.
    Módulos fora da lista de alternáveis (ex: reservas, o core do sistema)
    não têm botão nem rota: o 404 abaixo barra a tentativa pela URL."""
    unity = db.get_or_404(Unity, unity_id)
    if not (current_user.has_permission('*') or current_user.unity_id == unity.id):
        abort(403)
    module = next((m for m in Unity.TOGGLEABLE_MODULES if m['code'] == module_code), None)
    if module is None:
        abort(404)
    setattr(unity, module['attr'], not getattr(unity, module['attr']))
    db.session.commit()
    estado = 'ativado' if getattr(unity, module['attr']) else 'desativado'
    flash(f'Módulo {module["label"]} {estado} para a unidade {unity.name}.', 'success')
    return redirect(url_for('admin.edit_unity', unity_id=unity.id))

# ================= API TOKENS (integrações externas) =================
#
# Tokens Bearer da API pública de leitura de reservas (/api/v1). O valor
# completo é mostrado UMA VEZ na geração — o banco guarda só o hash SHA-256.
# O escopo dos dados retornados pela API é o do usuário criador do token.

TOKEN_DURATIONS = [(0, 'Sem expiração'), (30, '30 dias'), (60, '60 dias'),
                   (90, '90 dias'), (180, '180 dias'), (365, '1 ano')]


def _token_hash(raw):
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


@bp.route('/api-tokens')
@login_required
@require_permission('api:manage')
def list_api_tokens():
    tokens = ApiToken.query.order_by(ApiToken.created_at.desc()).all()
    return render_template('admin/api_tokens.html', tokens=tokens,
                           durations=TOKEN_DURATIONS)


@bp.route('/api-tokens/create', methods=['POST'])
@login_required
@require_permission('api:manage')
def create_api_token():
    name = (request.form.get('name') or '').strip()
    if len(name) < 3:
        flash('Informe um nome com pelo menos 3 caracteres para o token.', 'danger')
        return redirect(url_for('admin.list_api_tokens'))

    days = request.form.get('duration', type=int) or 0
    expires_at = None
    if days > 0:
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)

    raw = 'sige_' + secrets.token_urlsafe(32)
    token = ApiToken(name=name,
                     token_hash=_token_hash(raw),
                     prefix=raw[:13] + '…',
                     created_by_id=current_user.id,
                     expires_at=expires_at)
    db.session.add(token)
    db.session.commit()
    # Renderiza a própria listagem com o valor completo exibido uma única vez.
    tokens = ApiToken.query.order_by(ApiToken.created_at.desc()).all()
    return render_template('admin/api_tokens.html', tokens=tokens,
                           durations=TOKEN_DURATIONS, new_token=raw,
                           new_token_name=name)


@bp.route('/api-tokens/<int:token_id>/toggle', methods=['POST'])
@login_required
@require_permission('api:manage')
def toggle_api_token(token_id):
    token = db.get_or_404(ApiToken, token_id)
    token.is_active = not token.is_active
    db.session.commit()
    flash(f'Token "{token.name}" {"reativado" if token.is_active else "revogado"}.',
          'success' if token.is_active else 'warning')
    return redirect(url_for('admin.list_api_tokens'))


@bp.route('/api-tokens/<int:token_id>/delete', methods=['POST'])
@login_required
@require_permission('api:manage')
def delete_api_token(token_id):
    token = db.get_or_404(ApiToken, token_id)
    db.session.delete(token)
    db.session.commit()
    flash(f'Token "{token.name}" excluído permanentemente.', 'success')
    return redirect(url_for('admin.list_api_tokens'))
