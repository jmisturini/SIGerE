"""Comandos CLI customizados para o Flask."""
import click
from flask.cli import with_appcontext
from app.extensions import db
from app.models import (
    User, Classroom, Reservation, Course, Subject,
    TeacherBasePay, Role, Permission, RoomCategory, Unity
)
from datetime import datetime, date, time, timedelta
import random


# Códigos de permissão do sistema (code, module, action, description).
# Mantido no nível do módulo para ser reutilizado pelo seed e pelo comando
# `flask sync-permissions` (upgrade idempotente em bancos já existentes).
PERMISSION_DATA = [
    ('user:read', 'user', 'read', 'Visualizar usuários'),
    ('user:create', 'user', 'create', 'Criar usuários'),
    ('user:edit', 'user', 'edit', 'Editar usuários'),
    ('user:toggle', 'user', 'toggle', 'Ativar/desativar usuários'),
    # Módulo de Unidades Educacionais (multi-unidade)
    ('unity:read', 'unity', 'read', 'Visualizar unidades educacionais'),
    ('unity:create', 'unity', 'create', 'Criar unidades educacionais'),
    ('unity:edit', 'unity', 'edit', 'Editar unidades educacionais'),
    ('unity:toggle', 'unity', 'toggle', 'Ativar/desativar unidades educacionais'),
    ('unity:switch', 'unity', 'switch', 'Alternar a unidade ativa de operação'),
    ('room:read', 'room', 'read', 'Visualizar salas'),
    ('room:create', 'room', 'create', 'Criar salas'),
    ('room:edit', 'room', 'edit', 'Editar salas'),
    ('room:toggle', 'room', 'toggle', 'Ativar/desativar salas'),
    ('reservation:read_all', 'reservation', 'read_all', 'Ver todas as reservas'),
    ('reservation:read_own', 'reservation', 'read_own', 'Ver próprias reservas'),
    ('reservation:create', 'reservation', 'create', 'Criar reservas'),
    ('reservation:edit_all', 'reservation', 'edit_all', 'Editar todas as reservas'),
    ('reservation:edit_own', 'reservation', 'edit_own', 'Editar próprias reservas'),
    ('reservation:delete_all', 'reservation', 'delete_all', 'Excluir todas as reservas'),
    ('reservation:cancel_own', 'reservation', 'cancel_own', 'Cancelar próprias reservas'),
    ('reservation:cancel_all', 'reservation', 'cancel_all', 'Cancelar todas as reservas'),
    ('reservation:approve', 'reservation', 'approve', 'Aprovar reservas pendentes'),
    ('course:read', 'course', 'read', 'Visualizar cursos/disciplinas'),
    ('course:create', 'course', 'create', 'Criar cursos/disciplinas'),
    ('course:edit', 'course', 'edit', 'Editar cursos/disciplinas'),
    ('course:toggle', 'course', 'toggle', 'Ativar/desativar cursos/disciplinas'),
    ('holiday:read', 'holiday', 'read', 'Visualizar feriados'),
    ('holiday:create', 'holiday', 'create', 'Criar feriados'),
    ('holiday:edit', 'holiday', 'edit', 'Editar feriados'),
    ('holiday:delete', 'holiday', 'delete', 'Excluir feriados'),
    ('holiday:import', 'holiday', 'import', 'Importar feriados da API'),
    ('payment:read', 'payment', 'read', 'Ver todos os pagamentos'),
    ('payment:read_own', 'payment', 'read_own', 'Ver próprios pagamentos'),
    ('payment:create', 'payment', 'create', 'Criar lançamentos'),
    ('payment:edit', 'payment', 'edit', 'Editar lançamentos'),
    ('payment:delete', 'payment', 'delete', 'Excluir lançamentos'),
    ('payment:export', 'payment', 'export', 'Exportar pagamentos'),
    # Módulo de Cozinha (fichas técnicas, preparações e compras)
    ('kitchen:read', 'kitchen', 'read', 'Acessar o módulo de Cozinha (fichas técnicas, preparações e compras)'),
    ('kitchen:sheet_create', 'kitchen', 'sheet_create', 'Enviar e salvar fichas técnicas (DOCX)'),
    ('kitchen:sheet_delete', 'kitchen', 'sheet_delete', 'Excluir fichas técnicas e preparações'),
    ('kitchen:shopping_export', 'kitchen', 'shopping_export', 'Gerar e exportar a requisição de compra'),
    ('system:dashboard', 'system', 'dashboard', 'Acessar painel administrativo'),
    ('system:export', 'system', 'export', 'Exportar dados diversos'),
    ('role:read', 'role', 'read', 'Visualizar papéis'),
    ('role:create', 'role', 'create', 'Criar papéis'),
    ('role:edit', 'role', 'edit', 'Editar papéis'),
    ('role:delete', 'role', 'delete', 'Excluir papéis'),
    ('*', 'system', 'all', 'Permissão universal (super admin)'),
]

