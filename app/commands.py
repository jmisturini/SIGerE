"""Comandos CLI customizados para o Flask."""
import json
import os

import click
from flask.cli import with_appcontext
from app.extensions import db
from app.models import (
    User, Classroom, Reservation, Course, Subject,
    TeacherOvertimePay, Role, Permission, RoomCategory, Unity
)
from datetime import datetime, date, time, timedelta, timezone
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
    # Reservada ao super-administrador: a alternância da unidade ativa só
    # responde ao '*' (SWITCHABLE_PERMISSIONS em app.unity_context) — manter
    # esta permissão atribuída não dá o poder de trocar de unidade.
    ('unity:switch', 'unity', 'switch',
     'Alternar a unidade ativa de operação (reservada ao super-admin)'),
    ('unity:modules', 'unity', 'modules', 'Ativar/desativar módulos da unidade (Cozinha, Financeiro)'),
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
    # Tipos de curso (catálogo do lançamento de Hora Extra)
    ('course_type:read', 'course_type', 'read', 'Acessar o cadastro de Tipos de Curso'),
    ('course_type:create', 'course_type', 'create', 'Criar Tipos de Curso'),
    ('course_type:edit', 'course_type', 'edit', 'Editar Tipos de Curso'),
    ('course_type:toggle', 'course_type', 'toggle', 'Ativar/desativar Tipos de Curso'),
    ('holiday:read', 'holiday', 'read', 'Visualizar feriados'),
    ('holiday:create', 'holiday', 'create', 'Criar feriados'),
    ('holiday:edit', 'holiday', 'edit', 'Editar feriados'),
    ('holiday:delete', 'holiday', 'delete', 'Excluir feriados'),
    ('holiday:import', 'holiday', 'import', 'Importar feriados da API'),
    ('payment:read', 'payment', 'read', 'Ver lançamentos de pagamento extra (hora extra)'),
    ('payment:read_own', 'payment', 'read_own', 'Ver os próprios lançamentos de pagamento extra'),
    ('payment:create', 'payment', 'create', 'Criar lançamentos de pagamento extra (hora extra)'),
    ('payment:edit', 'payment', 'edit', 'Editar lançamentos de pagamento extra (hora extra)'),
    ('payment:delete', 'payment', 'delete', 'Excluir lançamentos de pagamento extra (hora extra)'),
    ('payment:export', 'payment', 'export', 'Exportar a planilha de pagamento extra (hora extra)'),
    ('payment:close_month', 'payment', 'close_month',
     'Fechar os lançamentos do mês de Hora Extra (bloqueia edições e baixa a planilha final)'),
    # Módulo Vale Alimentação - Professores (RH): lançamento simples de dias
    # trabalhados, separado do pagamento extra de hora
    ('meal:read', 'meal', 'read', 'Acessar o Vale Alimentação - Professores (lançamentos e listagem)'),
    ('meal:create', 'meal', 'create', 'Lançar dias trabalhados no Vale Alimentação - Professores'),
    ('meal:edit', 'meal', 'edit', 'Editar lançamentos do Vale Alimentação - Professores'),
    ('meal:delete', 'meal', 'delete', 'Excluir lançamentos do Vale Alimentação - Professores'),
    # Módulo Vale-Transporte (área do Financeiro com papéis próprios, separada
    # do pagamento extra: um papel pode liberar só uma das duas)
    ('vt:read', 'vt', 'read', 'Acessar o Vale-Transporte (pedidos e relatório)'),
    ('vt:edit', 'vt', 'edit', 'Corrigir pedidos de VT recebidos'),
    ('vt:delete', 'vt', 'delete', 'Excluir pedidos de VT'),
    ('vt:export', 'vt', 'export', 'Exportar a planilha de pagamento do Vale-Transporte'),
    ('vt:empresas', 'vt', 'empresas', 'Gerenciar empresas de ônibus e tarifas do pedido de VT'),
    ('vt:config', 'vt', 'config', 'Configurar o pedido público de VT (vales base e data de fechamento)'),
    # Módulo de Cozinha (fichas técnicas, preparações e compras)
    ('kitchen:read', 'kitchen', 'read', 'Acessar o módulo de Cozinha (fichas técnicas, preparações e compras)'),
    ('kitchen:sheet_create', 'kitchen', 'sheet_create', 'Enviar e salvar fichas técnicas (DOCX)'),
    ('kitchen:sheet_delete', 'kitchen', 'sheet_delete', 'Excluir fichas técnicas e preparações'),
    ('kitchen:shopping_export', 'kitchen', 'shopping_export', 'Gerar e exportar a requisição de compra'),
    # Módulo de Notificações de atividades próximas
    ('notification:manage', 'notification', 'manage',
     'Configurar o aviso de sobrecarga de professor da unidade (grupos destinatários)'),
    ('notification:groups', 'notification', 'groups',
     'Gerenciar os grupos personalizados de notificação da unidade'),
    ('system:dashboard', 'system', 'dashboard', 'Acessar painel administrativo'),
    ('system:export', 'system', 'export', 'Exportar dados diversos'),
    # Módulo API (integrações externas de leitura de reservas)
    ('api:manage', 'api', 'manage', 'Gerenciar tokens de acesso à API de reservas'),
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
            'unity:read', 'unity:create', 'unity:edit', 'unity:toggle',
            'unity:modules',
            'room:read', 'room:create', 'room:edit', 'room:toggle',
            'course:read', 'course:create', 'course:edit', 'course:toggle',
            'course_type:read', 'course_type:create', 'course_type:edit', 'course_type:toggle',
            'holiday:read', 'holiday:create', 'holiday:edit', 'holiday:delete', 'holiday:import',
            'reservation:read_all', 'reservation:edit_all', 'reservation:delete_all',
            'reservation:approve', 'reservation:cancel_all',
            'system:dashboard', 'system:export',
            'api:manage',
            'role:read', 'role:create', 'role:edit', 'role:delete',
            'kitchen:read', 'kitchen:sheet_create', 'kitchen:sheet_delete', 'kitchen:shopping_export',
            'vt:empresas', 'vt:config',
            'notification:manage', 'notification:groups'
        ]
    },
    'coordinator': {
        'label': 'Analista',
        'is_system': False,
        'permissions': [
            'course:read',
            'course_type:read',
            'reservation:approve', 'reservation:cancel_own',
            'reservation:create', 'reservation:edit_own', 'reservation:read_own',
            'system:export',
            'room:read',
            'payment:create', 'payment:edit', 'payment:read_own',
            'meal:read', 'meal:create', 'meal:edit'
        ]
    },
    'room_manager': {
        'label': 'Gestor',
        'is_system': False,
        'permissions': [
            'course:read', 'course:create', 'course:edit', 'course:toggle',
            'course_type:read', 'course_type:create', 'course_type:edit', 'course_type:toggle',
            'reservation:read_all', 'reservation:read_own',
            'reservation:create', 'reservation:edit_all', 'reservation:edit_own',
            'reservation:delete_all', 'reservation:cancel_own', 'reservation:cancel_all',
            'reservation:approve',
            'payment:read', 'payment:read_own', 'payment:create',
            'payment:edit', 'payment:delete', 'payment:export', 'payment:close_month',
            'meal:read', 'meal:create', 'meal:edit', 'meal:delete',
            'room:read', 'room:create', 'room:edit', 'room:toggle',
            'system:export'
        ]
    },
    'teacher': {
        'label': 'Professor',
        'is_system': False,
        'permissions': [
            'course:read',
            'reservation:create', 'reservation:cancel_own',
            'reservation:edit_own', 'reservation:read_own',
            'system:export',
            'room:read'
        ]
    },
    'employee': {
        'label': 'Assistente',
        'is_system': False,
        'permissions': [
            'course:read',
            'reservation:cancel_own', 'reservation:create',
            'reservation:edit_own', 'reservation:read_own',
            'system:export',
            'room:read'
        ]
    },
    # Papel adicional (add-on), não um cargo: concedido além do papel principal
    # na tela do usuário (ex.: Professor + Módulo Cozinha para professores de
    # gastronomia). A permissão efetiva é a união dos dois papéis.
    'kitchen': {
        'label': 'Módulo Cozinha',
        'is_system': False,
        'permissions': [
            'kitchen:read', 'kitchen:sheet_create', 'kitchen:shopping_export'
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
    updated_perms, retired_perms = 0, 0
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

        # Descrições/módulo/ação que mudaram no código: bancos já existentes
        # ficariam com o texto desatualizado (ex.: vt:read ainda citando a
        # importação que saiu do ar).
        for code, module, action, desc in PERMISSION_DATA:
            p = perm_objects[code]
            if (p.description != desc or p.module != module
                    or p.action != action):
                p.module = module
                p.action = action
                p.description = desc
                updated_perms += 1
        db.session.flush()

        # Aposenta permissões removidas do código (ex.: vt:create da
        # importação do Pedido de Compra, que saiu do ar): os vínculos com
        # papéis caem junto, por cascade na tabela de junção. Seguro porque
        # toda permissão do banco vem de PERMISSION_DATA.
        codigos_vigentes = {code for code, _, _, _ in PERMISSION_DATA}
        for code, p in list(perm_objects.items()):
            if code not in codigos_vigentes:
                db.session.delete(p)
                retired_perms += 1
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
            click.echo(f"   Permissões atualizadas: {updated_perms}")
            click.echo(f"   Permissões aposentadas: {retired_perms}")
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


def _seed_admin(password='admin123'):
    """Cria apenas o usuário administrador."""
    click.echo("   Criando usuário administrador...")

    super_admin_role = Role.query.filter_by(name='super_admin').first()

    admin = User(
        email='admin@school.edu',
        full_name='Administrador do Sistema', role='admin',
        department='Administration', profile_type='employee',
        force_password_change=False,
        role_id=super_admin_role.id
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.flush()
    click.echo("   ✅ Administrador criado.")


@click.command('seed-admin')
@with_appcontext
def seed_admin_command():
    """Cria apenas a conta do administrador, solicitando uma senha.

    Alternativa ao `seed` para implantações reais: cria as permissões/papéis
    e o usuário 'admin' — sem nenhum dado de demonstração — com a senha
    definida interativamente (mínimo de 8 caracteres, digitação oculta).
    """
    if User.query.filter_by(email='admin@school.edu').first() is not None:
        click.echo(click.style(
            "⚠️  A conta 'admin' já existe. Nada foi alterado.",
            fg="yellow"
        ))
        return

    click.echo(click.style("🌱 Criando a conta do administrador...", fg="green", bold=True))

    try:
        while True:
            password = click.prompt(
                click.style("Digite a senha do administrador", fg="yellow"),
                hide_input=True,
                confirmation_prompt=click.style("Confirme a senha", fg="yellow"),
            )
            if len(password) >= 8:
                break
            click.echo(click.style(
                "❌ A senha deve ter pelo menos 8 caracteres. Tente novamente.",
                fg="red"
            ))

        _seed_permissions()
        _seed_admin(password=password)
        db.session.commit()
        click.echo(click.style(
            "✅ Administrador criado com sucesso! Faça login com o e-mail "
            "'admin@school.edu' e a senha que você definiu.", fg="green", bold=True
        ))
    except Exception as exc:
        db.session.rollback()
        click.echo(click.style(
            f"❌ Falha ao criar o administrador.\n   Erro: {exc}",
            fg="red", bold=True
        ))
        raise click.ClickException(str(exc))


# Caminho padrão do JSON de unidades extraído do portal do Senac SC.
UNIDADES_JSON_PADRAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'docs', 'unidades-senac-sc.json'
)


def _seed_unidades(json_path):
    """Upsert idempotente das unidades a partir do JSON (retorna contadores).

    Casa cada registro pelo `code` e, na ausência, pelo `name`. Quando o JSON
    traz `is_active` em `cadastro_sugerido`, ele manda na criação e na
    atualização (ex.: todas as unidades com false para depurar/demonstrar com
    o módulo desligado); sem o campo, criação usa True e a atualização não
    toca em `is_active` (uma unidade desativada de propósito não é reativada).
    As coordenadas de clima (weather_latitude/longitude, usadas pela detecção
    da unidade mais próxima no portal público) são aplicadas apenas quando o
    JSON as traz — coordenada ausente não apaga a já cadastrada.
    """
    with open(json_path, encoding='utf-8') as fh:
        data = json.load(fh)

    criadas, atualizadas, ignorados = 0, 0, []
    for registro in data.get('unidades', []):
        sugestao = registro.get('cadastro_sugerido')
        if not sugestao:
            ignorados.append(registro.get('nome', '(sem nome)'))
            continue

        unity = Unity.query.filter_by(code=sugestao['code']).first()
        if not unity:
            unity = Unity.query.filter_by(name=sugestao['name']).first()
        if not unity:
            unity = Unity(name=sugestao['name'], code=sugestao['code'],
                          is_active=sugestao.get('is_active', True))
            db.session.add(unity)
            criadas += 1
        else:
            atualizadas += 1

        unity.name = sugestao['name']
        unity.code = sugestao['code']
        unity.address = sugestao.get('address')
        unity.phone = sugestao.get('phone')
        unity.weather_city = sugestao.get('weather_city')
        if sugestao.get('weather_latitude') is not None:
            unity.weather_latitude = sugestao['weather_latitude']
        if sugestao.get('weather_longitude') is not None:
            unity.weather_longitude = sugestao['weather_longitude']
        if 'is_active' in sugestao:
            unity.is_active = sugestao['is_active']

    return criadas, atualizadas, ignorados


@click.command('seed-unidades')
@click.option('--file', 'json_path', default=UNIDADES_JSON_PADRAO,
              metavar='CAMINHO',
              help='JSON de origem (padrão: docs/unidades-senac-sc.json).')
@with_appcontext
def seed_unidades_command(json_path):
    """Cadastra as unidades do Senac SC extraídas do portal.

    Lê docs/unidades-senac-sc.json e cria as unidades ausentes, atualizando
    endereço/telefone das existentes. Registros sem `cadastro_sugerido`
    (ex.: Direção Regional) são ignorados. Idempotente: pode ser executado
    mais de uma vez sem duplicar.

    Uso: flask --app run seed-unidades
    """
    if not os.path.exists(json_path):
        raise click.ClickException(f"Arquivo não encontrado: {json_path}")

    click.echo(click.style("🌱 Cadastrando unidades do Senac SC...", fg="green", bold=True))
    try:
        criadas, atualizadas, ignorados = _seed_unidades(json_path)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        click.echo(click.style(
            f"❌ Falha ao cadastrar as unidades. Alterações revertidas.\n   Erro: {exc}",
            fg="red", bold=True
        ))
        raise click.ClickException(str(exc))

    click.echo(click.style(
        f"✅ Unidades cadastradas! Criadas: {criadas} | Atualizadas: {atualizadas}",
        fg="green", bold=True
    ))
    if ignorados:
        click.echo(click.style(
            "ℹ️  Ignorados (sem cadastro_sugerido no JSON): " + ", ".join(ignorados),
            fg="yellow"
        ))


def _seed_demo_data():
    """Popula dados de demonstração (usuários, salas, cursos, reservas, etc.)."""
    click.echo("   Populando dados de demonstração...")

    teacher_role = Role.query.filter_by(name='teacher').first()
    employee_role = Role.query.filter_by(name='employee').first()
    admin = User.query.filter_by(email='admin@school.edu').first()

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
            email=f"employee{i}@school.edu",
            full_name=f"{fname} {lname}",
            role='room' if is_teacher_flag else 'viewer',
            sector="Administration",
            function=random.choice(["Coordinator", "Secretary", "Technician", "Director"]),
            profile_type='employee',
            is_teacher=is_teacher_flag,
            unities=[random.choice(unities)],
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
            email=f"teacher{i}@school.edu",
            full_name=f"{fname} {lname}",
            role='room',
            department=random.choice(["Science", "Math", "History", "Arts", "Languages", "Physical Ed"]),
            profile_type='teacher',
            unities=[random.choice(unities)],
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

    # 2. Categorias — cor/ícone alimentam o totem, que se monta a partir
    #    destes cadastros (nenhuma categoria é fixa no código).
    categories = [
        RoomCategory(name="Sala de Aula", code="classroom", abbr="SA",
                     color="#0d6efd", icon="bi-door-closed"),
        RoomCategory(name="Auditório", code="auditorium", abbr="AU",
                     color="#004b8d", icon="bi-buildings",
                     totem_window=RoomCategory.TOTEM_WINDOW_WEEK),
        RoomCategory(name="Cozinha", code="kitchen", abbr="CO",
                     color="#f0ad4e", icon="bi-cup-hot"),
        RoomCategory(name="Laboratório de Informática", code="computer_lab", abbr="LI",
                     color="#0dcaf0", icon="bi-pc-display"),
        RoomCategory(name="Laboratório de Saúde", code="health_lab", abbr="LS",
                     color="#dc3545", icon="bi-heart-pulse"),
        RoomCategory(name="Quadra de Esportes", code="sports_court", abbr="QE",
                     color="#198754", icon="bi-volleyball")
    ]
    db.session.add_all(categories)
    db.session.flush()

    cat_classroom = RoomCategory.query.filter_by(code='classroom').first()
    cat_aud = RoomCategory.query.filter_by(code='auditorium').first()
    cat_kitchen = RoomCategory.query.filter_by(code='kitchen').first()
    cat_comp = RoomCategory.query.filter_by(code='computer_lab').first()
    cat_health = RoomCategory.query.filter_by(code='health_lab').first()
    cat_sports = RoomCategory.query.filter_by(code='sports_court').first()

    # 3. Salas
    room_data = [
        {"name": "Auditório Principal", "category_id": cat_aud.id, "capacity": 150, "floor": "1º Andar", "computer_count": 0, "room_number": "101"},
        {"name": "Quadra Poliesportiva", "category_id": cat_sports.id, "capacity": 100, "floor": "Térreo", "computer_count": 0, "room_number": "001"},
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

    # 6. Pagamentos (hora extra)
    sample_teachers = teachers_list[:3]
    for i, teacher in enumerate(sample_teachers):
        overtime = TeacherOvertimePay(
            teacher_id=teacher.id,
            unity_id=teacher.primary_unity_id,
            teaching_level=random.choice(['Técnico', 'Superior']),
            weekly_workload=random.choice([2, 4, 6]),
            hourly_value=random.choice([15.50, 22.30, 30.00]),
            budget_code='950001234',
            shift=random.choice(['Matutino', 'Vespertino', 'Noturno']),
            multiple_dates=f"{10 + i}, {17 + i}",
            justification='Substituicao de aula',
            month_base='2024-08',
            accountable_id=admin.id
        )
        db.session.add(overtime)

    click.echo("   ✅ Lançamentos de hora extra criados.")


@click.command('import-legacy')
@click.option('--dump', 'dump_path', required=True,
              type=click.Path(exists=True, dir_okay=False),
              help='Caminho do dump .sql (phpMyAdmin) do banco MySQL do sistema legado.')
@click.option('--force', is_flag=True,
              help='Importa mesmo se o banco de destino já tiver dados.')
@with_appcontext
def import_legacy_command(dump_path, force):
    """Importa os dados do sistema legado (Django/MySQL) a partir do dump .sql.

    Espera um banco recém-criado por `flask db upgrade`. Lê o arquivo .sql
    diretamente (não precisa de servidor MySQL). Usuários entram com a senha
    antiga (quando o hash legado é aproveitável) e são obrigados a trocá-la.

    Uso: flask --app run import-legacy --dump caminho/sigere_active.sql
    """
    from app.legacy_import import import_legacy

    click.echo("Importando dados do sistema legado (pode levar alguns minutos)...")
    try:
        counts = import_legacy(dump_path, force=force)
    except RuntimeError as e:
        click.echo(click.style(f"❌ {e}", fg="red"))
        raise SystemExit(1)
    for line in counts.get("relatorio", []):
        click.echo("  • " + line)
    click.echo(click.style("✅ Importação concluída.", fg="green"))
    click.echo("Todos os usuários importados iniciarão com troca de senha obrigatória.")


@click.command('notify-scan')
@with_appcontext
@click.option('--dry-run', is_flag=True,
              help='Mostra o que seria criado sem gravar nada.')
def notify_scan_command(dry_run):
    """Varre as reservas próximas e cria as notificações dos destinatários.

    Cria os avisos das reservas aprovadas com notificações ativadas (seção
    Notificações do formulário de reserva): no marco de antecedência mais
    iminente já vencido (24h ou 1h antes do início), cada destinatário
    configurado na própria reserva — usuários individuais e grupos — recebe o
    aviso, salvo quem silenciou as notificações no perfil. Marcos anteriores
    ficam absorvidos, para não repetir avisos com o mesmo conteúdo.
    Idempotente: a constraint de unicidade impede duplicatas, então pode rodar
    com segurança a cada 15 minutos.

    Uso: flask --app run notify-scan [--dry-run]
    """
    from app.services.notifications import varrer_reservas, varrer_pendentes

    stats = varrer_reservas(dry_run=dry_run)
    rotulo = 'seriam criadas' if dry_run else 'criadas'
    stats_pend = varrer_pendentes(dry_run=dry_run)
    click.echo(f"Varredura concluída{' (dry-run)' if dry_run else ''}:")
    click.echo(f"  Reservas avaliadas: {stats['reservas']}")
    click.echo(f"  Notificações {rotulo}: {stats['criadas']}")
    click.echo(f"  Já existentes (sem duplicar): {stats['existentes']}")
    click.echo(f"  Pendências avaliadas: {stats_pend['reservas']}")
    click.echo(f"  Lembretes de aprovação {rotulo}: {stats_pend['criadas']}")
    if dry_run and (stats['criadas'] or stats_pend['criadas']):
        click.echo("Rode sem --dry-run para gravar.")


@click.command('notify-email')
@with_appcontext
@click.option('--dry-run', is_flag=True,
              help='Mostra o que seria enviado sem enviar nada.')
@click.option('--limite', default=200, show_default=True, type=int,
              help='Máximo de notificações processadas por rodada.')
def notify_email_command(dry_run, limite):
    """Envia por e-mail as notificações ainda pendentes (fila pelo sent_at).

    Espelho por e-mail de todas as notificações do sino: cada uma nasce com
    sent_at nulo e este comando envia e carimba — falha de SMTP continua
    pendente para a próxima rodada. Exige MAIL_SMTP_HOST e MAIL_FROM
    configurados; sem eles não faz nada. O usuário desliga o espelho no
    perfil (UserNotificationPref.email_enabled).

    Uso: flask --app run notify-email [--dry-run] [--limite N]
    """
    from app.services.mailer import drenar_fila_email

    try:
        stats = drenar_fila_email(limite=limite, dry_run=dry_run)
    except Exception as e:
        # Erro de conexão/autenticação SMTP: a rodada inteira falhou, nada
        # foi carimbado — o timer tenta de novo no próximo ciclo.
        click.echo(click.style(f"❌ Falha de SMTP: {e}", fg="red"))
        raise SystemExit(1)
    if stats.get('puladas') == -1:
        click.echo("Envio por e-mail desativado: defina MAIL_SMTP_HOST e "
                   "MAIL_FROM para ativar.")
        return
    rotulo = 'seriam enviados' if dry_run else 'enviados'
    click.echo(f"Dreno de e-mail concluído{' (dry-run)' if dry_run else ''}:")
    click.echo(f"  Notificações pendentes na fila: {stats['pendentes']}")
    click.echo(f"  E-mails {rotulo}: {stats['emails']} "
               f"(cobrindo {stats['notificacoes']} notificação(ões))")
    click.echo(f"  Falhas (contam tentativa, tentam de novo): {stats['falhas']}")
    click.echo(f"  Puladas (opt-out/inativas): {stats['puladas']}")
    if stats['excedidas']:
        click.echo(click.style(
            f"  ⚠ {stats['excedidas']} notificação(ões) passaram do limite de "
            f"tentativas e saíram da fila (verifique o SMTP).", fg="yellow"))
    if dry_run and stats['emails']:
        click.echo("Rode sem --dry-run para enviar.")


@click.command('notify-cleanup')
@with_appcontext
@click.option('--dias-lidas', default=90, show_default=True, type=int,
              help='Apagar notificações lidas há mais de N dias.')
@click.option('--dias-passadas', default=30, show_default=True, type=int,
              help='Apagar notificações (lidas ou não) de reservas cuja data '
                   'foi há mais de N dias.')
@click.option('--dry-run', is_flag=True,
              help='Mostra o que seria apagado sem gravar nada.')
def notify_cleanup_command(dias_lidas, dias_passadas, dry_run):
    """Apaga notificações antigas para manter a base enxuta.

    Duas regras: notificações lidas há mais de --dias-lidas, e notificações
    de reservas cuja data foi há mais de --dias-passadas (lidas ou não —
    aviso de atividade passada não tem mais função). O aviso de exclusão
    (reservation_id nulo) só sai pela regra das lidas.

    Uso: flask --app run notify-cleanup [--dry-run] [--dias-lidas N]
         [--dias-passadas N]
    """
    from sqlalchemy import exists, select

    from app.models import Notification, Reservation

    corte_lidas = datetime.now(timezone.utc) - timedelta(days=dias_lidas)
    corte_reservas = date.today() - timedelta(days=dias_passadas)

    # EXISTS correlacionado: mantém o DELETE em tabela única (o JOIN em
    # DELETE não é portátil — SQLite/PostgreSQL divergem na sintaxe).
    de_reserva_passada = exists(
        select(1).where(Notification.reservation_id == Reservation.id,
                        Reservation.date < corte_reservas))

    def _apagar(criterio):
        if dry_run:
            return Notification.query.filter(criterio).count()
        return (Notification.query.filter(criterio)
                .delete(synchronize_session=False))

    qtde_lidas = _apagar(Notification.read_at.isnot(None)
                         & (Notification.read_at < corte_lidas))
    qtde_passadas = _apagar(de_reserva_passada)
    if not dry_run:
        db.session.commit()

    rotulo = 'seriam apagadas' if dry_run else 'apagadas'
    click.echo(f"Limpeza de notificações concluída{' (dry-run)' if dry_run else ''}:")
    click.echo(f"  Lidas há mais de {dias_lidas} dias {rotulo}: {qtde_lidas}")
    click.echo(f"  De reservas passadas há mais de {dias_passadas} dias "
               f"{rotulo}: {qtde_passadas}")
