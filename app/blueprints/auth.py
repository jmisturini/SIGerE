from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse
from app.models import User
from app.forms import LoginForm, ChangePasswordForm
from app.extensions import db

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
            
            # Redirect to requested page or dashboard.
            # SECURITY: validate the 'next' parameter to prevent open redirect attacks.
            # Only allow relative URLs (no external domain in netloc).
            next_page = request.args.get('next')
            if next_page and urlparse(next_page).netloc != '':
                next_page = None
            return redirect(next_page or url_for('main.index'))
            
        flash('Nome de usuário ou senha inválidos.', 'danger')
    return render_template('auth/login.html', form=form)

# Route to force password change on first login
@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        # CORREÇÃO: Verificar se a senha atual está correta
        if not current_user.check_password(form.current_password.data):
            flash('Senha atual incorreta.', 'danger')
            return render_template('auth/change_password.html', form=form)
        
        # FIX: Fetch a fresh instance explicitly to bypass any proxy/identity-map caching.
        # Using filter_by().first() forces SQLAlchemy to hit the DB and return a clean object.
        user = User.query.filter_by(id=current_user.id).first()
        if not user:
            flash('Erro de sessão. Faça login novamente.', 'danger')
            return redirect(url_for('auth.logout'))

        # Update password and flag
        user.set_password(form.password.data)
        user.force_password_change = False

        try:
            # CORREÇÃO: removido o flush() redundante antes do commit() e o bloco
            # defensivo após refresh() — o commit já faz o flush e a flag
            # atualizada é confirmada pelo refresh, sem necessidade de re-checagem.
            db.session.commit()
            db.session.refresh(user)
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar: {str(e)}', 'danger')
            return render_template('auth/change_password.html', form=form)

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