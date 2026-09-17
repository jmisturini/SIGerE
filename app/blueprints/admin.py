import hashlib
import os
import secrets

import requests
from datetime import date, datetime, timedelta, timezone
from flask import (Blueprint, render_template, redirect, url_for, flash, abort,
                   request, jsonify, current_app, session)
from flask_login import login_required, current_user
from app.models import (User, Classroom, Course, Subject, Holiday, Role, Permission,
                        RoomCategory, Unity, ApiToken, VtConfig, VtEmpresa,
                        VtEmpresaValor, ROLE_POR_PERFIL)
from app.forms import (ClassroomForm, CourseForm, SubjectForm, UserForm, HolidayForm, RoleForm,
                   RoomCategoryForm, UnityForm, FormVtEmpresa, FormVtConfig)
from app.extensions import db
from sqlalchemy import func
from app.commands import UNIDADES_JSON_PADRAO, _seed_unidades
from wtforms.validators import Optional
from app.permissions import require_permission
from app.utils import gerar_slug, slug_unico, redirect_back, redirect_preserving_args
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


def _proteger_super_admin(user):
    """Bloqueia a edição/ação sobre uma conta super-admin por operador que
    não seja o próprio super-admin: quem tem user:edit mas não tem '*'
    não pode alterar dados, senha nem ativar/desativar o super-admin
    (trocar a senha ou o e-mail dele seria assumir a conta)."""
    if user.has_permission('*') and not current_user.has_permission('*'):
        abort(403)


def _ids_papeis_super():
    """IDs dos papéis que concedem a permissão universal '*' — atribuir um
    deles equivale a promover a super-admin, logo é operação exclusiva do
    próprio super-admin."""
    return {r.id for r in Role.query.all()
            if any(p.code == '*' for p in r.permissions)}


def _negar_papel_super(form, atuais=()):
    """Valida que operador sem '*' não atribua papel super-admin (novo ou
    adicional). `atuais` são os papéis que o usuário já possui — mantê-los é
    permitido (a edição de outros campos não pode ser bloqueada por papel
    pré-existente, atribuído pelo super-admin). Retorna mensagem de erro ou
    None quando a atribuição é válida."""
    if current_user.has_permission('*'):
        return None
    super_ids = _ids_papeis_super()
    escolhidos = {form.role_id.data, *form.extra_roles.data}
    if (escolhidos - set(atuais)) & super_ids:
        return ('Apenas o super-administrador pode atribuir papéis com '
                'permissão universal (*).')
    return None


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


PERMS_PAINEL = ('system:dashboard', 'unity:read', 'api:manage', 'vt:empresas')

# Admin dashboard route
@bp.route('/')
@login_required
def dashboard():
    # Hub do painel: quem tem qualquer uma das áreas abrigadas aqui acessa —
    # os cartões são filtrados por permissão no template.
    if not any(current_user.has_permission(p) for p in PERMS_PAINEL):
        abort(403)
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
    # Botão mostrar/esconder desativados: por padrão a listagem exibe apenas
    # as contas ativas (?inativos=1 revela também as desativadas).
    mostrar_inativos = request.args.get('inativos') == '1'

    # Multi-unidade: usuários da unidade ativa + contas globais (sem unidade)
    query = User.query.filter((User.unity_id == current_unity_id()) | (User.unity_id.is_(None)))
    if not mostrar_inativos:
        query = query.filter(User.is_active_user == True)
    if search_name:
        query = query.filter(User.full_name.ilike(f'%{search_name}%'))
    if filter_type in ['teacher', 'employee']:
        query = query.filter_by(profile_type=filter_type)

    # Ordenação (padrão: papel, depois nome — agrupamento original da página)
    ordem = request.args.get('ordem', 'padrao')
    if ordem == 'nome':
        query = query.order_by(func.lower(User.full_name))
    elif ordem == 'nome_desc':
        query = query.order_by(func.lower(User.full_name).desc())
    elif ordem == 'matricula':
        # matrícula vazia por último; depois nome
        query = query.order_by(User.registration.is_(None), User.registration,
                               func.lower(User.full_name))
    elif ordem == 'status':
        query = query.order_by(User.is_active_user.desc(), func.lower(User.full_name))
    else:
        ordem = 'padrao'
        query = query.order_by(User.role, func.lower(User.full_name))

    users = db.paginate(query,
                        page=request.args.get('page', 1, type=int),
                        per_page=USERS_PER_PAGE, error_out=False)
    # users: Pagination (iterável) usado pela tabela; pagination: mesmo objeto
    # para os controles de página do template.
    return render_template('admin/users.html', users=users, pagination=users,
                           search_name=search_name, filter_type=filter_type,
                           mostrar_inativos=mostrar_inativos, ordem=ordem)

