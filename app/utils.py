"""Utilidades compartilhadas entre os módulos."""
import re
import unicodedata


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
