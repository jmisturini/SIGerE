"""Utilidades compartilhadas entre os módulos."""
import re
import unicodedata

from urllib.parse import urlsplit

from flask import redirect, request, url_for


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
    args = request.args.to_dict()
    args.update(fixed_args)
    return redirect(url_for(endpoint, **args))