_PERFIL_LABEL = {'teacher': 'Professor', 'employee': 'Funcionário'}


def _preparar_form_usuario(form):
    """Choices dos selects (papel, módulos, unidade) comuns a criação e edição."""
    form.role_id.choices = [(r.id, r.label) for r in Role.query.order_by(Role.label).all()]
    form.extra_roles.choices = [(r.id, r.label) for r in Role.query.order_by(Role.label).all()]
    form.unity_id.choices = _unity_choices()
    if not form.unity_id.data:
        form.unity_id.data = current_unity_id()
    return form


def _aplicar_perfil(user, form, profile):
    """Grava os campos dependentes do perfil. O papel legado (coluna role) é
    derivado do profile_type pelo mapa único ROLE_POR_PERFIL (app.models)."""
    user.profile_type = profile
    user.role = ROLE_POR_PERFIL[profile]
    if profile == 'teacher':
        user.department = form.department.data
    else:
        user.sector = form.sector.data
        user.function = form.function.data
        user.is_teacher = form.is_teacher.data


@bp.route('/users/create', methods=['GET', 'POST'])
@login_required
@require_permission('user:create')
def create_user():
    return _criar_usuario(None)


@bp.route('/users/create-teacher', methods=['GET', 'POST'])
@login_required
@require_permission('user:create')
def create_teacher():
    return _criar_usuario('teacher')


@bp.route('/users/create-employee', methods=['GET', 'POST'])
@login_required
@require_permission('user:create')
def create_employee():
    return _criar_usuario('employee')


def _criar_usuario(profile_type):
    """Cadastro unificado (formulário único). A URL /users/create — usada pelo
    botão "Cadastrar Usuário" — abre sem tipo pré-escolhido; create-teacher e
    create-employee (checklist e compatibilidade) apenas pré-selecionam o
    perfil, que o formulário dinâmico permite trocar antes de salvar."""
    form = _preparar_form_usuario(UserForm(profile_type=profile_type or ''))
    if profile_type is None:
        # Opção vazia: força a escolha do tipo no próprio formulário.
        form.profile_type.choices = [('', 'Selecione o tipo de perfil…')] + list(form.profile_type.choices)
    if form.validate_on_submit():
        erro_papel = _negar_papel_super(form)
        if erro_papel:
            flash(erro_papel, 'danger')
            return render_template('admin/user_form.html', form=form,
                                   title=f"Cadastrar Novo {_PERFIL_LABEL.get(profile_type, 'Usuário')}",
                                   modo_edicao=False)
        user = User(
            email=form.email.data, full_name=form.full_name.data,
            registration=form.registration.data,
            is_active_user=form.is_active_user.data,
            unity_id=form.unity_id.data or None, role_id=form.role_id.data,
        )
        _aplicar_perfil(user, form, form.profile_type.data)
        user.extra_roles = Role.query.filter(Role.id.in_(form.extra_roles.data)).all()
        user.set_password(form.password.data)
        user.force_password_change = True
        db.session.add(user)
        db.session.commit()
        flash(f'{_PERFIL_LABEL[user.profile_type]} cadastrado com sucesso.', 'success')
        return redirect_preserving_args('admin.list_users')
    return render_template('admin/user_form.html', form=form,
                           title=f"Cadastrar Novo {_PERFIL_LABEL.get(profile_type, 'Usuário')}",
                           modo_edicao=False)

