# 🛠️ Desenvolvimento e Debug — Guia Completo

Documentação detalhada do ambiente de **desenvolvimento** do SIGerE: preparação
da máquina, modo debug, banco de dados local, migrações, testes automatizados,
depuração no dia a dia e os erros mais comuns (com as causas e as soluções).

> **Público-alvo:** quem vai alterar o código, rodar os testes ou depurar o sistema na própria máquina.
> **Arquitetura de referência:** Python 3.8+ · Flask 3.x · SQLAlchemy · Alembic · SQLite (local)
> 🚢 **Para instalar o sistema em servidor real, leia:** [implantacao-producao.md](implantacao-producao.md)

---

## Índice

- [Visão geral: desenvolvimento × produção](#-visão-geral-desenvolvimento--produção)
- [Preparação do ambiente](#-preparação-do-ambiente)
- [O modo debug (`FLASK_DEBUG`)](#-o-modo-debug-flask_debug)
  - [O que muda no modo debug](#o-que-muda-no-modo-debug)
  - [Como ativar em cada sistema](#como-ativar-em-cada-sistema)
  - [Arquivo `.env` — o que o Flask lê e o que não lê](#arquivo-env--o-que-o-flask-lê-e-o-que-não-lê)
- [Banco de dados local](#-banco-de-dados-local)
- [Migrações durante o desenvolvimento](#-migrações-durante-o-desenvolvimento)
- [CLI de manutenção](#-cli-de-manutenção)
- [Executando o servidor](#-executando-o-servidor)
- [Contas de demonstração](#-contas-de-demonstração)
- [Testes automatizados](#-testes-automatizados)
- [Depuração no dia a dia](#-depuração-no-dia-a-dia)
- [Erros comuns e soluções](#-erros-comuns-e-soluções)
- [Checklist antes do commit](#-checklist-antes-do-commit)
- [Perguntas frequentes](#-perguntas-frequentes)

---

## 🧭 Visão geral: desenvolvimento × produção

O mesmo código atende aos dois cenários. O que muda é **um interruptor** — a
variável `FLASK_DEBUG` — e algumas consequências de segurança que se ligam
sozinhas a partir dela:

| Aspecto | Desenvolvimento (`FLASK_DEBUG=true`) | Produção (sem `FLASK_DEBUG`) |
|---------|--------------------------------------|------------------------------|
| Servidor | Servidor nativo do Flask (`python run.py`) | Gunicorn + Nginx (ver [implantação](implantacao-producao.md)) |
| Debugger interativo | ✅ Werkzeug (traceback navegável + console) | ❌ Nunca exposto |
| Recarregamento automático | ✅ Reinicia ao salvar arquivo | ❌ Exige `systemctl reload` |
| `SECRET_KEY` | Padrão de desenvolvimento aceito | **Obrigatória** — a aplicação se recusa a iniciar sem ela |
| Cookie de sessão | Sem atributo `Secure` (funciona em `http://localhost`) | `Secure` automático — **exige HTTPS** |
| Banco padrão | SQLite (`reservation.db` na raiz) | PostgreSQL (`DATABASE_URL`) |
| Rate limiting | Ativo (memória) | Ativo (Redis, se houver mais de um worker) |

> 🔑 **Regra de ouro:** `FLASK_DEBUG` é a chave que destrava o modo
> desenvolvedor. Sem ela, o sistema assume que está em produção e aplica todas
> as exigências de segurança — inclusive se você estiver na sua máquina.

---

## 🧰 Preparação do ambiente

### Pré-requisitos

- **Python 3.8 ou superior** (`python --version`)
- **pip** e **git**
- **Internet** — algumas telas dependem de serviços externos (clima do totem,
  importação de feriados, busca de endereço); o restante do sistema funciona
  offline. Detalhes na [seção de APIs externas](#-erros-comuns-e-soluções).

### Passo a passo

```bash
# 1. Clone o repositório
git clone https://github.com/jmisturini/SIGerE.git
cd SIGerE

# 2. Crie e ative o ambiente virtual
python -m venv venv

# Linux/macOS:
source venv/bin/activate

# Windows (Git Bash):
source venv/Scripts/activate

# Windows (PowerShell):
# venv\Scripts\Activate.ps1

# 3. Instale as dependências (versões fixadas no requirements.txt)
pip install -r requirements.txt

# 4. Crie o schema do banco (Alembic — NÃO é criado no boot)
flask --app run db upgrade

# 5. Popule o banco — escolha UMA opção:
flask --app run seed          # admin padrão (admin/admin123) + pergunta sobre dados de demonstração
# ou
flask --app run seed-admin    # apenas o admin, com senha definida por você (implantação real)
```

> 📝 **Comandos da CLI não exigem `SECRET_KEY` nem `FLASK_DEBUG`** — a verificação
> de chave secreta vale apenas para quem *serve requisições HTTP* (`python run.py`,
> Gunicorn), pois é o único lugar onde existem cookies de sessão para proteger.

### Sobre o Windows

- O **Gunicorn não é instalado** em desenvolvimento (não funciona em Windows);
  ele entra em cena apenas no servidor Linux de produção — o `requirements.txt`
  propositadamente não o inclui.
- Os comandos `flask --app run ...` funcionam igualmente no Git Bash,
  PowerShell e CMD; só a forma de exportar variáveis de ambiente muda
  (veja a [próxima seção](#como-ativar-em-cada-sistema)).

---

## 🐞 O modo debug (`FLASK_DEBUG`)

### O que muda no modo debug

Com `FLASK_DEBUG=true`, três comportamentos são alterados em
`app/__init__.py` e `run.py`:

1. **Debugger do Werkzeug ativo** — erros não tratados abrem uma página de
   traceback navegável no navegador, com variáveis de cada frame e console
   Python interativo (protegido por PIN exibido no terminal). Nada disso
   existe fora do modo debug: erros mostram a página 500 amigável.
2. **Recarregamento automático (reloader)** — o servidor reinicia sozinho ao
   detectar mudança em qualquer arquivo `.py`, dispensando Ctrl+C a cada edição.
3. **Exigências de produção relaxadas** — o `SECRET_KEY` padrão de
   desenvolvimento (`dev-secret-key-change-in-production`) é aceito, e o cookie
   de sessão **não** recebe o atributo `Secure`, permitindo login em
   `http://localhost` (sem HTTPS).

Fora do modo debug, quem serve requisições sem um `SECRET_KEY` real recebe um
`RuntimeError` no boot (fail-fast): com a chave padrão seria possível forjar
cookies de sessão, então o sistema prefere não subir.

> 💡 O valor aceito é tolerante: `1`, `true`, `yes`, `on` em qualquer
> combinação de maiúsculas/minúsculas e com espaços nas bordas funcionam
> (`set FLASK_DEBUG=true ` do CMD deixa espaço final — está coberto).

### Como ativar em cada sistema

```bash
# Linux / macOS (bash, zsh):
export FLASK_DEBUG=true

# Windows PowerShell:
$env:FLASK_DEBUG="true"

# Windows CMD:
set FLASK_DEBUG=true

# Windows Git Bash:
export FLASK_DEBUG=true

# Em seguida, sirva a aplicação:
python run.py
```

> A variável vale **para a sessão do terminal atual**. Abrindo um terminal
> novo, exporte de novo (ou use um arquivo `.env` — próxima seção).

### Arquivo `.env` — o que o Flask lê e o que não lê

O `requirements.txt` inclui o `python-dotenv`, e o **comando `flask` carrega
automaticamente** um arquivo `.env` na raiz do projeto. Ou seja:

```bash
# .env na raiz do projeto
FLASK_DEBUG=true
# SECRET_KEY=...   # desnecessário em desenvolvimento
```

> ⚠️ O `.env` **não está no `.gitignore`** do repositório. Se você criar um com
> valores sensíveis, adicione `.env` ao seu `.gitignore` local ou não o commite.

| Como você inicia | Lê o `.env` automaticamente? |
|------------------|:----------------------------:|
| `flask --app run db upgrade`, `seed`, etc. | ✅ Sim (via `flask` CLI + python-dotenv) |
| `flask --app run run --debug` | ✅ Sim |
| `python run.py` | ❌ **Não** — nenhum `load_dotenv()` é chamado no `run.py` |

Na prática, há duas rotinas confortáveis:

```bash
# Opção A — exportar no terminal e usar python run.py:
export FLASK_DEBUG=true
python run.py

# Opção B — deixar no .env e usar a CLI do Flask (equivalente):
flask --app run run --debug
```

> ⚠️ **Pegadinha clássica:** criar um `.env` com `FLASK_DEBUG=true` e rodar
> `python run.py` — o arquivo é ignorado e o sistema sobe em "modo produção",
> chegando a recusar o boot por falta de `SECRET_KEY`. Nesse caso, exporte a
> variável no terminal ou troque para `flask --app run run --debug`.

---

## 🗄️ Banco de dados local

- **Padrão:** SQLite em `reservation.db`, na raiz do repositório. O caminho é
  montado em `app/config.py` e pode ser sobrescrito por `DATABASE_URL`.
- **Não versionado:** `*.db` está no `.gitignore` — o banco contém hashes de
  senha e dados locais; cada desenvolvedor tem o seu.
- **Schema versionado:** quem cria as tabelas é o Alembic (`flask --app run db
  upgrade`), **nunca** o boot da aplicação. Se o banco estiver vazio ou fora do
  fluxo de migrações, o boot apenas avisa no terminal e orienta o comando:

  ```
  ⚠️  Banco de dados vazio: rode "flask --app run db upgrade" para criar o schema
      e "flask --app run seed" para os dados iniciais.
  ```

- **Recriar do zero** (descartar tudo e começar de novo):

  ```bash
  rm reservation.db            # Windows: del reservation.db
  flask --app run db upgrade
  flask --app run seed         # ou seed-admin
  ```

- **Testar com PostgreSQL local** (recomendado antes de mexer em consultas que
  dependem de locks — ver [FAQ](#-perguntas-frequentes)):

  ```bash
  export DATABASE_URL="postgresql://usuario:senha@localhost:5432/sigere_dev"
  flask --app run db upgrade
  ```

- **Permissões/papéis novos:** o boot executa um `sync-permissions` silencioso
  e idempotente sempre que o banco já tem a tabela `permissions` — módulos
  novos passam a funcionar sem passo manual.

- **Uploads da Cozinha:** os `.docx` enviados ficam em `instance/uploads/`
  (fora de `static/`, fora do git — a pasta `instance/` inteira é ignorada).

---

## 🔁 Migrações durante o desenvolvimento

O schema vive em `migrations/versions/` e é comittado no repositório. Ao
**alterar modelos** em `app/models.py`:

```bash
# 1. Gere a migração (compara modelos × banco configurado em DATABASE_URL)
flask --app run db migrate -m "descrição curta da mudança"

# 2. REVISE o arquivo gerado em migrations/versions/
#    (o autogenerate erra com defaults, removals e tipos SQLite — nunca aplique às cegas)

# 3. Aplique no seu banco e rode os testes
flask --app run db upgrade
python -m unittest discover -s tests
```

Regras da casa:

- **Toda migração gerada vai junto com o código** que a exige, no mesmo commit/PR.
- Nunca edite uma migração **já aplicada** por outros desenvolvedores; se
  precisar corrigi-la, gere uma nova por cima.
- Bancos criados antes do Alembic (schema atualizado, mas sem
  `alembic_version`) entram no fluxo com `flask --app run db stamp head`.

---

## ⌨️ CLI de manutenção

Todos os comandos usam `flask --app run <comando>` (o `--app run` aponta para o
módulo `run.py`, onde vive a factory `create_app()`).

| Comando | O que faz | Observações |
|---------|-----------|-------------|
| `db upgrade` | Aplica as migrações pendentes (cria o schema do zero num banco vazio) | Seguro com múltiplos processos |
| `db migrate -m "..."` | Gera um arquivo de migração a partir dos modelos | Revise antes de aplicar |
| `db stamp head` | Marca o banco como "na versão atual" sem aplicar nada | Para bancos legados pré-Alembic |
| `seed` | Cria permissões/papéis + admin (`admin`/`admin123`) e **pergunta interativamente** se quer dados de demonstração | Recusa-se a rodar em banco já populado |
| `seed-admin` | Cria **apenas** o admin, com senha digitada (mín. 8 caracteres, oculta) | Fluxo de implantação real; sem demonstração |
| `seed-unidades` | Cadastra/atualiza as unidades do Senac SC a partir de `docs/unidades-senac-sc.json` | Idempotente; opção `--file CAMINHO` aceita outro JSON |
| `sync-permissions` | Cria permissões/papéis ausentes e vincula os códigos de `ROLES_CONFIG` | Idempotente; **nunca remove** vínculos existentes |

> `seed-unidades` ignora registros sem `cadastro_sugerido` no JSON (ex.: Direção
> Regional) e não altera coordenadas de clima — essas são editadas no painel.

---

## ▶️ Executando o servidor

```bash
python run.py
```

- Endereço: **http://localhost:5000** (só acessível da própria máquina).
- O modo debug é lido de `FLASK_DEBUG` (função `debug_enabled()`); com ele
  ativo, o reloader e o debugger ficam de pé ao lado do servidor.
- Sem `FLASK_DEBUG` e sem `SECRET_KEY` real, o boot falha com `RuntimeError`
  (comportamento de produção — intencional).

### Alternativa pela CLI do Flask

```bash
flask --app run run --debug          # com debugger/reloader
flask --app run run --host=0.0.0.0   # expõe na rede local (ex.: testar o totem num tablet/celular)
```

A forma `flask run` também carrega o `.env` automaticamente e aceita as mesmas
variáveis; a porta padrão é a mesma 5000.

### URLs úteis no dia a dia

| URL | O que é |
|-----|---------|
| `/` | Home pública |
| `/login` | Login (rate limit: 5 tentativas/min por IP) |
| `/dashboard` | Dashboard interno (após login) |
| `/calendar` | Calendário FullCalendar |
| `/admin/` | Painel administrativo |
| `/kitchen/fichas` · `/kitchen/preparacoes` · `/kitchen/compras` | Módulo Cozinha |
| `/vt/` · `/payments` | Vale Transporte · Horas Extras |
| `/totem/?unity=<id>` | Totem digital (tema automático, clima) |
| `/cronograma` · `/buscar-aula` · `/search` | Portal público (sem login) |
| `/api/v1/reservations` | API REST de leitura — [documentação completa](api-reservas.md) |

---

## 👤 Contas de demonstração

Criadas pelo `flask --app run seed` **quando você responde "y"** à pergunta de
população. As contas já vêm com `force_password_change=False` (não pedem troca
de senha no primeiro login — convenientes para testes).

| Perfil | Usuário | Senha | Permissões |
|--------|---------|-------|------------|
| **Super Administrador** | `admin` | `admin123` | Acesso total (`*`) — criado sempre, mesmo sem demonstração |
| **Professor** | `teacher1` … `teacher80` | `teacher123` | Reservas, próprios pagamentos, Cozinha |
| **Funcionário** | `employee1` … `employee20` | `employee123` | Visualização de salas/cursos, próprias reservas, Cozinha |

A demonstração cria 3 unidades (Centro, Norte e Sul), 100 usuários, 6
categorias de sala, 29 salas, 50 cursos, 50 disciplinas, 20 reservas e
lançamentos de hora extra — dados distribuídos entre as unidades, úteis para
testar o isolamento multi-unidade.

> ⚠️ Contas de demonstração **nunca** devem existir no servidor de produção;
> lá use `seed-admin`. Ver [implantação](implantacao-producao.md).

---

## 🧪 Testes automatizados

A suíte usa **`unittest`** (padrão do Python — nenhuma dependência extra) e
ficam em `tests/`. Cada teste sobe uma aplicação própria com **SQLite em
arquivo temporário**, CSRF e rate limiting desligados e `SECRET_KEY` de teste
(classe `TestConfig` de `tests/test_api_reservations.py`).

```bash
# Suíte completa (saída verbosa):
python -m unittest discover -s tests -v

# Suíte completa (saída enxuta):
python -m unittest discover -s tests

# Um módulo específico:
python -m unittest tests.test_kitchen_parser -v

# Um único teste:
python -m unittest tests.test_api_reservations.ApiReservationsTestCase.test_anonimo_lista_apenas_campos_publicos_e_aprovadas -v
```

Resultado esperado: **`OK`** ao final (eventuais `skipped` são casos
condicionais a ambiente e não indicam falha). A suíte completa roda em cerca de
um minuto.

### O que a suíte cobre

| Área | Módulo(s) de teste |
|------|--------------------|
| API REST de reservas (`/api/v1`) — payloads público/completo, filtros, escopo multi-unidade, erros | `test_api_reservations.py` |
| Tokens da API no painel admin (gerar, revogar, reativar) | `test_api_tokens_admin.py` |
| Cozinha — parser de fichas `.docx` e requisição de compra | `test_kitchen_parser.py`, `test_kitchen_scale.py` |
| Reservas — conflitos, disponibilidade, séries, passado | `test_classroom_availability.py`, `test_reservations_past.py` |
| Categorias dinâmicas e edição | `test_dynamic_categories.py`, `test_category_edit.py` |
| Financeiro (hora extra e Vale Transporte) | `test_payments.py` |
| CLI e seeds (admin, unidades) | `test_seed_admin.py`, `test_seed_unidades.py` |
| Autenticação — registro, troca de senha | `test_user_registration.py`, `test_change_password.py` |
| Formulários de sala e checklist de configuração | `test_room_form.py`, `test_setup_checklist.py` |
| Identificadores automáticos (códigos de sala) | `test_auto_identifiers.py` |

### Convenções ao escrever testes

- Um banco **novo por teste** (`tempfile.mkstemp`) — testes são independentes e
  não sujam o seu `reservation.db`.
- Para simular produção (cookie `Secure`, bloqueio de `SECRET_KEY` padrão),
  instancie `create_app(Config)` sem ajustes; o padrão da suíte é herdar de
  `TestConfig`.
- Ao adicionar permissões/papéis nos testes, siga o padrão existente (criar
  `Permission`, vincular a uma `Role` nova com nome único do teste).

---

## 🔍 Depuração no dia a dia

### Debugger do Werkzeug

Com `FLASK_DEBUG=true`, qualquer exceção não tratada abre o traceback
interativo. Dicas:

- O ícone de **console** em cada frame abre um REPL com as variáveis locais daquele ponto.
- Para parar no meio de uma rota, coloque `import pdb; pdb.set_trace()` (ou
  `breakpoint()`) na linha desejada — no terminal que serve a aplicação.
- O console do navegador **exige o PIN** mostrado no terminal no boot
  ("Debugger PIN"); ele impede que terceiros executem código na sua máquina.

### Logs e avisos do boot

O boot imprime avisos direcionados no `stderr` — eles são o primeiro lugar para
olhar quando algo "parece vazio":

| Aviso | Significado | Ação |
|-------|-------------|------|
| `⚠️ Banco de dados vazio: rode "flask --app run db upgrade" ...` | Banco novo/sem tabelas | `db upgrade` + `seed` |
| `⚠️ Banco existente sem versionamento Alembic ...` | Schema existe, mas não há `alembic_version` | `db stamp head` (schema OK) ou recriar do zero |

### Inspecionando estado com o shell

```bash
flask --app run shell
```

Dentro do shell (contexto de aplicação pronto):

```python
from app.models import Reservation, User, Unity
User.query.count()
Reservation.query.filter_by(status='pending').all()[:5]
Unity.query.all()
```

### Variáveis de configuração relevantes em dev

| Variável | Padrão | Efeito |
|----------|--------|--------|
| `FLASK_DEBUG` | vazio | Liga debugger, reloader e relaxa exigências de produção |
| `DATABASE_URL` | SQLite local | Troca o banco (ex.: PostgreSQL de teste) |
| `SECRET_KEY` | `dev-secret-key-change-in-production` | Só precisa ser real fora do modo debug |
| `RATELIMIT_STORAGE_URI` | `memory://` | Em dev, 1 processo → memória basta |
| `TOTEM_LATITUDE` / `TOTEM_LONGITUDE` | São Paulo | Fallback do clima; por unidade é configurado no painel |

---

## 🚨 Erros comuns e soluções

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| `RuntimeError: SECRET_KEY não configurada...` no boot | `python run.py` (ou `flask run`) **sem** `FLASK_DEBUG` e sem `SECRET_KEY` | `export FLASK_DEBUG=true` (dev) ou defina `SECRET_KEY` real |
| Login "não funciona" / sessão não persiste em `http://localhost` | `FLASK_DEBUG` desligado → cookies com `Secure` → navegador rejeita em HTTP puro | Ative `FLASK_DEBUG=true` (ou sirva sob HTTPS) |
| `.env` é ignorado ao rodar `python run.py` | `python run.py` não carrega `.env` (só a CLI `flask` carrega) | Exporte as variáveis no terminal ou use `flask --app run run --debug` |
| Página "Sua sessão expirou ou o formulário já não é válido" ao salvar formulário | Token CSRF ausente/expirado (sessão velha, aba dormindo) | Recarregue a página e reenvie — comportamento esperado |
| `429` / "Muitas tentativas em pouco tempo" no login | Limite de 5 tentativas/min por IP (Flask-Limiter) | Aguarde 1 minuto; o contador é em memória e some ao reiniciar o servidor |
| `⚠️ Banco de dados vazio` a cada boot | Esqueceu `db upgrade`/`seed` | Veja [banco de dados local](#-banco-de-dados-local) |
| `IntegrityError` / tabela faltando após `git pull` | Migração nova não aplicada | `flask --app run db upgrade` |
| Clima do totem "N/A", feriados não importam, busca de endereço falha | Sem internet (serviços: Open-Meteo, BrasilAPI, Nominatim) | Restabeleça a conexão; o resto do sistema funciona offline |
| `413 Request Entity Too Large` ao subir `.docx` | `MAX_CONTENT_LENGTH` = 16 MB | Arquivo maior que o limite — reduza/splite |
| Erro ao salvar planilhas exportadas abertas no Excel | Arquivos de lock `~$*.xlsx` | Feche o arquivo aberto antes de re-exportar |
| Comportamento de concorrência diferente em dev | SQLite não implementa `SELECT ... FOR UPDATE`/advisory locks (recursos PostgreSQL) | Valide cenários de double-booking concorrente com `DATABASE_URL` apontando para PostgreSQL |
| Totem/portal mostra clima de São Paulo | Unidade sem coordenadas próprias (cai no fallback global) | Configure no painel: Unidades → Editar → clima |

---

## ✅ Checklist antes do commit

1. `python -m unittest discover -s tests` termina em **OK**.
2. Se mexeu em `app/models.py`: migração gerada (`db migrate`), **revisada**,
   aplicada (`db upgrade`) e comittada junto.
3. Se criou permissões/papéis novos: códigos em `app/commands.py`
   (`PERMISSION_DATA`/`ROLES_CONFIG`) — o `sync-permissions` silencioso do boot
   e o comando explícito cuidam do resto.
4. Nada de `*.db`, `instance/` ou `~$*.xlsx` no commit (`.gitignore` cobre, mas
   confira `git status`).
5. Novos endpoints com `@limiter.limit` quando expostos sem login (padrão da
   API: `120 per minute`).
6. Textos de interface em pt-BR, consistente com o restante do sistema.
7. Documentação atualizada quando a mudança altera comportamento documentado
   (README, [API](api-reservas.md), [produção](implantacao-producao.md) ou este guia).

---

## ❓ Perguntas frequentes

**Preciso de PostgreSQL para desenvolver?**
Não — SQLite cobre o dia a dia. Use PostgreSQL quando for tocar em consultas
que dependem de locks (`SELECT ... FOR UPDATE`, advisory locks do agendamento),
pois o SQLite não os implementa e o comportamento concorrente local será
diferente do de produção.

**Posso rodar com `flask --app run run` em vez de `python run.py`?**
Sim, são equivalentes para desenvolvimento. A `flask run` adiciona o carregamento
automático do `.env` e flags prontas (`--debug`, `--host`); o `python run.py` lê
o modo debug de `FLASK_DEBUG` e fixa a porta 5000.

**Os dados de demonstração aparecem no meu banco de testes?**
Não. Os testes criam bancos temporários próprios e populam apenas o que cada
caso precisa — o `reservation.db` local nunca é tocado pela suíte.

**Por que o boot cria permissões sozinho se o `sync-permissions` também existe?**
O boot roda o mesmo algoritmo em modo silencioso e idempotente para bancos já
existentes — é uma conveniência para módulos novos. O comando explícito continua
existindo para o fluxo de atualização documentado e para executar verbosamente.

**O debugger do Werkzeug é perigoso?**
Fora da sua máquina, sim — quem acessar um erro com o debugger aberto poderia
executar código (o PIN é a barreira). Nunca ative `FLASK_DEBUG` em servidor
acessível por terceiros; produção usa Gunicorn + Nginx sem debugger.

**Onde vejo os arquivos `.docx` que enviei na Cozinha?**
Em `instance/uploads/`. Eles são servidos apenas pela rota autenticada de
download (`/kitchen/fichas/<id>/download`) — nunca por URL estática.

**Como simulo dois usuários ao mesmo tempo?**
Duas janelas anônimas/abas com sessões separadas (uma sessão por perfil de
navegador). Para testar concorrência de gravação de reservas de verdade
(locks), use PostgreSQL e duas máquinas/terminais — com SQLite o cenário não é
reproduzível fielmente.
