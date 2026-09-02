from flask import Flask, render_template, redirect, url_for, request
from config import Config
from extensions import db, login_manager
from models import User
from datetime import datetime
import os

def create_app(config_class=Config):
    """Factory function to create and configure the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize Flask extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Register all Blueprints
    from auth import bp as auth_bp
    from main import bp as main_bp
    from classrooms import bp as classrooms_bp
    from reservations import bp as reservations_bp
    from admin import bp as admin_bp
    from totem import bp as totem_bp
    from schedule import bp as schedule_bp
    from public import bp as public_bp
    from payments import bp as payments_bp
    from kitchen import bp as kitchen_bp

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
    from commands import seed_command, sync_permissions_command
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

    # Context processor to inject current datetime into all templates
    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

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

    add_column_if_missing('recipes', 'photo VARCHAR(255)')
    add_column_if_missing('ingredients', 'unit_price FLOAT')
    add_column_if_missing('ingredients', 'category_id INTEGER')
    add_column_if_missing('stock_movements', 'recipe_id INTEGER')

    # Categorias padrão de ingredientes (apenas na primeira execução)
    if 'ingredient_categories' in inspector.get_table_names():
        from models import IngredientCategory, DEFAULT_INGREDIENT_CATEGORIES
        if IngredientCategory.query.count() == 0:
            for name, order in DEFAULT_INGREDIENT_CATEGORIES:
                db.session.add(IngredientCategory(name=name, display_order=order))
            db.session.commit()


app = create_app()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=5000)