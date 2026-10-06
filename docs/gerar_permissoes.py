"""Gera docs/permissoes.md — matriz papel × permissão do SIGerE.

A documentação é derivada diretamente de PERMISSION_DATA e ROLES_CONFIG
(app/commands.py), então o documento nunca destoa do código enquanto for
regenerado. Após alterar o catálogo ou os papéis padrão, rode:

    python docs/gerar_permissoes.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.commands import PERMISSION_DATA, ROLES_CONFIG  # noqa: E402

SAIDA = Path(__file__).resolve().parent / 'permissoes.md'

# Orem dos papéis na matriz: principais primeiro, add-on (módulo) no fim.
ORDEM_PAPéis = ['super_admin', 'admin', 'coordinator', 'room_manager',
                'teacher', 'employee', 'kitchen']

MODULO_ROTULO = {
    'user': 'Usuários', 'unity': 'Unidades', 'room': 'Salas',
    'reservation': 'Reservas', 'course': 'Cursos', 'course_type': 'Tipos de Curso',
    'holiday': 'Feriados', 'payment': 'Hora Extra', 'meal': 'Vale Alimentação',
    'vt': 'Vale-Transporte', 'kitchen': 'Cozinha', 'notification': 'Notificações',
    'system': 'Sistema', 'api': 'API', 'role': 'Papéis',
}


def _matriz():
    papeis = [p for p in ORDEM_PAPéis if p in ROLES_CONFIG]
    extras = [p for p in ROLES_CONFIG if p not in ORDEM_PAPéis]
    papeis += extras

    linhas = []
    # Agrupado por módulo, com '*' (universal) por último.
    catalogo = sorted(PERMISSION_DATA, key=lambda p: (p[1], p[0] != '*', p[0]))
    modulo_anterior = None
    for code, module, _action, desc in catalogo:
        if module != modulo_anterior:
            rotulo = MODULO_ROTULO.get(module, module)
            linhas.append(f'| **{rotulo}** (`{module}`) | | '
                          + ' | '.join([''] * len(papeis)) + ' |')
            modulo_anterior = module
        celulas = []
        for papel in papeis:
            perms = ROLES_CONFIG[papel]['permissions']
            tem = '*' in perms or code in perms
            celulas.append('✓' if tem else '')
        linhas.append(f'| `{code}` | {desc} | ' + ' | '.join(celulas) + ' |')

    cabecalho = ('| Permissão | Descrição | '
                 + ' | '.join(f"`{p}`" for p in papeis) + ' |')
    separador = '|---|---|' + ':-:|' * len(papeis)
    return '\n'.join([cabecalho, separador] + linhas), papeis


def _rotulos_papeis():
    linhas = []
    for nome, config in ROLES_CONFIG.items():
        if config.get('is_system'):
            tipo = 'padrão do sistema'
        elif nome == 'kitchen':
            tipo = 'papel adicional (add-on)'
        else:
            tipo = 'padrão editável'
        n = len(config['permissions'])
        linhas.append(f"- **{config['label']}** (`{nome}`, {tipo}) — "
                      f"{n} {'permissão' if n == 1 else 'permissões'}")
    return '\n'.join(linhas)


def gerar():
    matriz, papeis = _matriz()
    total = len(PERMISSION_DATA)
    conteudo = f"""# Permissões e Papéis do SIGerE

> 🤖 **Documento gerado** por `docs/gerar_permissoes.py` a partir de
> `PERMISSION_DATA` e `ROLES_CONFIG` (`app/commands.py`) — não editar à mão.
> Após alterar o catálogo ou os papéis padrão, regenere com
> `python docs/gerar_permissoes.py`. Última geração: {date.today().isoformat()}.

## Como funciona

O SIGerE usa **RBAC** com permissões granulares:

- Cada **rota operacional** é protegida pelos decoradores
  `@require_permission('<código>')`, `@require_module('<módulo>')` (Cozinha e
  Financeiro podem ser desligados por unidade) e
  `@require_permission_or_owner(...)` (permissão global **ou** dono da reserva);
- **Templates** também consultam `current_user.has_permission(...)` para
  exibir/esconder botões — a checagem no servidor é a que vale;
- O usuário tem um **papel principal** (`users.role_id`) e pode acumular
  **papéis adicionais** (add-on, tabela `user_roles`); a permissão efetiva é a
  **união** dos dois conjuntos;
- A permissão curinga `*` (Super Administrador) dá acesso a tudo, inclusive
  trocar a unidade ativa de operação (`unity:switch` existe como marcador
  documental — atribuí-la não concede o poder, que é exclusivo do `*`).

## Papéis padrão

{_rotulos_papeis()}

Papéis customizados podem ser criados no painel (Painel → Papéis) com
qualquer combinação das permissões abaixo.

## Matriz papel × permissão

{total} permissões no catálogo. ✓ = o papel possui a permissão (o
Super Administrador tem tudo via `*`).

{matriz}

## Manutenção

- **Novo código de permissão ou mudança de papel:** edite
  `PERMISSION_DATA`/`ROLES_CONFIG` em `app/commands.py`, regenere este
  documento e rode `flask sync-permissions` (o startup também sincroniza
  sozinho, de forma idempotente);
- **Aposentadoria:** remover o código de `PERMISSION_DATA` faz o sync
  apagar a permissão e os vínculos com papéis em bancos já existentes;
- **Referência de uso:** `grep -r "require_permission" app/blueprints/`.
"""

    SAIDA.write_text(conteudo, encoding='utf-8')
    print(f"✅ {SAIDA} gerado ({total} permissões × {len(papeis)} papéis).")


if __name__ == '__main__':
    gerar()