# Configuração dos papéis padrão e suas permissões.
ROLES_CONFIG = {
    'super_admin': {
        'label': 'Super Administrador',
        'is_system': True,
        'permissions': ['*']
    },
    'admin': {
        'label': 'Administrador',
        'is_system': True,
        'permissions': [
            'user:read', 'user:create', 'user:edit', 'user:toggle',
            'unity:read', 'unity:create', 'unity:edit', 'unity:toggle', 'unity:switch',
            'room:read', 'room:create', 'room:edit', 'room:toggle',
            'course:read', 'course:create', 'course:edit', 'course:toggle',
            'holiday:read', 'holiday:create', 'holiday:edit', 'holiday:delete', 'holiday:import',
            'reservation:read_all', 'reservation:edit_all', 'reservation:delete_all',
            'reservation:approve', 'reservation:cancel_all',
            'system:dashboard', 'system:export',
            'role:read', 'role:create', 'role:edit', 'role:delete',
            'kitchen:read', 'kitchen:sheet_create', 'kitchen:sheet_delete', 'kitchen:shopping_export'
        ]
    },
    'financial_admin': {
        'label': 'Administrador Financeiro',
        'is_system': False,
        'permissions': [
            'payment:read', 'payment:create', 'payment:edit', 'payment:delete', 'payment:export',
            'user:read', 'system:export',
            'kitchen:read', 'kitchen:shopping_export'
        ]
    },
    'coordinator': {
        'label': 'Coordenador Pedagógico',
        'is_system': False,
        'permissions': [
            'room:read', 'course:read', 'course:create', 'course:edit', 'course:toggle',
            'reservation:read_all', 'reservation:approve',
            'reservation:edit_all', 'reservation:cancel_all',
            'user:read',
            'kitchen:read', 'kitchen:sheet_create', 'kitchen:shopping_export'
        ]
    },
    'room_manager': {
        'label': 'Gestor de Salas',
        'is_system': False,
        'permissions': [
            'room:read', 'room:create', 'room:edit', 'room:toggle',
            'reservation:read_all', 'reservation:edit_all', 'reservation:cancel_all',
            'system:export',
            'kitchen:read'
        ]
    },
    'teacher': {
        'label': 'Professor',
        'is_system': False,
        'permissions': [
            'reservation:create', 'reservation:read_own',
            'reservation:edit_own', 'reservation:cancel_own',
            'room:read', 'course:read', 'payment:read_own',
            'kitchen:read', 'kitchen:sheet_create', 'kitchen:shopping_export'
        ]
    },
    'employee': {
        'label': 'Funcionário',
        'is_system': False,
        'permissions': [
            'room:read', 'course:read', 'reservation:read_own',
            'kitchen:read'
        ]
    },
    'viewer': {
        'label': 'Visualizador',
        'is_system': False,
        'permissions': [
            'room:read', 'course:read',
            'kitchen:read'
        ]
    }
}


@click.command('seed')
@with_appcontext
def seed_command():
    """Popula o banco de dados com dados iniciais.

    Uso: flask seed
    """
    if User.query.count() > 0:
        click.echo(click.style(
            "⚠️  O banco de dados já contém dados. Pulando população.",
            fg="yellow"
        ))
        return

    click.echo(click.style("🌱 Iniciando população do banco...", fg="green", bold=True))

    try:
        _seed_permissions()
        _seed_admin()
        db.session.commit()
        click.echo(click.style("✅ Administrador criado com sucesso!", fg="green", bold=True))
        click.echo(click.style(
            "   Login: admin/admin123",
            fg="cyan"
        ))

        # Pergunta se deseja popular com dados de teste
        populate_demo = click.confirm(
            click.style("Deseja popular o banco com dados de demonstração?", fg="yellow"),
            default=False
        )

        if populate_demo:
            click.echo(click.style("📦 Populando dados de demonstração...", fg="blue"))
            _seed_demo_data()
            db.session.commit()
            click.echo(click.style("✅ Dados de demonstração criados com sucesso!", fg="green", bold=True))
            click.echo(click.style(
                "   Logins adicionais: teacher1/teacher123 | employee1/employee123",
                fg="cyan"
            ))
        else:
            click.echo(click.style("ℹ️  Apenas o administrador foi criado.", fg="blue"))

    except Exception as exc:
        db.session.rollback()
        click.echo(click.style(
            f"❌ Falha na população. Todas as alterações foram revertidas.\n   Erro: {exc}",
            fg="red", bold=True
        ))
        raise click.ClickException(str(exc))


