from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func, update
from urllib.parse import urlparse
from app.models import User, RoomCategory, UserNotificationPref
from app.forms import LoginForm, ChangePasswordForm, ProfileForm
from app.extensions import db, limiter

bp = Blueprint('auth', __name__)

# Route for user login
@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('5 per minute', methods=['POST'])
def login():
    # Redirect to dashboard if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
        
    form = LoginForm()
    if form.validate_on_submit():
        # Login pelo e-mail; comparação sem diferenciar maiúsculas/minúsculas
        # para não bloquear quem digitar o e-mail com caixa diferente.
        email = form.email.data.strip().lower()
        user = User.query.filter(func.lower(User.email) == email).first()

        # Verify user exists and password is correct
        if user and user.check_password(form.password.data):
            # A mensagem de bloqueio só sai para quem JÁ acertou a senha:
            # para senha errada a resposta continua genérica, sem revelar
            # quais e-mails existem (ou estão bloqueados).
            if user.is_locked:
                flash('Sua conta está bloqueada por excesso de tentativas de acesso. '
                      'Procure um administrador para desbloqueá-la.', 'danger')
                return redirect(url_for('auth.login'))
            if not user.is_active_user:
                flash('Sua conta foi desativada. Por favor, contate um administrador.', 'danger')
                return redirect(url_for('auth.login'))

            # Acesso confirmado: zera o contador de erros do bloqueio. O reset
            # é condicional no banco (is_locked falso): se uma tentativa
            # concorrente bloqueou a conta enquanto este request rodava, nada
            # é zerado e o login é recusado abaixo.
            reset = db.session.execute(
                update(User)
                .where(User.id == user.id, User.is_locked.is_(False))
                .values(failed_login_attempts=0))
            if reset.rowcount != 1:
                db.session.rollback()
                flash('Sua conta está bloqueada por excesso de tentativas de acesso. '
                      'Procure um administrador para desbloqueá-la.', 'danger')
                return redirect(url_for('auth.login'))
            db.session.commit()
            if not login_user(user):
                # Barreira dupla: o is_active do User (cobre bloqueio) recusou
                # a sessão — não confirmar sucesso para quem não entrou.
                flash('Sua conta está bloqueada por excesso de tentativas de acesso. '
                      'Procure um administrador para desbloqueá-la.', 'danger')
                return redirect(url_for('auth.login'))
            flash(f'Bem-vindo de volta, {user.full_name}!', 'success')
            
            # SECURITY: validate the 'next' parameter to prevent open redirect
            # attacks. Only allow relative paths starting with a single '/' —
            # scheme, netloc, '\' (treated as '/' by browsers) and '//' point
            # to another origin.
            next_page = request.args.get('next')
            parsed = urlparse(next_page or '')
            if (not next_page or '\\' in next_page or parsed.scheme
                    or parsed.netloc or not next_page.startswith('/')
                    or next_page.startswith('//')):
                next_page = None
            return redirect(next_page or url_for('main.index'))

        # Senha errada (ou e-mail inexistente): resposta genérica. Para conta
        # existente, a falha conta para o bloqueio por excesso de tentativas.
        if user:
            user.registrar_falha_login()
            db.session.commit()
        flash('E-mail ou senha inválidos.', 'danger')
    # ocultar_sidebar: tela de login em foco total, sem a navegação do painel
    # (mesmo padrão do pedido público de VT).
    return render_template('auth/login.html', form=form, ocultar_sidebar=True)

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

        # SECURITY: block reuse of the current password. On the forced
        # first-login change this is the initial password issued by the
        # admin; hashes are salted, so compare via check_password instead
        # of comparing strings/hashes directly.
        if user.check_password(form.password.data):
            flash('A nova senha não pode ser igual à senha atual. Escolha uma senha diferente.', 'danger')
            return render_template('auth/change_password.html', form=form)

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

# Route for the user to view and update their own profile
@bp.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    """Autoatendimento: o usuário edita o próprio nome, departamento, senha e
    as preferências de notificação (silenciar os avisos de atividade próxima
    — todos, ou apenas os de salas de determinados tipos). E-mail (login) e
    papel só mudam pela administração."""
    form = ProfileForm(obj=current_user)
    # Tipos de sala (categorias ativas) para o "silenciar por tipo de sala".
    form.notify_muted_categories.choices = [
        (c.id, c.name) for c in
        RoomCategory.query.filter_by(is_active=True).order_by(RoomCategory.name).all()]
    if request.method == 'GET':
        pref = current_user.notification_pref
        if pref is not None:
            form.notify_mute_all.data = pref.mute_all
            form.notify_muted_categories.data = [c.id for c in pref.muted_categories]
            form.notify_email.data = pref.email_enabled
    if form.validate_on_submit():
        # Instância fresca do banco (mesmo cuidado da troca de senha)
        user = User.query.filter_by(id=current_user.id).first()
        if not user:
            flash('Erro de sessão. Faça login novamente.', 'danger')
            return redirect(url_for('auth.logout'))

        user.full_name = form.full_name.data
        user.department = form.department.data or None
        if form.password.data:
            user.set_password(form.password.data)
            user.force_password_change = False

        # Preferências de notificação (get-or-create 1:1 com o usuário)
        pref = user.notification_pref
        if pref is None:
            pref = UserNotificationPref(user_id=user.id)
            db.session.add(pref)
        pref.mute_all = form.notify_mute_all.data
        pref.email_enabled = form.notify_email.data
        pref.muted_categories = RoomCategory.query.filter(
            RoomCategory.id.in_(form.notify_muted_categories.data or [0]),
            RoomCategory.is_active == True).all()  # noqa: E712 — comparação de coluna

        db.session.commit()
        db.session.refresh(user)
        flash('Seu perfil foi atualizado com sucesso.', 'success')
        return redirect(url_for('auth.perfil'))

    return render_template('auth/perfil.html', form=form)

# Route for user logout
@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Você saiu do sistema.', 'info')
    return redirect(url_for('auth.login'))