# Guia de continuidade do SIGerE

> **Para que serve:** ponto de partida para continuar o desenvolvimento deste projeto
> em outra instância do ZCode ou em outro computador. A memória local do ZCode
> (memórias automáticas por projeto) **não viaja com o git** — este arquivo é o
> subconjunto transportável: o que uma sessão nova precisa saber para não recomeçar
> do zero.
>
> **Última atualização:** 2026-10-27, após a release **v1.37.0** (segurança: política de senha, bloqueio de conta e trilha de auditoria) e revisão completa da documentação (README, guias de docs/, permissoes.md regenerado e manual do usuário).
> Ao fechar cada release, atualize a seção [Estado e pendências](#8-estado-e-pendências)
> e a data acima.

---

## 1. O projeto em 60 segundos

**SIGerE** — Sistema Integrado de Gerenciamento Educacional. Plataforma web em
**Flask 3 + Bootstrap 5** para gestão de reservas de salas, cronogramas acadêmicos,
pagamentos docentes (hora extra), vale transporte/RH, operação de cozinha e
notificações, com suporte a **múltiplas unidades educacionais**. Possui API pública
de reservas (`/api/v1`) e página de totem.

- **Banco de dados:** SQLite em desenvolvimento (`reservation.db`, já no repo);
  **PostgreSQL** em produção (o `setup_interativo.py` não cria o banco, só grava a
  `DATABASE_URL` no `.env`). Toda migration precisa funcionar nos dois dialetos
  (ver seção 6).
- **Multi-unidade:** relação N:N usuário↔unidades (tabela `user_unities`). Para
  consultar usuários por unidade, usar `User.escopo_unidade(uid)` — a antiga coluna
  `users.unity_id` não existe mais. Super-admin tem escopo `*`.
- **Notificações:** por reserva (config 24h/1h + destinatários por reserva, mutes no
  perfil), consumidas por um timer externo `sigere-notify` na VM — não usa
  APScheduler/Celery/SSE.
- **Docs do repo:** `README.md` (visão, instalação, permissões, contas demo),
  `CONTRIBUTING.md` (fluxo de branches e PRs — autoridade nesta matéria),
  `docs/implantacao-producao.md` (deploy passo a passo), `docs/desenvolvimento-debug.md`,
  `docs/api-reservas.md`, `docs/permissoes.md` (gerado por `docs/gerar_permissoes.py`),
  `docs/migracao-legado.md`, `docs/backlog-seguranca.md` (ideias de segurança futuras).

## 2. Preparando o ambiente (máquina nova)

1. `git clone` e entre no diretório; crie um virtualenv.
2. **Python 3.11 ou superior** — piso das dependências (`pillow==13` exige 3.11+;
   o setup interativo valida também a `.venv` reaproveitada). O CI usa 3.14; alinhe a
   local com 3.11+.
3. `pip install -r requirements.txt -r requirements-dev.txt`.
4. Banco local: `flask --app run db upgrade` (aplica todas as migrations no
   `reservation.db`) e, para dados de demonstração, `flask --app run seed-demo`
   (usuários demo, senha `demo1234`; `admin@school.edu` tem escopo `*`) — só roda
   com `FLASK_DEBUG=true` (ou `SIGERE_PERMITIR_SEED_DEMO=1` forçando).
5. Ao servir requisições fora de `FLASK_DEBUG`, defina uma `SECRET_KEY` forte.
   Comandos CLI de manutenção (`flask db upgrade`, `seed-demo`…) são isentos
   pela fábrica. Embora `flask --app run run` seja carregado no contexto CLI,
   ele serve HTTP; fora de `FLASK_DEBUG`, defina `SECRET_KEY` manualmente
   antes de usar esse comando.
6. Servidor de dev: `python run.py` (ou `flask --app run run` — ver item 5).
7. Conferir a suíte: `pytest` (~807 testes, alguns minutos).

## 3. Fluxo de trabalho: branches e PRs

O detalhamento oficial está no `CONTRIBUTING.md`. O que não se deriva dele:

- `main` e `dev` são **protegidas com `enforce_admins`**: push direto do próprio
  owner é rejeitado (erro GH006). **Tudo vai por PR**, mesmo ajuste pequeno de docs.
- Branches temporárias `feature/`, `fix/`, `hotfix/`, `release/` sempre a partir da
  `dev` atualizada; **apagar local e remotamente** após o merge e realinhar a dev
  local com `git pull --ff-only`. Manter a working tree 100% limpa no fim de cada ciclo.
- CI: job `tests` (pytest, ~4 min) e job `qualidade` (**ruff + bandit + pip-audit** — CVE em
  dependência do `requirements.txt` derruba o CI mesmo com testes verdes; resolver
  com bump da versão pinada). Num PR, podem existir **2 check-runs** (push da dev +
  o PR em si): conferir todos antes de mesclar.
- Padrão de commits: prefixos em português (`ui:`, `fix:`, `docs:`, `release:`, `notificacoes:` …).

### Sem `gh` CLI — API do GitHub via curl

O `gh` **não está instalado/autenticado** nas máquinas usadas até agora. Caminho comprovado:

- Token: `git credential fill` (host `github.com`) do Git Credential Manager — nunca
  ecoar o token; ler para uma variável com `sed`.
- Criar PR: `POST /repos/jmisturini/SIGerE/pulls`; mesclar:
  `PUT /repos/jmisturini/SIGerE/pulls/{n}/merge` com `merge_method: "merge"` (estilo
  do histórico) e, se quiser, `sha` + `commit_title` customizados.
- **Armadilha Windows:** o `curl.exe` não entende caminhos `/tmp` do Git Bash — usar
  caminhos Windows (`C:/Users/.../AppData/Local/Temp/...`) ou um arquivo temporário no
  próprio diretório do repo (apagar depois). Payloads JSON de PR/merge em **arquivo
  UTF-8** evitam erro 400 com acentos no `-d` inline.
- Deletar branch remota: `DELETE /repos/jmisturini/SIGerE/git/refs/heads/...` (retorna 204).
- **Criar a GitHub Release** (equivalente ao `gh release create` do passo 4):
  valide antes que a tag existe (`GET /repos/jmisturini/SIGerE/git/ref/tags/vX.Y.Z`
  → 200 — sem isso o `POST` criaria a tag no commit da branch padrão) e então
  `POST /repos/jmisturini/SIGerE/releases` com payload
  `{"tag_name": "vX.Y.Z", "name": "SIGerE vX.Y.Z — <título da entrada>",
  "body": "<texto da entrada em app/version.py>", "target_commitish": "main"}`
  (a tag já deve existir; `body` aceita markdown).

## 4. Ciclo de release

Só há release quando houver bump: mudança de código visível ou entrada de changelog.

1. Branch `release/vX.Y.Z` a partir da `dev` → bump de `APP_VERSION` + entrada no
   **topo** de `RELEASES` em `app/version.py` → commit `release: vX.Y.Z`.
2. PR → `dev` (CI verde) → PR `dev` → `main` (CI verde).
3. **Tag anotada no commit de merge dev→main da main** (não no merge na dev):
   `git tag -a vX.Y.Z <sha-do-merge> -m "SIGerE vX.Y.Z"` + `git push origin vX.Y.Z`.
4. **GitHub Release** a partir da tag (pré-requisito: `gh` instalado e
   autenticado — `gh auth login`; nas máquinas sem `gh`, siga a seção
   "Sem `gh` CLI" e publique pela API):
   `gh release create vX.Y.Z --verify-tag --notes-file notas.md --title "SIGerE vX.Y.Z — <título da entrada>"`
   — copie título e grupos da entrada
   correspondente de `RELEASES` em `app/version.py` (Notas geradas por IA e changelog
   automático não substituem a entrada curada; `--verify-tag` impede o `gh` de
   criar tag ausente apontando para a branch padrão). Desde a v1.36.0, toda release publicada
   ganha o objeto GitHub Release; a tag anotada continua sendo a referência primária.
5. PR `main` → `dev` para realinhar (o merge da main traz a tag de volta à dev).

Mudança só de docs pode ir direto por PR sem release.

## 5. Produção (Oracle Cloud)

- VM OCI (IP e domínio **fora do repo público** — apontados pelo CodeRabbit como
  exposição de infraestrutura, CWE-200, no PR #148; registre-os no gerenciador de
  segredos/nota privada do operador; recuperáveis no console OCI e no DNS). Stack:
  nginx + gunicorn no socket `unix:/run/sigere/sigere.sock` via `sigere.service`.
- **Firewall em duas camadas:** Security List da VCN no console OCI **e** iptables da
  instância (imagem Ubuntu da Oracle só libera a 22; persistência via
  `/etc/iptables/rules.v4` com `netfilter-persistent save`). Abrir só uma não resolve.
- **Update oficial** (`docs/implantacao-producao.md` seção 10): `git status` limpo →
  `venv/bin/pip install -r requirements.txt gunicorn` → `flask --app run db upgrade` →
  `flask --app run sync-permissions` (o boot não sincroniza) → restart do serviço.
  Antes do `sync-permissions`, anote as revogações feitas em **Painel Admin → Papéis**:
  o comando devolve ao papel as permissões configuradas que estiverem ausentes, inclusive
  as revogadas de propósito. Se alguma revogação for perdida, reaplique-a no painel
  antes de liberar o acesso aos usuários.
  Migrations pendentes **não derrubam o boot** (o app sobe com aviso), mas o
  `db upgrade` e o `sync-permissions` são obrigatórios para as features novas
  funcionarem.
- **Diagnóstico de crash do serviço:** o journal fica mudo — o gunicorn loga em
  **`/var/log/sigere/error.log`** (`--error-logfile` no unit). Ir direto lá e confirmar
  o ExecStart real com `systemctl cat sigere`.
- **Duas venvs distintas:** o `setup_interativo.py` mantém `.venv`, mas o serviço
  documentado executa `venv/bin/gunicorn` — update via setup não atualiza o ambiente
  que serve (causa provável do incidente de 2026-10-07, exit 1 após update).
- **`/run` é tmpfs:** o unit precisa de `RuntimeDirectory=sigere` (+
  `RuntimeDirectoryMode=0755`); sem isso, após reboot o socket some e o serviço morre
  com sintoma idêntico a crash de código. A doc já foi corrigida (v1.31.1), mas o unit
  na VM pode continuar o antigo — corrigir à mão se necessário.
- A máquina de desenvolvimento usual **não tinha chave SSH** para a VM; diagnóstico
  remoto dependia de acesso pelo console da Oracle.

## 6. Armadilhas técnicas conhecidas

- **Migrations portáveis SQLite/PostgreSQL** (o projeto roda nos dois):
  - Booleano **nunca** como literal `1`/`0` em SQL cru — usar `sa.text(...)` com
    parâmetros Python (`{'v': True}`) para atribuição e a coluna nua como predicado
    (`WHERE is_active`).
  - `cursor.lastrowid` não existe no psycopg2 — usar `sa.Table` com PK declarada e
    `inserted_primary_key`.
  - Funções SQLite (`instr`, `strftime`) não existem no PG (`strpos`); alter
    numérico→integer no PG exige `postgresql_using='col::integer'`.
  - Validar a cadeia sempre com `DATABASE_URL=sqlite:///<temp>` +
    `flask --app run db upgrade` em banco temporário.
- **Testes dependentes de data:** agendar "amanhã" quebra no sábado (domingo é
  bloqueado por `check_schedule_restrictions`). Padrão a vigiar em testes novos.
- **Flask-SQLAlchemy 3.1.x:** `db.paginate(Query)` está quebrado — usar
  `query.paginate()` (5 call sites já convertidos).
- **Fix de segurança pode abrir vazamento adjacente:** identificar usuário por email
  antes de validar o POST fez página de erro vazar nome/matrícula (CWE-200, PR #136) —
  guardar o valor do POST e restaurá-lo em qualquer resposta de erro.
- **Teste visual no navegador** (receita completa nas memórias locais; resumo):
  subir banco demo descartável via `DATABASE_URL` sqlite temporário na porta 5001;
  campos com **TomSelect** não aceitam `selectOption` (usar `evaluate` no `<select>` +
  evento change); **screenshot fullPage quebra** com a sidebar fixa (usar viewport +
  `scrollIntoView`); trocar de usuário exige `GET /logout` antes do POST `/login`;
  servidor sem `FLASK_DEBUG` não recarrega templates (matar o processo **por PID** —
  `taskkill //F //IM python.exe` mata todo Python).
- **Manual do usuário:** regenerar com `python docs/gerar_manual.py` (pipeline
  versionado; conteúdo na lista `BLOCOS`; valida visualmente com `pymupdf`).

## 7. Decisões de design já tomadas (não refazer a roda)

- **Home pública:** opção C "cards funcionais" (PR #62). Os mockups A/B/C das
  propostas estão arquivados na tag anotada `archive/redesign-home-previews`
  (recuperar com `git switch -c <nome> archive/redesign-home-previews`).
- **Notificações:** redesign por reserva publicado na v1.30.0 (migrations
  `c2a9e7b5d4f1`; tabelas `reservation_notification_configs`, `user_notification_prefs`
  + mutes). A junção de categorias silenciadas referencia
  `user_notification_prefs.user_id` (não `users.id`) de propósito. Sobrecarga de
  professor (`notificar_sobrecarga_professor`) ficou intocada.
- **Sidebar:** Vale Transporte no bloco **RH**; Financeiro só com Hora Extra;
  visibilidade sob `vt:read` + `unity_module_enabled('finance')`.
- **Formulário de reserva:** Disciplina **não** depende mais do curso (desacoplado na
  v1.30.0); o modelo (`Subject.course_id`) continua existindo no cadastro.
- **Favicons:** já commitados desde a v1.19.0 (prédio branco sobre Azul Senac
  `#004b8d`; fonte vetorial em `app/static/favicon.svg`).
- **Redesign visual por fases:** concluído na v1.36.0 — fase 1 (login, painel, agenda,
  reservas) e fase 2 (admin/RH/financeiro/cozinha) na v1.35.0–v1.36.0; fase 3 (portal,
  salas, relatórios, erros, deduplicação de CSS) no PR #146. Design system em
  `app/static/css/style.css` (tokens de tema/accent). Mantidos de propósito: `home.html`
  (componentes próprios sobre os tokens) e `totem.html` (HTML/CSS próprios por
  restrição de hardware — Raspberry Pi).

## 8. Estado e pendências

Estado em **2026-10-27** (v1.37.0 publicada; documentação revisada):

| Item | Situação |
|---|---|
| Documentação | Revisada em 2026-10-27: README, api-reservas, implantação-producao, desenvolvimento-debug, guia-continuidade, permissoes.md regenerado (73 permissões) e manual do usuário regenerado para a v1.37.0. |
| Manual do usuário (`docs/manual-do-usuario.pdf`) | Atualizado para a v1.37.0 (2026-10-27): Adicional Noturno, fluxo de professor pendente, autocancel, política de senha, bloqueio de conta, auditoria. Regenerar com `python docs/gerar_manual.py` a cada release relevante. |
| Produção (VM OCI) | Confirmar na VM: `db upgrade` **e `sync-permissions`** (o sync saiu do boot — há permissões novas na v1.37: `user:lock`, `system:audit`), `RuntimeDirectory=sigere` no unit, e a resolução do incidente de 2026-10-07 (exit 1 pós-update; ver seção 5). |
| CI | Status check do `tests` ainda não é *required* — pode ser endurecido em Settings depois de comprovado estável. |

## 9. Memória local do ZCode (não viaja com o git)

Nas máquinas usadas até agora, as memórias automáticas do projeto ficam em:

```
%USERPROFILE%\.zcode\cli\memories\projects\sigere-<hash>\memory\
```

com índice em `MEMORY.md` (um resumo por arquivo). **Ao migrar de computador**, esse
diretório pode ser copiado para o mesmo caminho na nova máquina. Este guia cobre o
essencial; as memórias guardam detalhes extras (receitas completas de teste visual,
histórico de PRs com números de commit, hipóteses descartadas em incidentes).

Ao concluir trabalho relevante, **atualize este arquivo** (seção 8 principalmente) —
é ele o ponto de partida da próxima sessão, em qualquer máquina.