@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('user:edit')
def edit_user(user_id):
    user = _unity_scoped_or_404(db.get_or_404(User, user_id))
    _proteger_super_admin(user)

    form = UserForm(obj=user)
    form._obj_id = user.id
    form.password.validators = [Optional()]
    form.password.flags.required = False

    _preparar_form_usuario(form)
    if request.method == 'GET':
        # SelectMultipleField(coerce=int) não consegue pré-selecionar a partir
        # de obj=user (int(Role) falha silenciosamente) — setar os ids à mão.
        form.extra_roles.data = [r.id for r in user.extra_roles]
    if form.validate_on_submit():
        atuais = {user.role_id, *(r.id for r in user.extra_roles)}
        erro_papel = _negar_papel_super(form, atuais)
        if user.id == current_user.id and form.is_active_user.data == False:
            flash('Você não pode desativar sua própria conta.', 'danger')
        elif erro_papel:
            flash(erro_papel, 'danger')
        else:
            user.email = form.email.data
            user.full_name = form.full_name.data
            user.registration = form.registration.data
            user.is_active_user = form.is_active_user.data
            user.unity_id = form.unity_id.data or None
            user.role_id = form.role_id.data
            user.extra_roles = Role.query.filter(Role.id.in_(form.extra_roles.data)).all()

            # O perfil não muda na edição (seletor desabilitado no template);
            # passar o profile persistido evita que um POST forjado o altere.
            _aplicar_perfil(user, form, user.profile_type)

            if form.password.data:
                user.set_password(form.password.data)
                user.force_password_change = True
            db.session.commit()
            flash('Usuário atualizado com sucesso.', 'success')
            return redirect_preserving_args('admin.list_users')
    return render_template('admin/user_form.html', form=form,
                           title=f"Editar {_PERFIL_LABEL[user.profile_type]}",
                           modo_edicao=True, user=user)

@bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@require_permission('user:toggle')
def toggle_user(user_id):
    user = _unity_scoped_or_404(db.get_or_404(User, user_id))
    _proteger_super_admin(user)
    if user.id == current_user.id:
        flash('Você não pode desativar sua própria conta.', 'danger')
        return redirect_back('admin.list_users')
    user.is_active_user = not user.is_active_user
    db.session.commit()
    flash(f'Usuário {user.full_name} {"ativado" if user.is_active_user else "desativado"}.', 'success')
    return redirect_back('admin.list_users', anchor=f'user-{user_id}')

@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
@require_permission('user:edit')
def reset_user_password(user_id):
    """Gera uma senha temporária aleatória, exibe UMA vez ao administrador e
    força a troca no próximo login do usuário."""
    user = _unity_scoped_or_404(db.get_or_404(User, user_id))
    _proteger_super_admin(user)
    temp_password = secrets.token_urlsafe(9)
    user.set_password(temp_password)
    user.force_password_change = True
    db.session.commit()
    flash(f'Senha de {user.full_name} redefinida. Senha temporária '
          f'(exibida apenas agora — copie e envie ao usuário): {temp_password}', 'success')
    return redirect_back('admin.list_users', anchor=f'user-{user_id}')

# ================= ROOM MANAGEMENT =================


@bp.route('/rooms')
@login_required
@require_permission('room:read')
def list_rooms():
    rooms = Classroom.query.filter_by(unity_id=current_unity_id()).all()
    # Ordenação escolhida no filtro da página (padrão: código, como antes)
    ordem = request.args.get('ordem', 'codigo')
    if ordem == 'nome':
        rooms.sort(key=lambda r: r.name.lower())
    elif ordem == 'nome_desc':
        rooms.sort(key=lambda r: r.name.lower(), reverse=True)
    elif ordem == 'capacidade':
        rooms.sort(key=lambda r: (-(r.capacity or 0), r.code))
    elif ordem == 'predio':
        rooms.sort(key=lambda r: ((r.building or '').lower(), r.floor or '',
                                  r.code))
    else:
        ordem = 'codigo'
        rooms.sort(key=lambda r: r.code)
    return render_template('admin/rooms.html', rooms=rooms, ordem=ordem)

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
    return redirect_back('admin.list_rooms', anchor=f'room-{room_id}')

# ================= COURSE MANAGEMENT =================

