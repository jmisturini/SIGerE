"""Contexto de unidade educacional ativa (multi-unidade).

Cada requisição autenticada opera dentro de UMA unidade:
- O usuário opera nas unidades às quais está vinculado (User.unities, N:N) —
  com um único vínculo fica fixado nele; com vários, alterna entre os próprios
  pelo seletor no topo (armazenado na sessão, chave 'unity_id');
- Apenas o super-admin (permissão '*') e quem tem múltiplos vínculos alternam
  a unidade ativa — a permissão 'unity:switch', que antes também liberava o
  seletor, ficou reservada;
- Conta global (sem vínculos) e sem '*' não alterna: cai para a primeira
  unidade ativa por nome.

Os blueprints usam current_unity_id() para filtrar todas as queries. O valor
da sessão SEMPRE é validado contra o escopo do usuário antes de valer — apagar
um vínculo derruba a unidade da sessão sem privilégio residual.
"""
from flask import session, g
from flask_login import current_user

SWITCHABLE_PERMISSIONS = ('*',)

SESSION_KEY = 'unity_id'


def can_switch_unity():
    """True quando o usuário pode alternar a unidade ativa: super-admin ('*')
    ou mais de um vínculo ativo com unidades."""
    if not current_user.is_authenticated:
        return False
    if any(current_user.has_permission(code) for code in SWITCHABLE_PERMISSIONS):
        return True
    return len(_vinculos_ativos()) > 1


def _vinculos_ativos():
    """Unidades ativas às quais o usuário está vinculado (ordenadas por nome)."""
    cached = g.get('_vinculos_ativos')
    if cached is not None:
        return cached
    vinculos = sorted((u for u in current_user.unities if u.is_active),
                      key=lambda u: u.name.lower())
    g._vinculos_ativos = vinculos
    return vinculos


def allowed_unity_ids():
    """IDs das unidades em que o usuário pode operar: todas as ativas para o
    super-admin ('*'), os próprios vínculos ativos para os demais."""
    cached = g.get('_allowed_unity_ids')
    if cached is not None:
        return cached
    from app.models import Unity
    if current_user.has_permission('*'):
        ids = [u.id for u in Unity.query.filter_by(is_active=True)
               .order_by(Unity.name).all()]
    else:
        ids = [u.id for u in _vinculos_ativos()]
    g._allowed_unity_ids = ids
    return ids


def _first_active_unity_id():
    first = g.setdefault('_unity_first', None)
    if first is None:
        from app.models import Unity
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

    from app.models import Unity, db

    unity_id = None
    session_id = session.get(SESSION_KEY)
    if session_id:
        # A sessão só vale se a unidade continuar ativa E dentro do escopo do
        # usuário (super-admin: qualquer ativa; demais: os próprios vínculos).
        unity = db.session.get(Unity, session_id)
        if unity and unity.is_active and unity.id in allowed_unity_ids():
            unity_id = unity.id
    if unity_id is None:
        vinculos = _vinculos_ativos()
        if vinculos:
            unity_id = vinculos[0].id
    if unity_id is None:
        unity_id = _first_active_unity_id()

    g._current_unity_id = 'none' if unity_id is None else unity_id
    return unity_id


def current_unity():
    """Objeto Unity ativo (ou None)."""
    unity_id = current_unity_id()
    if unity_id is None:
        return None
    from app.models import Unity, db
    return db.session.get(Unity, unity_id)


def switchable_unities():
    """Unidades disponíveis no seletor: todas as ativas para o super-admin,
    os próprios vínculos ativos para quem tem mais de um (vazio se não alterna)."""
    if not can_switch_unity():
        return []
    from app.models import Unity
    if current_user.has_permission('*'):
        return Unity.query.filter_by(is_active=True).order_by(Unity.name).all()
    return _vinculos_ativos()


def unity_module_enabled(module_code):
    """Módulo opcional ativo na unidade da requisição.

    Sem unidade ativa (instalação sem multi-unidade) tudo fica ligado.
    Usado pelos templates para esconder as seções dos módulos desligados.
    """
    unity = current_unity()
    return True if unity is None else unity.is_module_enabled(module_code)


def reset_unity_cache():
    """Limpa o cache por-request (chamar após trocar a unidade na sessão)."""
    g.pop('_current_unity_id', None)
    g.pop('_unity_first', None)
    g.pop('_vinculos_ativos', None)
    g.pop('_allowed_unity_ids', None)
