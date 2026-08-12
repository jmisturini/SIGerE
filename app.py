from flask import Flask, render_template, redirect, url_for, request
from config import Config
from extensions import db, login_manager
from models import User, Classroom, Reservation, Course, Subject, Holiday, TeacherBasePay, Role, Permission, RoomCategory
from datetime import datetime, date, time, timedelta
import random

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

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(classrooms_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(totem_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(payments_bp)

    # ── Register CLI commands ──
    from commands import seed_command
    app.cli.add_command(seed_command)

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
            if request.endpoint not in allowed_endpoints:
                return redirect(url_for('auth.change_password'))

    # Create database tables only (NO automatic seeding)
    with app.app_context():
        db.create_all()

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000)