@bp.route('/courses')
@login_required
@require_permission('course:read')
def list_courses():
    courses = Course.query.filter_by(unity_id=current_unity_id()).all()
    # Ordenação escolhida no filtro da página (padrão: nome A–Z). Feita em
    # Python para ser case-insensitive e contar disciplinas sem subconsulta.
    ordem = request.args.get('ordem', 'nome')
    if ordem == 'nome_desc':
        courses.sort(key=lambda c: c.name.lower(), reverse=True)
    elif ordem == 'codigo':
        courses.sort(key=lambda c: c.code.lower())
    elif ordem == 'disciplinas':
        courses.sort(key=lambda c: (-len(c.subjects), c.name.lower()))
    else:
        ordem = 'nome'
        courses.sort(key=lambda c: c.name.lower())
    return render_template('admin/courses.html', courses=courses, ordem=ordem)

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
    flash(f'Curso {course.code} {"ativada" if course.is_active else "desativado"}.', 'success')
    return redirect_back('admin.list_courses', anchor=f'course-{course_id}')

# ================= SUBJECT MANAGEMENT =================

@bp.route('/subjects')
@login_required
@require_permission('course:read')
def list_subjects():
    subjects = Subject.query.filter_by(unity_id=current_unity_id()).all()
    # Ordenação escolhida no filtro da página (padrão: nome A–Z). Feita em
    # Python para ordenar case-insensitive e agrupar por curso com as
    # disciplinas sem curso ao final.
    ordem = request.args.get('ordem', 'nome')
    if ordem == 'nome_desc':
        subjects.sort(key=lambda s: s.name.lower(), reverse=True)
    elif ordem == 'codigo':
        subjects.sort(key=lambda s: s.code.lower())
    elif ordem == 'curso':
        subjects.sort(key=lambda s: (s.course.name.lower() if s.course else '\uffff',
                                     s.name.lower()))
    else:
        ordem = 'nome'
        subjects.sort(key=lambda s: s.name.lower())
    return render_template('admin/subjects.html', subjects=subjects, ordem=ordem)

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
    return redirect_back('admin.list_subjects', anchor=f'subject-{subject_id}')

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
    return redirect_back('admin.list_holidays')

@bp.route('/holidays/import', methods=['POST'])
@login_required
@require_permission('holiday:import')
def import_holidays():
    year = request.form.get('year', datetime.now().year, type=int)

    if not (2000 <= year <= 2100):
        flash('Ano inválido. Use um valor entre 2000 e 2100.', 'danger')
        return redirect_back('admin.list_holidays')

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
    return redirect_back('admin.list_holidays')

# ================= ROLE MANAGEMENT =================

# Rótulos amigáveis dos módulos de permissão (agrupamento da tela de papéis).
# O Financeiro tem dois grupos de permissões separados (Pagamento Extra e
# Vale-Transporte) para que papéis distintos possam cobrir cada área.
MODULO_LABELS = {
    'course': 'Cursos', 'holiday': 'Feriados', 'kitchen': 'Cozinha',
    'payment': 'Pagamento Extra', 'reservation': 'Reservas', 'role': 'Papéis',
    'room': 'Salas', 'system': 'Sistema', 'unity': 'Unidades',
    'user': 'Usuários', 'vt': 'Vale-Transporte',
}

# Módulos de permissão que dependem de um módulo ligável por unidade:
# mapeiam o módulo da permissão para o código do módulo na Unity. Grupos
# fora deste mapa não dependem de módulo (o aviso contextual nunca aparece).
# Pagamento Extra e Vale-Transporte são áreas do módulo Financeiro.
MODULO_PERMISSAO_PARA_MODULO_UNIDADE = {
    'kitchen': Unity.MODULE_KITCHEN,
    'payment': Unity.MODULE_FINANCE,
    'vt': Unity.MODULE_FINANCE,
}


def _grupos_de_permissoes():
    """Permissões agrupadas por módulo — [(rótulo, [Permission...],
    modulo_unidade), ...] — alimentando a grade de checkboxes (com
    marcar/limpar por módulo). modulo_unidade é o código do módulo ligável
    por unidade que controla o grupo (None quando não depende de módulo) e
    serve ao aviso contextual de módulo desligado no formulário de papéis.
    A permissão universal '*' fica de fora da grade para operadores sem o
    próprio '*' (em par com _choices_permissoes_papel)."""
    perms = Permission.query.order_by(Permission.module, Permission.action).all()
    if not current_user.has_permission('*'):
        perms = [p for p in perms if p.code != '*']
    grupos, ordem = {}, []
    for p in perms:
        if p.module not in grupos:
            grupos[p.module] = []
            ordem.append(p.module)
        grupos[p.module].append(p)
    return [(MODULO_LABELS.get(m, m.title()), grupos[m],
             MODULO_PERMISSAO_PARA_MODULO_UNIDADE.get(m)) for m in ordem]


