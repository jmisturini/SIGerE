"""Contexto de unidade educacional ativa (multi-unidade).

Cada requisição autenticada opera dentro de UMA unidade:
- Usuários comuns ficam fixados na própria unidade (User.unity_id);
- Usuários com a permissão '*' ou 'unity:switch' podem alternar a unidade
  ativa pelo seletor no topo (armazenada na sessão, chave 'unity_id');
- Sem unidade definida, cai para a primeira unidade ativa por nome.

Os blueprints usam current_unity_id() para filtrar todas as queries.
"""
from flask import session, g
from flask_login import current_user

SWITCHABLE_PERMISSIONS = ('*', 'unity:switch')

SESSION_KEY = 'unity_id'


def can_switch_unity():
    """Usuários autorizados a alternar entre unidades (admins globais)."""
    if not current_user.is_authenticated:
        return False
    return any(current_user.has_permission(code) for code in SWITCHABLE_PERMISSIONS)


def _first_active_unity_id():
    first = g.setdefault('_unity_first', None)
    if first is None:
        from models import Unity
        unity = Unity.query.filter_by(is_active=True).order_by(Unity.name).first()
        first = ('none',) if unity is None else ('ok', unity.id)
        g._unity_first = first
    return None if first[0] == 'none' else first[1]


def current_unity_id():
    """ID da unidade ativa da requisição (None se nenhuma unidade existir)."""
    if not current_user.is_authenticated:
        return None
    cached = g.get('_current_unity_id')
    if cached is not None:
        return None if cached == 'none' else cached

    from models import Unity, db

    unity_id = None
    if can_switch_unity():
        session_id = session.get(SESSION_KEY)
        if session_id:
            unity = db.session.get(Unity, session_id)
            if unity and unity.is_active:
                unity_id = unity.id
    if unity_id is None and current_user.unity_id:
        unity_id = current_user.unity_id
    if unity_id is None:
        unity_id = _first_active_unity_id()

    g._current_unity_id = 'none' if unity_id is None else unity_id
    return unity_id


def current_unity():
    """Objeto Unity ativo (ou None)."""
    unity_id = current_unity_id()
    if unity_id is None:
        return None
    from models import Unity, db
    return db.session.get(Unity, unity_id)


def switchable_unities():
    """Unidades disponíveis no seletor (apenas para quem pode alternar)."""
    if not can_switch_unity():
        return []
    from models import Unity
    return Unity.query.filter_by(is_active=True).order_by(Unity.name).all()


def reset_unity_cache():
    """Limpa o cache por-request (chamar após trocar a unidade na sessão)."""
    g.pop('_current_unity_id', None)
    g.pop('_unity_first', None)


def scope(query, model, column_name='unity_id'):
    """Aplica o filtro da unidade ativa a uma query do modelo informado."""
    return query.filter(getattr(model, column_name) == current_unity_id())
