"""Utilidades compartilhadas entre os módulos."""
import re
import unicodedata

from urllib.parse import urlsplit

from flask import current_app, has_request_context, redirect, request, url_for
from flask_login import current_user

from app.extensions import db


def auditar(evento, **campos):
    """Trilha de auditoria de segurança para eventos sensíveis — login,
    troca/reset de senha, bloqueios e ciclo de usuários.

    Grava em `audit_logs` (consultável no Painel Admin, /admin/auditoria) e
    replica no log da aplicação (journal em produção): a linha no log é a
    cópia de defesa — se o banco falhar, o registro permanece. NUNCA passar
    senha, hash ou token nos campos.
    """
    if not has_request_context():
        return
    actor_id = None
    actor_email = None
    if current_user.is_authenticated:
        actor_id = int(current_user.get_id())
        actor_email = current_user.email
    alvo = campos.pop('alvo', None)

    def _sanitiza(v):
        # CWE-117: o e-mail logado vem de input não validado contra quebras de
        # linha (LoginForm aceita qualquer texto até 120) — neutraliza \r/\n
        # para que uma tentativa não fabrique linhas falsas na auditoria.
        return str(v).replace('\r', '\\r').replace('\n', '\\n') if v is not None else None

    alvo_log = _sanitiza(alvo)
    detalhes = ' '.join(f'{k}={_sanitiza(v)}' for k, v in campos.items() if v is not None)
    ip = request.remote_addr or '-'
    try:
        from app.models import AuditLog
        db.session.add(AuditLog(evento=evento, actor_id=actor_id,
                                actor_email=actor_email, alvo=alvo, ip=ip,
                                detalhes=detalhes or None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.warning(
            '[AUDITORIA] evento=%s gravacao_banco=falha (registro segue no log)', evento)
    current_app.logger.info('[AUDITORIA] evento=%s ator=%s ip=%s alvo=%s %s',
                            evento, f'#{actor_id} <{actor_email}>' if actor_id else 'anonimo',
                            ip, alvo_log, detalhes)


def gerar_slug(texto):
    """Converte um texto em identificador snake_case: 'Biblioteca Central'
    → 'biblioteca_central' (minúsculas, sem acentos, símbolos viram _)."""
    texto = unicodedata.normalize('NFD', texto or '')
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn').lower()
    return re.sub(r'[^a-z0-9]+', '_', texto).strip('_')


def slug_unico(base, existentes):
    """Garante a unicidade do slug contra um conjunto de identificadores já
    usados, anexando sufixo numérico: 'biblioteca' → 'biblioteca_2'."""
    if base not in existentes:
        return base
    numero = 2
    while f'{base}_{numero}' in existentes:
        numero += 1
    return f'{base}_{numero}'


def redirect_back(default_endpoint, anchor=None, **fixed_args):
    """Volta para a página de origem da ação, preservando a consulta da
    listagem (filtros e ?page=N) — sem isso, ativar/desativar/excluir a
    partir de uma linha devolvia o usuário à primeira página, no topo da
    lista (e limpa os filtros aplicados).

    Usa o referrer do POST, aceito apenas quando é da mesma origem; sem
    referrer válido cai na listagem padrão. `anchor` rola até a linha
    afetada (requer o id correspondente no <tr> do template) e só faz
    sentido quando o registro continua existindo.
    """
    ref = request.referrer
    if ref:
        parts = urlsplit(ref)
        if parts.netloc == request.host:
            # Caminho precisa ser relativo ao host: "//host" e "\" são
            # interpretados como outra origem pelo navegador (open redirect).
            if ('\\' in parts.path or not parts.path.startswith('/')
                    or parts.path.startswith('//')):
                return redirect(url_for(default_endpoint, **fixed_args))
            destino = parts.path + (f'?{parts.query}' if parts.query else '')
            if anchor:
                destino += f'#{anchor}'
            return redirect(destino)
    return redirect(url_for(default_endpoint, **fixed_args))


def redirect_preserving_args(endpoint, **fixed_args):
    """Redirect para a listagem preservando a query string atual.

    Para o retorno de formulários criar/editar: o <form> sem action faz o
    POST para a própria URL (com a query de onde o usuário veio), então
    request.args carrega a página e os filtros da listagem de origem.
    """
    # Chaves com "_" prefixadas são reservadas do url_for (_external, _scheme,
    # _anchor, _method) e não podem vir da query string — controlariam o redirect.
    args = {k: v for k, v in request.args.items() if not k.startswith('_')}
    args.update(fixed_args)
    return redirect(url_for(endpoint, **args))