def _choices_permissoes_papel():
    """Choices da grade de permissões do formulário de papéis. A permissão
    universal '*' não aparece para operadores sem o próprio '*': marcá-la
    num papel criado/editado por eles seria auto-promoção a super-admin."""
    perms = Permission.query.order_by(Permission.module, Permission.action).all()
    if not current_user.has_permission('*'):
        perms = [p for p in perms if p.code != '*']
    return [(p.id, f"{p.module}: {p.action} ({p.code})") for p in perms]


def _e_papel_super_admin(role):
    """O papel do super-admin é o que carrega a permissão curinga '*' —
    identificá-lo pelo código (e não pelo nome) cobre também papéis
    customizados que venham a receber a permissão universal."""
    return any(p.code == '*' for p in role.permissions)


@bp.route('/roles')
@login_required
@require_permission('role:read')
def list_roles():
    roles = Role.query.all()
    # Ordenação escolhida no filtro da página (padrão: nome A–Z)
    ordem = request.args.get('ordem', 'nome')
    if ordem == 'nome_desc':
        roles.sort(key=lambda r: r.name.lower(), reverse=True)
    else:
        ordem = 'nome'
        roles.sort(key=lambda r: r.name.lower())
    return render_template('admin/roles.html', roles=roles, ordem=ordem,
                           ids_papel_super_admin={r.id for r in roles
                                                  if _e_papel_super_admin(r)})

@bp.route('/roles/create', methods=['GET', 'POST'])
@login_required
@require_permission('role:create')
def create_role():
    form = RoleForm()
    form.permissions.choices = _choices_permissoes_papel()
    
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
    # O papel do super-admin só pode ser alterado pelo próprio super-admin:
    # um admin comum (role:edit) poderia esvaziá-lo ou renomeá-lo, derrubando
    # o acesso universal do sistema. Vale para GET (formulário) e POST.
    if _e_papel_super_admin(role) and not current_user.has_permission('*'):
        flash('Apenas o super-admin pode editar o papel de Super Administrador.', 'danger')
        return redirect_back('admin.list_roles', anchor=f'role-{role_id}')
    form = RoleForm(obj=role)
    form.permissions.choices = _choices_permissoes_papel()
    
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
            # '*' não chega no POST de operador sem '*' (checkbox oculto):
            # preservada para a edição não revogar o super-admin do papel.
            if p.code == '*':
                selecionadas.add(p.id)
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
        return redirect_back('admin.list_roles', anchor=f'role-{role_id}')
    if len(role.users) > 0:
        flash('Não é possível excluir um papel que possui usuários vinculados. Mude os usuários de papel primeiro.', 'danger')
        return redirect_back('admin.list_roles', anchor=f'role-{role_id}')

    db.session.delete(role)
    db.session.commit()
    flash('Papel excluído.', 'info')
    return redirect_back('admin.list_roles')

# ================= ROOM CATEGORY MANAGEMENT =================

@bp.route('/categories')
@login_required
@require_permission('room:read')
def list_categories():
    categories = RoomCategory.query.all()
    # Ordenação escolhida no filtro da página (padrão: nome A–Z)
    ordem = request.args.get('ordem', 'nome')
    if ordem == 'nome_desc':
        categories.sort(key=lambda c: c.name.lower(), reverse=True)
    else:
        ordem = 'nome'
        categories.sort(key=lambda c: c.name.lower())
    return render_template('admin/categories.html', categories=categories, ordem=ordem)

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
    return redirect_back('admin.list_categories', anchor=f'category-{cat_id}')

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
        return redirect_back('admin.list_unities')
    try:
        criadas, atualizadas, ignorados = _seed_unidades(UNIDADES_JSON_PADRAO)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('Falha ao reler o arquivo de unidades.')
        flash(f'Falha ao reler o arquivo de unidades: {exc}', 'danger')
        return redirect_back('admin.list_unities')
    flash(f'Unidades atualizadas do arquivo do portal. Criadas: {criadas} | Atualizadas: {atualizadas}.', 'success')
    if ignorados:
        flash('Ignorados (sem cadastro_sugerido no JSON): ' + ', '.join(ignorados), 'info')
    return redirect_back('admin.list_unities')

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
        return redirect_back('admin.list_unities')
    unity.is_active = not unity.is_active
    db.session.commit()
    flash(f'Unidade {unity.name} {"ativada" if unity.is_active else "desativada"}.', 'success')
    return redirect_back('admin.list_unities', anchor=f'unity-{unity_id}')


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

