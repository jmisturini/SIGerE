from flask import Flask, render_template, redirect, url_for, request
from config import Config
from extensions import db, login_manager
from models import User, Classroom, Reservation
from flask_login import current_user



def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    from auth import bp as auth_bp
    from main import bp as main_bp
    from classrooms import bp as classrooms_bp
    from reservations import bp as reservations_bp
    from admin import bp as admin_bp
    from totem import bp as totem_bp
    from schedule import bp as schedule_bp
    from public import bp as public_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(classrooms_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(totem_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(public_bp)

    @app.errorhandler(403)
    def forbidden(_):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template('errors/500.html'), 500

    @app.context_processor
    def inject_now():
        from datetime import datetime
        return {'now': datetime.now()}
    
    @app.before_request
    def require_password_change():
        # If user is logged in and needs to change password
        if current_user.is_authenticated and current_user.force_password_change:
            # Allow access to the change password route, static files, and logout
            allowed_endpoints = ['auth.change_password', 'auth.logout', 'static']
            if request.endpoint not in allowed_endpoints:
                return redirect(url_for('auth.change_password'))

    with app.app_context():
        db.create_all()
        seed_data()

    return app


def seed_data():
    """Seed initial demo users and classrooms if DB is empty."""
    if User.query.count() == 0:
        admin = User(
            username='admin', email='admin@school.edu',
            full_name='System Administrator', role='admin',
            department='Administration',
            force_password_change=False
        )
        admin.set_password('admin123')
        db.session.add(admin)

        booker = User(
            username='booker', email='booker@school.edu',
            full_name='Jane Smith', role='room',
            department='Computer Science',
            force_password_change=False
        )
        booker.set_password('booker123')
        db.session.add(booker)

        viewer = User(
            username='viewer', email='viewer@school.edu',
            full_name='John Doe', role='viewer',
            department='External',
            force_password_change=False
        )
        viewer.set_password('viewer123')
        db.session.add(viewer)
        db.session.commit()
        print('Seeded users: admin/admin123, booker/booker123, viewer/viewer123')


app = create_app()


if __name__ == '__main__':
    app.run(debug=True, port=5000)
