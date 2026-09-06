from flask import Flask, render_template, redirect, url_for, request, flash
from app.config import Config
from app.extensions import db, login_manager, csrf, limiter, migrate
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
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

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
    # Ponte para bancos criados antes do Alembic (ver app/legacy_migrations.py)
    from app.legacy_migrations import legacy_upgrade_command
    app.cli.add_command(legacy_upgrade_command)

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

    # Rate limit excedido (ex.: várias tentativas de login): aviso amigável
    # em vez da página 429 crua.
    from flask_limiter.errors import RateLimitExceeded
    @app.errorhandler(RateLimitExceeded)
    def handle_rate_limit(e):
        flash('Muitas tentativas em pouco tempo. Aguarde um momento e tente novamente.', 'warning')
        return redirect(url_for('auth.login'))

    # Context processor to inject current datetime into all templates
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    # Coordenadas do clima (totem/portal) centralizadas no Config
    @app.context_processor
    def inject_weather_config():
        return {'totem_lat': app.config['TOTEM_LATITUDE'],
                'totem_lon': app.config['TOTEM_LONGITUDE']}

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

    # Schema gerenciado pelo Alembic (Flask-Migrate): `flask --app run db upgrade`
    # cria/atualiza as tabelas. Nada de DDL no boot — seguro com multi-worker.
    # O boot apenas orienta o operador quando o banco está fora do fluxo:
    with app.app_context():
        from sqlalchemy import inspect
        tables = inspect(db.engine).get_table_names()
        if not tables:
            print('⚠️  Banco de dados vazio: rode "flask --app run db upgrade" para '
                  'criar o schema e "flask --app run seed" para os dados iniciais.',
                  file=sys.stderr)
        elif 'alembic_version' not in tables:
            print('⚠️  Banco existente sem versionamento Alembic: rode '
                  '"flask --app run db stamp head" — ou "flask --app run '
                  'db-legacy-upgrade" se criado antes do módulo multi-unidade.',
                  file=sys.stderr)

        # Permissões/papéis novos em bancos já existentes (idempotente)
        if 'permissions' in tables:
            from app.commands import sync_permissions_impl
            sync_permissions_impl(verbose=False)

    return app