# ================= VT: CONFIGURAÇÃO DO PEDIDO (por unidade) =================

@bp.route('/vt-configuracao', methods=['GET', 'POST'])
@login_required
@require_permission('vt:empresas')
def vt_configuracao():
    """Configurações do pedido público de VT da unidade ativa: números
    base de vales por trajeto (quando definidos, o formulário os aplica
    automaticamente) e data de fechamento (último dia para preencher)."""
    config = VtConfig.query.filter_by(unity_id=current_unity_id()).first()
    form = FormVtConfig(obj=config)
    if form.validate_on_submit():
        if config is None:
            config = VtConfig(unity_id=current_unity_id())
            db.session.add(config)
        config.vales_somente_ida = form.vales_somente_ida.data
        config.vales_ida_e_volta = form.vales_ida_e_volta.data
        config.fecha_em = form.fecha_em.data
        db.session.commit()
        flash('Configurações do pedido de VT salvas.', 'success')
        return redirect(url_for('admin.vt_configuracao'))
    return render_template('admin/vt_configuracao.html', form=form,
                           config=config)


# ================= VT: EMPRESAS DE ÔNIBUS (pedido público) =================
#
# Cadastro de empresas de ônibus e tarifas vigentes usado pelo formulário
# público de pedido de Vale-Transporte (/vt/pedido). Cada empresa pertence
# à unidade que a cadastrou: a listagem mostra só as da unidade ativa, o
# formulário público usa as da unidade do link e empresas de outras
# unidades ficam invisíveis (404).

@bp.route('/vt-empresas')
@login_required
@require_permission('vt:empresas')
def list_vt_empresas():
    empresas = (VtEmpresa.query
                .filter_by(unity_id=current_unity_id())
                .order_by(VtEmpresa.nome).all())
    return render_template('admin/vt_empresas.html', empresas=empresas)


def _linhas_tarifa_do_post():
    """Lê e valida as linhas dinâmicas de tarifa (identificação + valor)
    do POST. Devolve (linhas, erro): linhas é a lista [(identificacao,
    Decimal)] validada e erro a mensagem amigável (ou None)."""
    from app.forms import parse_tarifa_linhas
    try:
        return parse_tarifa_linhas(request.form.getlist('identificacao'),
                                   request.form.getlist('valor')), None
    except ValueError as exc:
        return None, str(exc)


@bp.route('/vt-empresas/create', methods=['GET', 'POST'])
@login_required
@require_permission('vt:empresas')
def create_vt_empresa():
    form = FormVtEmpresa()
    if form.validate_on_submit():
        linhas, erro = _linhas_tarifa_do_post()
        if erro:
            flash(erro, 'danger')
        elif VtEmpresa.query.filter(
                func.lower(VtEmpresa.nome) == form.nome.data.strip().lower(),
                VtEmpresa.unity_id == current_unity_id()).first():
            flash('Já existe uma empresa com este nome nesta unidade.', 'danger')
        else:
            empresa = VtEmpresa(nome=form.nome.data.strip(),
                                is_active=form.is_active.data,
                                unity_id=current_unity_id())
            empresa.valores = [VtEmpresaValor(identificacao=t, valor=v) for t, v in linhas]
            db.session.add(empresa)
            db.session.commit()
            flash(f'Empresa {empresa.nome} criada com sucesso.', 'success')
            return redirect(url_for('admin.list_vt_empresas'))
    # Re-render: repõe as linhas digitadas (ou uma vazia no primeiro acesso).
    linhas_tarifas = (list(zip(request.form.getlist('identificacao'),
                               request.form.getlist('valor')))
                      if request.method == 'POST' else [('', '')])
    return render_template('admin/vt_empresa_form.html', form=form,
                           title='Nova Empresa de Ônibus',
                           linhas_tarifas=linhas_tarifas)


