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

def require_permission_or_owner(perm_code, owner_attr='user_id'):
    """Permite acesso se o usuário tem a permissão OU é o dono do recurso."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)

            # Verifica permissão global primeiro
            if current_user.has_permission(perm_code):
                return f(*args, **kwargs)

            # Se não tem permissão global, verifica se é dono do recurso
            resource_id = kwargs.get('reservation_id') or kwargs.get('user_id')
            if resource_id:
                from app.models import Reservation
                resource = Reservation.query.get(resource_id)
                if resource and getattr(resource, owner_attr) == current_user.id:
                    return f(*args, **kwargs)

            abort(403)
        return decorated_function
    return decorator