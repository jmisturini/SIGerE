from functools import wraps
from flask import abort
from flask_login import current_user

def require_permission(perm_code):
    """Decorator que exige uma permissão específica para acessar a rota."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if not current_user.has_permission(perm_code):
                abort(403)
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_permission_or_owner(perm_code):
    """Permite acesso se o usuário tem a permissão OU é o dono da reserva.

    O recurso é sempre a reserva identificada por kwargs['reservation_id'] —
    usar esta decorator em rota com outro tipo de recurso é um erro de código.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            # Verifica permissão global primeiro
            if current_user.has_permission(perm_code):
                return f(*args, **kwargs)

            # Sem permissão global: apenas o dono da reserva passa
            reservation_id = kwargs.get('reservation_id')
            if reservation_id:
                from app.extensions import db
                from app.models import Reservation
                reservation = db.session.get(Reservation, reservation_id)
                if reservation and reservation.user_id == current_user.id:
                    return f(*args, **kwargs)

            abort(403)
        return decorated_function
    return decorator