@bp.route('/vt-empresas/<int:empresa_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('vt:empresas')
def edit_vt_empresa(empresa_id):
    empresa = db.get_or_404(VtEmpresa, empresa_id)
    if empresa.unity_id != current_unity_id():
        abort(404)  # empresa de outra unidade nem deve parecer existir
    form = FormVtEmpresa(obj=empresa)
    form._obj_id = empresa.id
    if form.validate_on_submit():
        linhas, erro = _linhas_tarifa_do_post()
        if erro:
            flash(erro, 'danger')
        elif VtEmpresa.query.filter(
                func.lower(VtEmpresa.nome) == form.nome.data.strip().lower(),
                VtEmpresa.unity_id == current_unity_id(),
                VtEmpresa.id != empresa.id).first():
            flash('Já existe outra empresa com este nome nesta unidade.', 'danger')
        else:
            empresa.nome = form.nome.data.strip()
            empresa.is_active = form.is_active.data
            empresa.valores = [VtEmpresaValor(identificacao=t, valor=v) for t, v in linhas]
            db.session.commit()
            flash(f'Empresa {empresa.nome} atualizada.', 'success')
            return redirect(url_for('admin.list_vt_empresas'))
    # Re-render: linhas digitadas no POST ou as vigentes da empresa.
    if request.method == 'POST':
        linhas_tarifas = list(zip(request.form.getlist('identificacao'),
                                  request.form.getlist('valor')))
    else:
        linhas_tarifas = [(v.identificacao, v.valor_texto) for v in empresa.valores]
    return render_template('admin/vt_empresa_form.html', form=form,
                           title='Editar Empresa de Ônibus', empresa=empresa,
                           linhas_tarifas=linhas_tarifas)


@bp.route('/vt-empresas/<int:empresa_id>/delete', methods=['POST'])
@login_required
@require_permission('vt:empresas')
def delete_vt_empresa(empresa_id):
    """Exclusão só remove do cadastro: os pedidos antigos guardam nome e
    tarifa como texto, então o histórico permanece íntegro."""
    empresa = db.get_or_404(VtEmpresa, empresa_id)
    if empresa.unity_id != current_unity_id():
        abort(404)
    nome = empresa.nome
    db.session.delete(empresa)
    db.session.commit()
    flash(f'Empresa {nome} excluída. Os pedidos antigos continuam com o '
          'nome e a tarifa registrados.', 'info')
    return redirect_back('admin.list_vt_empresas')

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
    # O token recém-gerado chega pela sessão (padrão PRG) e é consumido aqui:
    # exibido uma única vez — recarregar a página não reexibe o valor nem
    # cria novo token.
    new_token = session.pop('new_api_token', None)
    new_token_name = session.pop('new_api_token_name', None)
    return render_template('admin/api_tokens.html', tokens=tokens,
                           durations=TOKEN_DURATIONS, new_token=new_token,
                           new_token_name=new_token_name)


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
    # PRG (Post/Redirect/Get): o valor completo vai para a sessão e a rota
    # redireciona. Renderizar a listagem direto no POST mantinha o navegador
    # em /create — recarregar reenviava o POST gerando novos tokens, e o
    # redirect_back da primeira ação seguinte voltava a GET /create → 405.
    session['new_api_token'] = raw
    session['new_api_token_name'] = name
    return redirect(url_for('admin.list_api_tokens'))


@bp.route('/api-tokens/<int:token_id>/toggle', methods=['POST'])
@login_required
@require_permission('api:manage')
def toggle_api_token(token_id):
    token = db.get_or_404(ApiToken, token_id)
    token.is_active = not token.is_active
    db.session.commit()
    flash(f'Token "{token.name}" {"reativado" if token.is_active else "revogado"}.',
          'success' if token.is_active else 'warning')
    return redirect_back('admin.list_api_tokens', anchor=f'token-{token_id}')


@bp.route('/api-tokens/<int:token_id>/delete', methods=['POST'])
@login_required
@require_permission('api:manage')
def delete_api_token(token_id):
    token = db.get_or_404(ApiToken, token_id)
    db.session.delete(token)
    db.session.commit()
    flash(f'Token "{token.name}" excluído permanentemente.', 'success')
    return redirect_back('admin.list_api_tokens')
