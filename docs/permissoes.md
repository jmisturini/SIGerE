# Permissões e Papéis do SIGerE

> 🤖 **Documento gerado** por `docs/gerar_permissoes.py` a partir de
> `PERMISSION_DATA` e `ROLES_CONFIG` (`app/commands.py`) — não editar à mão.
> Após alterar o catálogo ou os papéis padrão, regenere com
> `python docs/gerar_permissoes.py`. Última geração: 2026-10-06.

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

- **Super Administrador** (`super_admin`, padrão do sistema) — 1 permissão
- **Administrador** (`admin`, padrão do sistema) — 47 permissões
- **Analista** (`coordinator`, padrão editável) — 13 permissões
- **Gestor** (`room_manager`, padrão editável) — 31 permissões
- **Professor** (`teacher`, padrão editável) — 6 permissões
- **Assistente** (`employee`, padrão editável) — 6 permissões
- **Módulo Cozinha** (`kitchen`, papel adicional (add-on)) — 3 permissões

Papéis customizados podem ser criados no painel (Painel → Papéis) com
qualquer combinação das permissões abaixo.

## Matriz papel × permissão

65 permissões no catálogo. ✓ = o papel possui a permissão (o
Super Administrador tem tudo via `*`).

| Permissão | Descrição | `super_admin` | `admin` | `coordinator` | `room_manager` | `teacher` | `employee` | `kitchen` |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **API** (`api`) | |  |  |  |  |  |  |  |
| `api:manage` | Gerenciar tokens de acesso à API de reservas | ✓ | ✓ |  |  |  |  |  |
| **Cursos** (`course`) | |  |  |  |  |  |  |  |
| `course:create` | Criar cursos/disciplinas | ✓ | ✓ |  | ✓ |  |  |  |
| `course:edit` | Editar cursos/disciplinas | ✓ | ✓ |  | ✓ |  |  |  |
| `course:read` | Visualizar cursos/disciplinas | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| `course:toggle` | Ativar/desativar cursos/disciplinas | ✓ | ✓ |  | ✓ |  |  |  |
| **Tipos de Curso** (`course_type`) | |  |  |  |  |  |  |  |
| `course_type:create` | Criar Tipos de Curso | ✓ | ✓ |  | ✓ |  |  |  |
| `course_type:edit` | Editar Tipos de Curso | ✓ | ✓ |  | ✓ |  |  |  |
| `course_type:read` | Acessar o cadastro de Tipos de Curso | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `course_type:toggle` | Ativar/desativar Tipos de Curso | ✓ | ✓ |  | ✓ |  |  |  |
| **Feriados** (`holiday`) | |  |  |  |  |  |  |  |
| `holiday:create` | Criar feriados | ✓ | ✓ |  |  |  |  |  |
| `holiday:delete` | Excluir feriados | ✓ | ✓ |  |  |  |  |  |
| `holiday:edit` | Editar feriados | ✓ | ✓ |  |  |  |  |  |
| `holiday:import` | Importar feriados da API | ✓ | ✓ |  |  |  |  |  |
| `holiday:read` | Visualizar feriados | ✓ | ✓ |  |  |  |  |  |
| **Cozinha** (`kitchen`) | |  |  |  |  |  |  |  |
| `kitchen:read` | Acessar o módulo de Cozinha (fichas técnicas, preparações e compras) | ✓ | ✓ |  |  |  |  | ✓ |
| `kitchen:sheet_create` | Enviar e salvar fichas técnicas (DOCX) | ✓ | ✓ |  |  |  |  | ✓ |
| `kitchen:sheet_delete` | Excluir fichas técnicas e preparações | ✓ | ✓ |  |  |  |  |  |
| `kitchen:shopping_export` | Gerar e exportar a requisição de compra | ✓ | ✓ |  |  |  |  | ✓ |
| **Vale Alimentação** (`meal`) | |  |  |  |  |  |  |  |
| `meal:create` | Lançar dias trabalhados no Vale Alimentação - Professores | ✓ |  | ✓ | ✓ |  |  |  |
| `meal:delete` | Excluir lançamentos do Vale Alimentação - Professores | ✓ |  |  | ✓ |  |  |  |
| `meal:edit` | Editar lançamentos do Vale Alimentação - Professores | ✓ |  | ✓ | ✓ |  |  |  |
| `meal:read` | Acessar o Vale Alimentação - Professores (lançamentos e listagem) | ✓ |  | ✓ | ✓ |  |  |  |
| **Notificações** (`notification`) | |  |  |  |  |  |  |  |
| `notification:groups` | Gerenciar os grupos personalizados de notificação da unidade | ✓ | ✓ |  |  |  |  |  |
| `notification:manage` | Configurar o aviso de sobrecarga de professor da unidade (grupos destinatários) | ✓ | ✓ |  |  |  |  |  |
| **Hora Extra** (`payment`) | |  |  |  |  |  |  |  |
| `payment:close_month` | Fechar os lançamentos do mês de Hora Extra (bloqueia edições e baixa a planilha final) | ✓ |  |  | ✓ |  |  |  |
| `payment:create` | Criar lançamentos de pagamento extra (hora extra) | ✓ |  | ✓ | ✓ |  |  |  |
| `payment:delete` | Excluir lançamentos de pagamento extra (hora extra) | ✓ |  |  | ✓ |  |  |  |
| `payment:edit` | Editar lançamentos de pagamento extra (hora extra) | ✓ |  | ✓ | ✓ |  |  |  |
| `payment:export` | Exportar a planilha de pagamento extra (hora extra) | ✓ |  |  | ✓ |  |  |  |
| `payment:read` | Ver lançamentos de pagamento extra (hora extra) | ✓ |  |  | ✓ |  |  |  |
| **Reservas** (`reservation`) | |  |  |  |  |  |  |  |
| `reservation:approve` | Aprovar reservas pendentes | ✓ | ✓ | ✓ | ✓ |  |  |  |
| `reservation:cancel_all` | Cancelar todas as reservas | ✓ | ✓ |  | ✓ |  |  |  |
| `reservation:cancel_own` | Cancelar próprias reservas | ✓ |  | ✓ | ✓ | ✓ | ✓ |  |
| `reservation:create` | Criar reservas | ✓ |  | ✓ | ✓ | ✓ | ✓ |  |
| `reservation:delete_all` | Excluir todas as reservas | ✓ | ✓ |  | ✓ |  |  |  |
| `reservation:edit_all` | Editar todas as reservas | ✓ | ✓ |  | ✓ |  |  |  |
| `reservation:read_all` | Ver todas as reservas | ✓ | ✓ |  | ✓ |  |  |  |
| `reservation:read_own` | Ver próprias reservas | ✓ |  | ✓ | ✓ | ✓ | ✓ |  |
| **Papéis** (`role`) | |  |  |  |  |  |  |  |
| `role:create` | Criar papéis | ✓ | ✓ |  |  |  |  |  |
| `role:delete` | Excluir papéis | ✓ | ✓ |  |  |  |  |  |
| `role:edit` | Editar papéis | ✓ | ✓ |  |  |  |  |  |
| `role:read` | Visualizar papéis | ✓ | ✓ |  |  |  |  |  |
| **Salas** (`room`) | |  |  |  |  |  |  |  |
| `room:create` | Criar salas | ✓ | ✓ |  | ✓ |  |  |  |
| `room:edit` | Editar salas | ✓ | ✓ |  | ✓ |  |  |  |
| `room:read` | Visualizar salas | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| `room:toggle` | Ativar/desativar salas | ✓ | ✓ |  | ✓ |  |  |  |
| **Sistema** (`system`) | |  |  |  |  |  |  |  |
| `*` | Permissão universal (super admin) | ✓ |  |  |  |  |  |  |
| `system:dashboard` | Acessar painel administrativo | ✓ | ✓ |  |  |  |  |  |
| `system:export` | Exportar dados diversos | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| **Unidades** (`unity`) | |  |  |  |  |  |  |  |
| `unity:create` | Criar unidades educacionais | ✓ | ✓ |  |  |  |  |  |
| `unity:edit` | Editar unidades educacionais | ✓ | ✓ |  |  |  |  |  |
| `unity:modules` | Ativar/desativar módulos da unidade (Cozinha, Financeiro) | ✓ | ✓ |  |  |  |  |  |
| `unity:read` | Visualizar unidades educacionais | ✓ | ✓ |  |  |  |  |  |
| `unity:switch` | Alternar a unidade ativa de operação (reservada ao super-admin) | ✓ |  |  |  |  |  |  |
| `unity:toggle` | Ativar/desativar unidades educacionais | ✓ | ✓ |  |  |  |  |  |
| **Usuários** (`user`) | |  |  |  |  |  |  |  |
| `user:create` | Criar usuários | ✓ | ✓ |  |  |  |  |  |
| `user:edit` | Editar usuários | ✓ | ✓ |  |  |  |  |  |
| `user:read` | Visualizar usuários | ✓ | ✓ |  |  |  |  |  |
| `user:toggle` | Ativar/desativar usuários | ✓ | ✓ |  |  |  |  |  |
| **Vale-Transporte** (`vt`) | |  |  |  |  |  |  |  |
| `vt:config` | Configurar o pedido público de VT (vales base e data de fechamento) | ✓ | ✓ |  |  |  |  |  |
| `vt:delete` | Excluir pedidos de VT | ✓ |  |  |  |  |  |  |
| `vt:edit` | Corrigir pedidos de VT recebidos | ✓ |  |  |  |  |  |  |
| `vt:empresas` | Gerenciar empresas de ônibus e tarifas do pedido de VT | ✓ | ✓ |  |  |  |  |  |
| `vt:export` | Exportar a planilha de pagamento do Vale-Transporte | ✓ |  |  |  |  |  |  |
| `vt:read` | Acessar o Vale-Transporte (pedidos e relatório) | ✓ | ✓ |  |  |  |  |  |

## Manutenção

- **Novo código de permissão ou mudança de papel:** edite
  `PERMISSION_DATA`/`ROLES_CONFIG` em `app/commands.py`, regenere este
  documento e rode `flask sync-permissions` (o startup também sincroniza
  sozinho, de forma idempotente);
- **Aposentadoria:** remover o código de `PERMISSION_DATA` faz o sync
  apagar a permissão e os vínculos com papéis em bancos já existentes;
- **Referência de uso:** `grep -r "require_permission" app/blueprints/`.
