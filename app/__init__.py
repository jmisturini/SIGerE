from flask import Flask, render_template, redirect, url_for, request, flash
from app.config import Config
from app.extensions import db, login_manager, csrf
from datetime import datetime
import os
import sys

# Valor de desenvolvimento — em produção (FLASK_DEBUG != true) a app se recusa
# a iniciar sem um SECRET_KEY real, pois com ele é possível forjar cookies de sessão.
DEV_SECRET_KEY = 'dev-secret-key-change-in-production'

def create_app(config_class=Config):
    """Factory function to create and configure the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'

    # Fail-fast de segurança: sem SECRET_KEY forte, sessões podem ser forjadas.
    if app.config['SECRET_KEY'] == DEV_SECRET_KEY and not debug_mode:
        raise RuntimeError(
            'SECRET_KEY não configurada: defina a variável de ambiente SECRET_KEY '
            'com um valor forte e único (ou rode com FLASK_DEBUG=true em desenvolvimento).'
        )

    # Endurecimento de cookies apenas fora do modo debug (produção assumed HTTPS):
    # Secure impede envio do cookie por HTTP puro; HttpOnly já é o padrão do Flask.
    # Atribuição direta: o Flask já predefine SESSION_COOKIE_SECURE=False, então
    # setdefault não teria efeito.
    if not debug_mode:
        app.config['SESSION_COOKIE_SECURE'] = True

    # Initialize Flask extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Register all Blueprints
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.classrooms import bp as classrooms_bp
    from app.blueprints.reservations import bp as reservations_bp
    from app.blueprints.admin import bp as admin_bp
    from app.blueprints.totem import bp as totem_bp
    from app.blueprints.schedule import bp as schedule_bp
    from app.blueprints.public import bp as public_bp
    from app.blueprints.payments import bp as payments_bp
    from app.blueprints.kitchen import bp as kitchen_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(classrooms_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(totem_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(kitchen_bp)

    # ── Register CLI commands ──
    from app.commands import seed_command, sync_permissions_command
    app.cli.add_command(seed_command)
    app.cli.add_command(sync_permissions_command)

    # Custom Error Handlers
    @app.errorhandler(403)
    def forbidden(_):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template('errors/500.html'), 500

    # CSRF rejeitado (token ausente/expirado — típico de sessão expirada):
    # mensagem amigável em vez de página "Bad Request" crua.
    from flask_wtf.csrf import CSRFError
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        flash('Sua sessão expirou ou o formulário já não é válido. '
              'Recarregue a página e tente novamente.', 'warning')
        return redirect(request.referrer or url_for('main.index'))

    # Context processor to inject current datetime into all templates
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    # Multi-unidade: injeta a unidade ativa e o seletor de unidades nos templates
    @app.context_processor
    def inject_unity_context():
        from app.unity_context import (current_unity, switchable_unities,
                                   can_switch_unity)
        return {
            'current_unity': current_unity(),
            'switchable_unities': switchable_unities(),
            'can_switch_unity': can_switch_unity(),
        }

    # Security Hook: Force password change on first login or admin reset
    @app.before_request
    def require_password_change():
        from flask_login import current_user
        if current_user.is_authenticated and current_user.force_password_change:
            allowed_endpoints = ['auth.change_password', 'auth.logout', 'static']
            # Guard against None endpoint (e.g. unresolved routes before 404 handler fires)
            if request.endpoint and request.endpoint not in allowed_endpoints:
                return redirect(url_for('auth.change_password'))

    # Create database tables only (NO automatic seeding)
    with app.app_context():
        db.create_all()
        _ensure_schema_upgrades()

    return app


def _ensure_schema_upgrades():
    """Migrações leves e idempotentes para bancos já existentes.

    O db.create_all() cria apenas tabelas novas — não adiciona colunas em
    tabelas que já existem. Bancos criados antes de novas versões precisam
    das colunas adicionadas via ALTER TABLE.

    Multi-unidade: cria a tabela `unities`, adiciona `unity_id` nas tabelas
    de dados, migra o texto legado `users.unity` para o novo vínculo e
    reconstrói tabelas cuja constraint UNIQUE global virou (unity_id, coluna).
    """
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)

    def add_column_if_missing(table, ddl):
        if table in inspector.get_table_names():
            columns = [c['name'] for c in inspector.get_columns(table)]
            column = ddl.split()[0]
            if column not in columns:
                with db.engine.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {ddl}'))

    UNITY_TABLES = (
        'users', 'classrooms', 'reservations', 'courses', 'subjects', 'holidays',
        'teacher_base_pay', 'teacher_additive_payment', 'teacher_overtime_pay',
    )
    for table in UNITY_TABLES:
        add_column_if_missing(table, 'unity_id INTEGER')

    # Cozinha: ingredientes desativáveis (não aparecem na requisição de compra)
    add_column_if_missing('kitchen_recipe_ingredients', 'is_active BOOLEAN DEFAULT 1')

    _migrate_to_unities(inspector)
    inspector = inspect(db.engine)  # reflete as colunas/tabelas novas
    _rebuild_unity_unique_constraints(inspector)

    # Garante permissões/papéis novos (ex: unity:*) em bancos já existentes
    from app.commands import sync_permissions_impl
    sync_permissions_impl(verbose=False)


def _migrate_to_unities(inspector):
    """Cria unidades iniciais e preenche unity_id nos registros existentes.

    - Cria uma unidade para cada valor distinto do texto legado users.unity;
    - Garante ao menos uma unidade ativa ("Unidade Principal");
    - Preenche unity_id NULL com a unidade padrão (a primeira criada);
    - Usuários com o texto legado recebem a unidade correspondente.
    """
    from sqlalchemy import text
    from app.models import Unity, db

    if 'unities' not in inspector.get_table_names():
        return  # banco novo será criado pelo create_all com o schema atual

    if Unity.query.count() > 0:
        return  # já migrado

    # 1. Unidades a partir do texto legado em users.unity (coluna pode não
    #    existir em bancos criados já no esquema novo)
    legacy_values = []
    user_columns = [c['name'] for c in inspector.get_columns('users')]
    if 'unity' in user_columns:
        rows = db.session.execute(text(
            "SELECT DISTINCT unity FROM users WHERE unity IS NOT NULL AND unity != ''"
        )).fetchall()
        legacy_values = sorted({r[0].strip() for r in rows if r[0] and r[0].strip()})

    # Banco vazio (primeira execução): nada a migrar — o seed cria as unidades.
    existing_tables = [t for t in inspector.get_table_names()]
    has_data = False
    for table in ('users', 'classrooms', 'reservations', 'courses'):
        if table in existing_tables:
            count = db.session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            if count:
                has_data = True
                break
    if not has_data and not legacy_values:
        return

    # 2. Unidades a partir do texto legado
    legacy_map = {}
    for name in legacy_values:
        unity = Unity(name=name, code=_generate_unity_code(name), is_active=True)
        db.session.add(unity)
        db.session.flush()
        legacy_map[name] = unity.id

    # 3. Unidade padrão quando nenhuma existir (migração de banco com dados)
    default_unity_id = next(iter(legacy_map.values()), None)
    if default_unity_id is None:
        default = Unity(name='Unidade Principal', code='UP', is_active=True)
        db.session.add(default)
        db.session.flush()
        default_unity_id = default.id

    # 4. Backfill de todas as tabelas de dados.
    # IMPORTANTE: usar db.session (mesma conexão da transação ORM) — abrir
    # db.engine.begin() aqui causaria "database is locked" no SQLite.
    for table in ('classrooms', 'reservations', 'courses', 'subjects', 'holidays',
                  'teacher_base_pay', 'teacher_additive_payment',
                  'teacher_overtime_pay'):
        if table in inspector.get_table_names():
            db.session.execute(text(
                f'UPDATE "{table}" SET unity_id = :uid WHERE unity_id IS NULL'
            ), {'uid': default_unity_id})
    if 'unity' in user_columns:
        for name, uid in legacy_map.items():
            db.session.execute(text(
                "UPDATE users SET unity_id = :uid WHERE unity_id IS NULL "
                "AND lower(trim(unity)) = lower(trim(:name))"
            ), {'uid': uid, 'name': name})
        # Usuários restantes sem unidade ficam globais (contas administrativas)

    db.session.commit()


def _generate_unity_code(name):
    """Gera um código curto e único a partir do nome da unidade."""
    from app.models import Unity
    initials = ''.join(word[0] for word in name.split() if word).upper()[:4] or 'U'
    code, suffix = initials, 1
    while Unity.query.filter_by(code=code).first() is not None:
        suffix += 1
        code = f'{initials}{suffix}'
    return code[:20]


def _rebuild_unity_unique_constraints(inspector):
    """Converte constraints UNIQUE globais em (unity_id, coluna) no SQLite.

    SQLite não altera constraints via ALTER TABLE — a tabela é reconstruída:
    renomeia a antiga, cria a nova a partir do modelo (já com a constraint
    composta), copia os dados e remove a antiga. Roda apenas quando ainda
    existe índice único de coluna única do esquema antigo. Idempotente.
    """
    from sqlalchemy.schema import CreateTable, CreateIndex
    from app.models import Classroom, Course, Subject, Holiday

    # (modelo, coluna que era única globalmente)
    targets = [
        (Classroom, 'code'), (Course, 'code'), (Subject, 'code'),
        (Holiday, 'date'),
    ]

    with db.engine.connect() as conn:
        conn = conn.execution_options(isolation_level='AUTOCOMMIT')
        # legacy_alter_table=ON: o RENAME não reescreve FKs de outras tabelas
        # que apontam para a renomeada — comportamento exigido para rebuild
        # de tabela sem quebrar as referências existentes.
        conn.exec_driver_sql('PRAGMA legacy_alter_table=ON')
        conn.exec_driver_sql('PRAGMA foreign_keys=OFF')
        for model, column in targets:
            table = model.__table__
            table_name = table.name
            if table_name not in inspector.get_table_names():
                continue
            if not _has_single_column_unique_index(conn, table_name, column):
                continue

            old_columns = [c['name'] for c in inspector.get_columns(table_name)]
            new_columns = set(table.columns.keys())
            common = [c for c in old_columns if c in new_columns]

            # Pula tabelas cujo esquema antigo não consegue alimentar colunas
            # NOT NULL do modelo atual (ex: bancos de iterações muito antigas).
            # Reconstruí-las exigiria migração de dados específica.
            required = {c.name for c in table.columns
                        if c.nullable is False and c.name not in common
                        and c.default is None and not c.primary_key}
            if required:
                print(f'⚠️  Migração multi-unidade: tabela "{table_name}" pulada — '
                      f'esquema antigo sem colunas {sorted(required)}. Recrie o banco '
                      f'(flask seed) ou migre manualmente.', file=sys.stderr)
                continue

            old_name = f'_old_{table_name}'
            col_list = ', '.join(f'"{c}"' for c in common)

            conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{old_name}"')
            conn.exec_driver_sql(f'ALTER TABLE "{table_name}" RENAME TO "{old_name}"')
            conn.execute(CreateTable(table))
            conn.exec_driver_sql(
                f'INSERT INTO "{table_name}" ({col_list}) '
                f'SELECT {col_list} FROM "{old_name}"'
            )
            conn.exec_driver_sql(f'DROP TABLE "{old_name}"')
            for index in table.indexes:
                conn.execute(CreateIndex(index, if_not_exists=True))


def _has_single_column_unique_index(conn, table_name, column):
    """Detecta índice único de UMA coluna (esquema pré-multi-unidade)."""
    rows = conn.exec_driver_sql(f'PRAGMA index_list("{table_name}")').fetchall()
    for row in rows:
        index_name, is_unique = row[1], row[2]
        if not is_unique:
            continue
        cols = conn.exec_driver_sql(f'PRAGMA index_info("{index_name}")').fetchall()
        if len(cols) == 1 and cols[0][2] == column:
            return True
    return False