@click.command('sync-permissions')
@with_appcontext
def sync_permissions_command():
    """Sincroniza permissões e papéis definidos no código com o banco.

    Cria permissões e papéis ausentes e concede às roles os códigos
    definidos em ROLES_CONFIG. Não remove nada já concedido. Útil para
    atualizar bancos criados antes de novos módulos.

    Uso: flask sync-permissions
    """
    sync_permissions_impl(verbose=True)


def sync_permissions_impl(verbose=True):
    """Lógica compartilhada do sync de permissões.

    Chamada pelo comando `flask sync-permissions` e também durante o startup
    (app.py) para garantir que permissões de módulos novos (ex: unity:*)
    existam em bancos já existentes sem passo manual.
    """
    created_perms, created_roles, created_links = 0, 0, 0
    log = click.echo if verbose else (lambda *a, **k: None)

    try:
        perm_objects = {p.code: p for p in Permission.query.all()}
        for code, module, action, desc in PERMISSION_DATA:
            if code not in perm_objects:
                p = Permission(code=code, module=module, action=action, description=desc)
                db.session.add(p)
                perm_objects[code] = p
                created_perms += 1
        db.session.flush()

        for role_name, config in ROLES_CONFIG.items():
            role = Role.query.filter_by(name=role_name).first()
            if not role:
                role = Role(name=role_name, label=config['label'],
                            is_system=config.get('is_system', False))
                db.session.add(role)
                created_roles += 1
                log(f"   ➕ Papel criado: {config['label']}")

            existing = {p.code for p in role.permissions}
            for perm_code in config['permissions']:
                if perm_code not in existing and perm_code in perm_objects:
                    role.permissions.append(perm_objects[perm_code])
                    created_links += 1

        db.session.commit()
        if verbose:
            click.echo(click.style("✅ Permissões sincronizadas com sucesso!", fg="green", bold=True))
            click.echo(f"   Permissões criadas: {created_perms}")
            click.echo(f"   Papéis criados: {created_roles}")
            click.echo(f"   Vínculos papel↔permissão adicionados: {created_links}")
        return created_perms, created_roles, created_links
    except Exception as exc:
        db.session.rollback()
        raise click.ClickException(f"Falha ao sincronizar permissões: {exc}")


def _seed_permissions():
    """Cria permissões e roles padrão."""
    if Role.query.count() > 0:
        return

    click.echo("   Criando sistema de permissões...")

    perm_objects = {}
    for code, module, action, desc in PERMISSION_DATA:
        p = Permission(code=code, module=module, action=action, description=desc)
        db.session.add(p)
        perm_objects[code] = p

    db.session.flush()

    for role_name, config in ROLES_CONFIG.items():
        role = Role(name=role_name, label=config['label'], is_system=config['is_system'])
        for perm_code in config['permissions']:
            if perm_code in perm_objects:
                role.permissions.append(perm_objects[perm_code])
        db.session.add(role)

    db.session.flush()
    click.echo("   ✅ Permissões e roles criadas.")


def _seed_admin():
    """Cria apenas o usuário administrador."""
    click.echo("   Criando usuário administrador...")

    super_admin_role = Role.query.filter_by(name='super_admin').first()

    admin = User(
        username='admin', email='admin@school.edu',
        full_name='Administrador do Sistema', role='admin',
        department='Administration', profile_type='employee',
        force_password_change=False,
        role_id=super_admin_role.id
    )
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.flush()
    click.echo("   ✅ Administrador criado.")


