from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import User
from forms import LoginForm, ChangePasswordForm
from extensions import db

bp = Blueprint('auth', __name__)

# Route for user login
@bp.route('/login', methods=['GET', 'POST'])
def login():
    # Redirect to dashboard if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
        
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        
        # Verify user exists and password is correct
        if user and user.check_password(form.password.data):
            if not user.is_active_user:
                flash('Sua conta foi desativada. Por favor, contate um administrador.', 'danger')
                return redirect(url_for('auth.login'))
                
            login_user(user)
            flash(f'Bem-vindo de volta, {user.full_name}!', 'success')
            
            # Redirect to requested page or dashboard
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.index'))
            
        flash('Nome de usuário ou senha inválidos.', 'danger')
    return render_template('auth/login.html', form=form)

# Route to force password change on first login
@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        # Update password hash and remove the force flag
        current_user.set_password(form.password.data)
        current_user.force_password_change = False
        db.session.commit()
        flash('Sua senha foi atualizada com sucesso!', 'success')
        return redirect(url_for('main.index'))
    return render_template('auth/change_password.html', form=form)

# Route for user logout
@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('auth.login'))