def _seed_demo_data():
    """Popula dados de demonstração (usuários, salas, cursos, reservas, etc.)."""
    click.echo("   Populando dados de demonstração...")

    teacher_role = Role.query.filter_by(name='teacher').first()
    employee_role = Role.query.filter_by(name='employee').first()
    admin = User.query.filter_by(username='admin').first()

    # 0. Unidades educacionais de demonstração
    unity_names = [("Unidade Centro", "CTR"), ("Unidade Norte", "NOR"), ("Unidade Sul", "SUL")]
    unities = []
    for name, code in unity_names:
        unity = Unity.query.filter_by(name=name).first()
        if not unity:
            unity = Unity(name=name, code=code, is_active=True)
            db.session.add(unity)
        unities.append(unity)
    db.session.flush()
    main_unity = unities[0]  # dados acadêmicos/estoque demonstrados na unidade principal
    unity_ids = [u.id for u in unities]
    click.echo(f"   ✅ {len(unities)} unidades educacionais criadas.")

    # 1. 100 Usuários
    first_names = [
        "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
        "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
        "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
        "Matthew", "Margaret", "Anthony", "Sandra", "Mark", "Ashley", "Donald", "Kimberly",
        "Steven", "Emily", "Paul", "Donna", "Andrew", "Michelle", "Joshua", "Carol",
        "Kenneth", "Amanda", "Kevin", "Melissa", "Brian", "Deborah", "George", "Stephanie",
        "Edward", "Rebecca"
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
        "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
        "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores"
    ]

    users_created = 0
    teachers_list = []

    for i in range(1, 21):
        fname = random.choice(first_names)
        lname = random.choice(last_names)
        is_teacher_flag = (i in [1, 2])
        e = User(
            username=f"employee{i}",
            email=f"employee{i}@school.edu",
            full_name=f"{fname} {lname}",
            role='room' if is_teacher_flag else 'viewer',
            sector="Administration",
            function=random.choice(["Coordinator", "Secretary", "Technician", "Director"]),
            profile_type='employee',
            is_teacher=is_teacher_flag,
            unity_id=random.choice(unity_ids),
            force_password_change=False,
            role_id=employee_role.id
        )
        e.set_password('employee123')
        db.session.add(e)
        if is_teacher_flag:
            teachers_list.append(e)
        users_created += 1

    db.session.flush()

    for i in range(1, 81):
        fname = random.choice(first_names)
        lname = random.choice(last_names)
        t = User(
            username=f"teacher{i}",
            email=f"teacher{i}@school.edu",
            full_name=f"{fname} {lname}",
            role='room',
            department=random.choice(["Science", "Math", "History", "Arts", "Languages", "Physical Ed"]),
            profile_type='teacher',
            unity_id=random.choice(unity_ids),
            registration=f"REG-{i:04d}",
            force_password_change=False,
            role_id=teacher_role.id
        )
        t.set_password('teacher123')
        db.session.add(t)
        teachers_list.append(t)
        users_created += 1

    db.session.flush()
    click.echo(f"   ✅ {users_created} usuários criados.")

    # 2. Categorias
    categories = [
        RoomCategory(name="Sala de Aula", code="classroom", abbr="SA"),
        RoomCategory(name="Auditório", code="auditorium", abbr="AU"),
        RoomCategory(name="Cozinha", code="kitchen", abbr="CO"),
        RoomCategory(name="Laboratório de Informática", code="computer_lab", abbr="LI"),
        RoomCategory(name="Laboratório de Saúde", code="health_lab", abbr="LS")
    ]
    db.session.add_all(categories)
    db.session.flush()

    cat_classroom = RoomCategory.query.filter_by(code='classroom').first()
    cat_aud = RoomCategory.query.filter_by(code='auditorium').first()
    cat_kitchen = RoomCategory.query.filter_by(code='kitchen').first()
    cat_comp = RoomCategory.query.filter_by(code='computer_lab').first()
    cat_health = RoomCategory.query.filter_by(code='health_lab').first()

    # 3. Salas
    room_data = [
        {"name": "Auditório Principal", "category_id": cat_aud.id, "capacity": 150, "floor": "1º Andar", "computer_count": 0, "room_number": "101"},
        {"name": "Cozinha Experimental A", "category_id": cat_kitchen.id, "capacity": 15, "floor": "1º Andar", "computer_count": 0, "room_number": "102"},
        {"name": "Cozinha Experimental B", "category_id": cat_kitchen.id, "capacity": 15, "floor": "1º Andar", "computer_count": 0, "room_number": "103"},
        {"name": "Sala de Aula 104", "category_id": cat_classroom.id, "capacity": 30, "floor": "1º Andar", "computer_count": 0, "room_number": "104"},
        {"name": "Lab de Informática A", "category_id": cat_comp.id, "capacity": 40, "floor": "1º Andar", "computer_count": 40, "room_number": "105"},
        {"name": "Lab de Informática B", "category_id": cat_comp.id, "capacity": 40, "floor": "1º Andar", "computer_count": 40, "room_number": "106"},
        {"name": "Lab de Informática C", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "201"},
        {"name": "Lab de Informática D", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "202"},
        {"name": "Lab de Informática E", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "203"},
        {"name": "Lab de Informática F", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "204"},
        {"name": "Lab de Informática G", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "205"},
        {"name": "Sala de Aula 206", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "206"},
        {"name": "Sala de Aula 207", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "207"},
        {"name": "Sala de Aula 208", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "208"},
        {"name": "Sala de Aula 209", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "209"},
        {"name": "Sala de Aula 210", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "210"},
        {"name": "Sala de Aula 211", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "211"},
        {"name": "Sala de Aula 212", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "212"},
        {"name": "Sala de Aula 213", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "213"},
        {"name": "Lab de Saúde A", "category_id": cat_health.id, "capacity": 20, "floor": "3º Andar", "computer_count": 0, "room_number": "301"},
        {"name": "Lab de Saúde B", "category_id": cat_health.id, "capacity": 20, "floor": "3º Andar", "computer_count": 0, "room_number": "302"},
        {"name": "Lab de Saúde C", "category_id": cat_health.id, "capacity": 20, "floor": "3º Andar", "computer_count": 0, "room_number": "303"},
        {"name": "Sala de Aula 304", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "304"},
        {"name": "Sala de Aula 305", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "305"},
        {"name": "Sala de Aula 306", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "306"},
        {"name": "Sala de Aula 307", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "307"},
        {"name": "Sala de Aula 308", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "308"},
        {"name": "Sala de Aula 309", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "309"},
    ]

    rooms = []
    for r_data in room_data:
        cat_obj = RoomCategory.query.get(r_data['category_id'])
        code = f"{cat_obj.abbr}{r_data['room_number']}" if cat_obj.abbr else r_data['room_number']
        room = Classroom(
            code=code, name=r_data["name"], category_id=r_data["category_id"],
            capacity=r_data["capacity"], floor=r_data["floor"], building="Bloco Principal",
            room_number=r_data["room_number"], computer_count=r_data["computer_count"], is_active=True,
            unity_id=main_unity.id
        )
        db.session.add(room)
        rooms.append(room)

    db.session.flush()
    click.echo(f"   ✅ {len(rooms)} salas criadas.")

    # 4. Cursos e Disciplinas
    courses_list = []
    for i in range(1, 51):
        c = Course(name=f"Curso {i}", code=f"C{i:03d}", is_active=True, unity_id=main_unity.id)
        db.session.add(c)
        courses_list.append(c)

    db.session.flush()

    subjects_list = []
    for i in range(1, 51):
        random_course = random.choice(courses_list)
        s = Subject(name=f"Disciplina {i}", code=f"S{i:03d}", course_id=random_course.id, is_active=True, unity_id=main_unity.id)
        db.session.add(s)
        subjects_list.append(s)

    db.session.flush()
    click.echo("   ✅ 50 cursos e 50 disciplinas criados.")

    # 5. Reservas
    all_bookers = teachers_list + [admin]
    time_slots = [
        (time(8, 0), time(10, 0)), (time(10, 0), time(12, 0)),
        (time(13, 0), time(15, 0)), (time(15, 0), time(17, 0)),
        (time(18, 0), time(20, 0)), (time(19, 0), time(21, 0))
    ]

    for i in range(1, 21):
        if i <= 5:
            res_date = date.today()
            if res_date.weekday() == 6:
                res_date += timedelta(days=1)
            now_hour = datetime.now().hour
            start_hour = min(now_hour, 19)
            end_hour = min(start_hour + 1, 20)
            start = time(start_hour, 0)
            end = time(end_hour, 0)
        else:
            res_date = date.today() + timedelta(days=random.randint(1, 30))
            if res_date.weekday() == 6:
                res_date += timedelta(days=1)
            start, end = random.choice(time_slots)

        room = random.choice(rooms)
        booker = random.choice(all_bookers)
        teacher = random.choice(teachers_list) if random.random() > 0.3 else None
        course = random.choice(courses_list)
        subject = random.choice(subjects_list)
        status = 'pending' if i in [10, 15] else 'approved'

        res = Reservation(
            user_id=booker.id, classroom_id=room.id,
            teacher_id=teacher.id if teacher else None,
            course_id=course.id, subject_id=subject.id,
            unity_id=room.unity_id,
            title=f"Aula/Evento {i}",
            description="Aula agendada para alunos.",
            date=res_date, start_time=start, end_time=end, status=status
        )
        db.session.add(res)

    click.echo("   ✅ 20 reservas criadas.")

    # 6. Pagamentos
    sample_teachers = teachers_list[:3]
    for i, teacher in enumerate(sample_teachers):
        base_pay = TeacherBasePay(
            teacher_id=teacher.id,
            course_id=courses_list[i].id,
            unity_id=teacher.unity_id,
            month_start='2024-02',
            month_end='2024-07',
            budget_code=95000,
            complement='Contrato Inicial',
            weekly_workload=20,
            accountable_id=admin.id
        )
        db.session.add(base_pay)

    click.echo("   ✅ Lançamentos de pagamento base criados.")
