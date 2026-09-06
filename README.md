<div align="center">

# 🏫 SIGerE — Sistema Integrado de Gerenciamento Educacional

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5-7952B3?logo=bootstrap&logoColor=white)](https://getbootstrap.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Plataforma web completa para gestão de reservas de salas, cronogramas acadêmicos, pagamentos docentes e operação de cozinha em instituições de ensino — com suporte a múltiplas unidades educacionais.**

</div>

---

## 📋 Índice

- [Visão Geral](#-visão-geral)
- [Funcionalidades](#-funcionalidades)
- [Tecnologias](#-tecnologias)
- [Instalação](#-instalação)
- [Configuração](#-configuração)
- [Deploy em Produção (Gunicorn + Nginx)](#-deploy-em-produção-gunicorn--nginx)
- [Uso](#-uso)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [APIs Externas](#-apis-externas)
- [Contas de Demonstração](#-contas-de-demonstração)
- [Permissões e Papéis](#-permissões-e-papéis)
- [Catálogo de Permissões](#-catálogo-de-permissões)
- [Segurança](#-segurança)
- [Licença](#-licença)

---

## 🎯 Visão Geral

O **SIGerE** é um sistema web desenvolvido em **Flask** para instituições educacionais que precisam gerenciar de forma integrada:

- 🏛️ **Reservas de espaços físicos** — salas de aula, auditórios, laboratórios de informática/saúde, cozinhas
- 👨‍🏫 **Cronogramas de professores** com detecção automática de conflitos de horário
- 💰 **Pagamentos docentes** — remuneração base semestral, aditivos e horas extras
- 🍳 **Cozinha** — fichas técnicas (.docx), preparações e requisição de compra
- 📺 **Totens digitais** para corredores com exibição em tempo real de ocupação de salas
- 📆 **Calendário interativo** com filtros avançados e visualização mensal
- 🌐 **Portal público** com cronograma do dia e busca de aula para alunos
- 🏢 **Multi-unidade** — dados isolados por unidade educacional (salas, reservas, cursos, feriados, cozinha), com alternância de unidade para administradores

O sistema possui **controle de acesso baseado em papéis (RBAC)** com permissões granulares, tema claro/escuro persistente, exportação de relatórios em PDF/Excel, layout responsivo (mobile/tablet/desktop) e seed opcional de dados de demonstração.

---

## ✨ Funcionalidades

### 🏢 Multi-unidade Educacional
- **CRUD de unidades** no painel (Painel → Unidades): nome, sigla e ativação/desativação
- **Clima por unidade:** cada unidade tem latitude/longitude e cidade exibida próprias, editáveis no formulário com **busca de endereço** (autocompletar via OpenStreetMap/Nominatim)
- **Seletor de unidade** no topo para quem tem `unity:switch` ou `*` (armazenado na sessão); usuários comuns ficam fixados na própria unidade
- **Isolamento de dados:** salas, reservas, cursos, disciplinas, feriados, usuários e módulo de Cozinha são escopados pela unidade ativa
- **Totem e portal público por unidade:** `/totem/?unity=<id>` e páginas públicas aceitam a unidade como parâmetro

### 📅 Gestão de Reservas
- **Detecção inteligente de conflitos:** bloqueio automático de double-booking de salas
- **Proteção contra reservas concorrentes:** lock por (sala, data) e revalidação atômica na gravação — em PostgreSQL, `SELECT ... FOR UPDATE` e advisory lock transacional evitam que duas requisições simultâneas reservem o mesmo slot (padrão TOCTOU)
- **Conflito de professor:** se um professor já está alocado em outra sala no mesmo horário, a reserva é criada como **PENDENTE** e aguarda aprovação administrativa
- **Restrições de calendário:**
  - ❌ Domingos bloqueados
  - ❌ Feriados bloqueados (cadastrados por unidade; importáveis da BrasilAPI)
  - ⚠️ Sábados: apenas manhã e tarde (início e término até 18h)
- **Repetição de reservas:** crie séries de aulas com opções de "mesmo dia da semana" e "pular fins de semana" (intervalo limitado a 180 dias por lote)
- **Gerenciamento de série:** edite ou cancele/exclua em lote as reservas geradas por uma repetição (horário, sala, título — com validação de conflito por data) na opção **"Gerenciar Série"** da reserva ou da tela de repetição
- **Auto-aprovação:** reservas sem conflitos são aprovadas instantaneamente
- **Ciclo de vida:** aprovar, cancelar (status `cancelled` mantém histórico) e excluir permanentemente (admins)
- **Filtros de disponibilidade:** salas disponíveis agora, em data/período específico ou por categoria

### 🏛️ Gestão de Salas e Categorias
- **Categorias com CRUD completo** no painel (Painel → Categorias): nome, sigla e código
- **Categorias padrão da seed:** Sala de Aula (`SA`), Auditório (`AU`), Cozinha (`CO`), Laboratório de Informática (`LI`), Laboratório de Saúde (`LS`)
- **Código automático:** geração de códigos no formato `SA101`, `AU101`, `LI105`, `LS301` (sigla da categoria + número da sala)
- **Atributos da sala:** capacidade, andar, bloco, número e quantidade de computadores
- **Visualização mensal:** calendário de ocupação por sala com navegação entre meses
- **Exportação:** PDF (landscape A4) da listagem e da disponibilidade mensal
- **Ativação/desativação** de salas e categorias sem exclusão

### 👥 Gestão de Usuários (Painel Admin)
- **Perfis distintos:**
  - **Professor:** departamento, matrícula, unidade
  - **Funcionário:** setor, função, unidade, com opção de "também atuar como professor"
- **Busca e filtros:** filtrar usuários por nome ou tipo de perfil, com paginação
- **Reset de senha pelo admin:** gera uma senha temporária aleatória (exibida uma única vez) e força a troca no próximo login
- **Segurança:** forçar troca de senha no primeiro login ou após reset administrativo
- **Ativação/desativação:** controle de status do usuário sem exclusão de dados
- **Proteção de auto-desativação:** administradores não podem desativar a própria conta

### 📚 Estrutura Acadêmica
- CRUD completo de **Cursos** e **Disciplinas** (Painel → Cursos / Disciplinas)
- Vinculação de reservas a curso, disciplina e professor específicos
- Ativação/desativação de registros sem exclusão

### 🎓 Dashboard Interno (`/dashboard`)
- Cronograma do dia separado por **auditorios** e **salas de aula**
- Destaque para o **período atual** (manhã/tarde/noite) com as reservas aprovadas em andamento
- Escopado na unidade ativa

### 🌤️ Totem / Quiosque Digital (`/totem`)
- Interface otimizada para **TVs de corredor**
- **Tema automático:** claro durante o dia, escuro à noite
- **Clima em tempo real** via Open-Meteo, usando a localização da unidade exibida
- Agrupamento de salas ocupadas por **andar**
- Exibição de reservas de auditórios para os próximos 7 dias
- Alternância rápida de unidade por parâmetro (`?unity=<id>`) — uma TV por unidade

### 🗓️ Calendário Interativo (`/calendar`)
- Integração com **FullCalendar** (visões: dia, semana, mês)
- Filtros por sala, professor, curso, disciplina e período (manhã/tarde/noite)
- API JSON (`/calendar/api/events`) com intervalo de datas obrigatório e filtros combináveis
- Eventos coloridos com detalhes ao clicar (link para a reserva)
- Adaptação automática ao tema claro/escuro

### 💰 Gestão de Pagamentos Docentes
- **Remuneração Base (Semestral):** lançamento por professor, curso, carga horária semanal e código orçamentário
- **Aditivos:** horas adicionais vinculadas a um lançamento base existente
- **Horas Extras:** com nível de ensino, valor hora, turno e múltiplas datas
- **Regras de negócio:**
  - Bloqueio de lançamentos em meses anteriores
  - Bloqueio de edição após 30 dias
  - Bloqueio de exclusão após 180 dias
  - Horas extras só até o dia 25 do mês corrente
- **Exportação Excel:** planilhas formatadas com modelos pré-definidos (`baseplanilhaCHsemestral.xlsx` para base, `base_pagamento_extra.xlsx` para horas extras)

### 🍳 Cozinha (`/kitchen`)
- **Ficha Técnica:** envio de múltiplos arquivos `.docx` de fichas técnicas operacionais de uma vez; o sistema lê o conteúdo (nome da preparação, equipamentos, utensílios, tempo de preparo, rendimento, tabelas de insumos, modo de preparo e notas técnicas) e um botão **Salvar Ficha Técnica** gera a preparação; também é possível **criar a ficha manualmente** pelo botão "Criar Ficha Técnica", no mesmo modelo
- **Preparações:** cada ficha salva gera uma receita visualizável em **cards ou lista** (à escolha do usuário, persistida no navegador), com busca por nome; a visualização completa traz equipamentos, utensílios, tempo, rendimento, ingredientes por preparação (especificação, quantidade e unidade), modo de preparo geral, alergênicos, observações e referências; os ingredientes podem ser **editados e ativados/desativados** — desativados, ficam de fora da requisição de compra; há **recálculo das quantidades por porções desejadas** (base = menor rendimento informado, ex.: "4 a 6 porções" usa 4) e **edição de todos os campos da preparação**
- **Compras:** seleção de múltiplas preparações e **soma dos ingredientes por similaridade** (acentos, plurais e parênteses normalizados), com conversão automática de unidades (g→KG, ml→L, un→UN) e exportação da **requisição de compra em Excel** preenchendo o modelo `app/static/templates_excel/base_planilha_compras.xlsx` ("REQUISIÇÃO DE COMPRA - GASTRONOMIA", com aba de centros de custo); a coluna OBSERVAÇÃO é exportada em branco, com as linhas da grade, para ser preenchida posteriormente
- **Multi-unidade:** fichas e preparações são isoladas por unidade educacional
- **Armazenamento seguro:** os `.docx` enviados ficam em `instance/uploads/`, fora de `static/`, servidos apenas por rota autenticada de download
- **Permissões:** `kitchen:read`, `kitchen:sheet_create`, `kitchen:sheet_delete`, `kitchen:shopping_export`

### 🌐 Portal Público
- **Página inicial** com links para login, calendário, cronograma e buscas
- **Cronograma do dia** (`/cronograma`): aulas aprovadas do dia agrupadas por período (manhã/tarde/noite)
- **Busca de aula do aluno** (`/buscar-aula`): pesquisa por título da aula, curso/turma, disciplina, professor ou sala
- **Busca de salas e professores** (`/search`): salas por nome/código e professores por nome
- Seletor de unidade nas páginas públicas (`?unity=<id>`)

### 🎨 UI/UX
- **Tema Claro/Escuro:** alternância global com persistência no `localStorage`
- **Design responsivo:** Bootstrap 5, todas as páginas adaptadas a mobile, tablet e desktop
- **Interface em Português:** todo o sistema localizado para pt-BR
- **Paginação** reutilizável em listagens (`_pagination.html`)

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|--------|-----------|
| **Backend** | Python 3.8+, Flask 3.x, Flask-SQLAlchemy, Flask-Login, Flask-WTF |
| **Banco de Dados** | SQLite (padrão), compatível com PostgreSQL (driver incluído) |
| **Migrações** | Flask-Migrate (Alembic) |
| **Frontend** | Bootstrap 5, Bootstrap Icons, Jinja2, FullCalendar |
| **Relatórios** | FPDF2 (PDF), OpenPyXL (Excel) |
| **Rate limiting** | Flask-Limiter |
| **Produção** | Gunicorn (WSGI) + Nginx (proxy/TLS) |
| **APIs Externas** | [Open-Meteo](https://open-meteo.com/) (clima), [BrasilAPI](https://brasilapi.com.br/) (feriados), [Nominatim/OpenStreetMap](https://nominatim.org/) (geocodificação) |

---

## 🚀 Instalação

### Pré-requisitos
- Python 3.8 ou superior
- pip

### Passo a passo

```bash
# 1. Clone o repositório
git clone https://github.com/jmisturini/SIGerE.git
cd SIGerE

# 2. Crie e ative um ambiente virtual
python -m venv venv

# Linux/macOS:
source venv/bin/activate

# Windows:
venv\Scripts\activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Habilite o modo desenvolvimento (ou defina uma SECRET_KEY)
# Linux/macOS:
export FLASK_DEBUG=true
# Windows PowerShell:
# $env:FLASK_DEBUG="true"

# 5. Crie o schema do banco (Flask-Migrate/Alembic)
flask --app run db upgrade

# 6. Popule o banco (cria o admin; dados de demonstração são opcionais)
flask --app run seed

# 7. Execute a aplicação
python run.py
```

A aplicação estará disponível em: **http://localhost:5000**

> **Nota:** o schema do banco é versionado com Flask-Migrate/Alembic (não é criado automaticamente no boot). O boot apenas avisa no terminal quando o banco está vazio ou fora do fluxo de migrações.

> **Nota:** o comando `seed` cria sempre o administrador (`admin`/`admin123`) e, em seguida, **pergunta interativamente** se você quer popular dados de demonstração (responda `y` para receber também as contas `teacher1` e `employee1`). Veja detalhes em [Contas de Demonstração](#-contas-de-demonstração).

> **Atualizando uma instalação existente:** após `git pull`, execute `flask --app run db upgrade` (aplica migrações de schema novas) e `flask --app run sync-permissions` (permissões de módulos novos).

---

## ⚙️ Configuração

As configurações ficam em `app/config.py` e podem ser sobrescritas por variáveis de ambiente:

```python
# app/config.py
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        f'sqlite:///{os.path.join(BASE_DIR, "reservation.db")}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Rejeita uploads/requisições maiores que 16 MB
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    # Mitiga CSRF em navegação cross-site em complemento ao token do Flask-WTF
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Rate limiting (memória basta para 1 processo; para múltiplos workers, use Redis)
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    # Fallback global da localização do clima (totem/portal)
    TOTEM_LATITUDE = float(os.environ.get('TOTEM_LATITUDE', '-23.5505'))
    TOTEM_LONGITUDE = float(os.environ.get('TOTEM_LONGITUDE', '-46.6333'))
```

### Variáveis de ambiente recomendadas (produção)

```bash
export SECRET_KEY="sua-chave-secreta-forte-aqui"
export DATABASE_URL="postgresql://user:pass@localhost/sigere"
export RATELIMIT_STORAGE_URI="redis://localhost:6379/0"   # com múltiplos workers
```

> **Obrigatório em produção:** sem `SECRET_KEY` definida (fora do modo debug), a aplicação se recusa a iniciar. Além disso, os cookies de sessão recebem o atributo `Secure` automaticamente quando `FLASK_DEBUG != true` — sirva a aplicação atrás de HTTPS.

### Configurar localização do clima (Totem e portal)

As unidades ficam distantes entre si, então **cada unidade tem a própria
localização do clima**, definida no painel: **Painel → Unidades → Editar**.
No formulário, busque as coordenadas pelo endereço (preenchimento automático
via OpenStreetMap/Nominatim) ou informe latitude, longitude e a cidade exibida
manualmente. O totem de cada unidade (`/totem/?unity=<id>`) e o portal usam as
coordenadas da unidade ativa.

As variáveis abaixo funcionam apenas como **fallback global** para unidades
sem coordenadas próprias:

```bash
export TOTEM_LATITUDE="-23.5505"    # Latitude padrão (fallback)
export TOTEM_LONGITUDE="-46.6333"   # Longitude padrão (fallback)
```

### Migrações de banco (Flask-Migrate/Alembic)

O schema é versionado no diretório `migrations/` (comittado no repositório). O boot da aplicação **não** altera o schema — quem aplica é o Alembic, de forma segura até com múltiplos workers.

| Situação | Comando |
|---|---|
| Instalação nova (banco vazio) | `flask --app run db upgrade` + `flask --app run seed` |
| Banco já no esquema atual, mas sem versionamento Alembic | `flask --app run db stamp head` |

Após **alterar modelos** em `app/models.py`, gere e aplique a migração:

```bash
flask --app run db migrate -m "descrição da mudança"   # gera o arquivo em migrations/versions/
flask --app run db upgrade                             # aplica no banco
```

O `db migrate` compara os modelos com o banco configurado em `DATABASE_URL` — revise o arquivo gerado em `migrations/versions/` antes de aplicar.

---

## 🚢 Deploy em Produção (Gunicorn + Nginx)

O servidor de desenvolvimento do Flask (`python run.py`) **não deve ser usado em produção**. A arquitetura recomendada é: **Nginx** (proxy reverso + arquivos estáticos + TLS) → **Gunicorn** (servidor WSGI) → aplicação Flask.

> **Nota:** o Gunicorn não está no `requirements.txt` porque não funciona em Windows (máquina de desenvolvimento). Instale-o apenas no servidor Linux.

### 1. Preparar o servidor

```bash
# Dependências do sistema (Debian/Ubuntu)
sudo apt update
sudo apt install python3-venv python3-pip nginx postgresql redis-server

# Código + ambiente virtual
sudo mkdir -p /var/www/sigere && sudo chown $USER /var/www/sigere
git clone https://github.com/jmisturini/SIGerE.git /var/www/sigere
cd /var/www/sigere
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt gunicorn

# Permissões: o Gunicorn precisa escrever o banco (se SQLite) e os uploads
sudo chown -R www-data:www-data /var/www/sigere/instance
```

### 2. Variáveis de ambiente

Crie o arquivo `/var/www/sigere/.env` (lido pelo `systemd` abaixo) — **nunca versionado**:

```bash
SECRET_KEY="gere-com: python3 -c 'import secrets; print(secrets.token_urlsafe(48))'"
DATABASE_URL="postgresql://sigere:senha-forte@localhost:5432/sigere"
TOTEM_LATITUDE="-23.5505"
TOTEM_LONGITUDE="-46.6333"
RATELIMIT_STORAGE_URI="redis://localhost:6379/0"
```

> **Clima:** as coordenadas acima são só o fallback global. A localização de
> cada unidade é configurada no painel (Unidades → Editar → "Clima no Totem").

> **Por que PostgreSQL?** O SQLite padrão serve para avaliação, mas em produção com múltiplos workers o recomendado é PostgreSQL (driver já incluído no `requirements.txt`). Além do desempenho, o módulo de agendamento usa `SELECT ... FOR UPDATE` e advisory locks do PostgreSQL para proteger reservas concorrentes entre processos.

> **Por que Redis no rate limit?** Com mais de um worker do Gunicorn, cada processo teria seu próprio contador em memória — o limite por IP ficaria N vezes mais frouxo. Com Redis, o contador é compartilhado.

### 3. Gunicorn via systemd

Crie `/etc/systemd/system/sigere.service`:

```ini
[Unit]
Description=SIGerE (Gunicorn)
After=network.target postgresql.service redis-server.service

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/sigere
EnvironmentFile=/var/www/sigere/.env
ExecStart=/var/www/sigere/venv/bin/gunicorn \
    --chdir /var/www/sigere \
    --bind unix:/run/sigere/sigere.sock \
    --workers 3 --threads 2 \
    --timeout 120 \
    --access-logfile /var/log/sigere/access.log \
    --error-logfile /var/log/sigere/error.log \
    run:app
ExecReload=/bin/kill -s HUP $MAINPID

[Install]
WantedBy=multi-user.target
```

```bash
# Socket dir e logs
sudo mkdir -p /run/sigere /var/log/sigere
sudo chown www-data:www-data /run/sigere /var/log/sigere

# Ativar e iniciar
sudo systemctl daemon-reload
sudo systemctl enable --now sigere
sudo systemctl status sigere   # deve estar "active (running)"
```

> **Workers:** use `--workers (2 x CPUs) + 1` como ponto de partida. O entrypoint é `run:app` — a variável `app = create_app()` já existe no `run.py`. Ao atualizar o código, `sudo systemctl reload sigere` aplica sem derrubar as requisições em andamento.

### 4. Nginx como proxy reverso

Crie `/etc/nginx/sites-available/sigere`:

```nginx
server {
    listen 80;
    server_name sigere.sua-instituicao.edu.br;
    # Redirecione todo o tráfego HTTP para HTTPS após emitir o certificado (passo 5)

    # Deve ser >= MAX_CONTENT_LENGTH da aplicação (16 MB)
    client_max_body_size 16m;

    # Arquivos estáticos servidos direto pelo Nginx (CSS, JS, modelos Excel)
    location /static/ {
        alias /var/www/sigere/app/static/;
        expires 7d;
        access_log off;
    }

    location / {
        proxy_pass http://unix:/run/sigere/sigere.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/sigere /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

> **Atenção:** o `proxy_set_header X-Forwarded-For` é o que permite o rate limiting do login contar por IP real do visitante. O diretório `instance/uploads/` (fichas técnicas) **não** é servido pelo Nginx de propósito — o acesso é exclusivamente pela rota autenticada da aplicação.

### 5. HTTPS (obrigatório)

Sem HTTPS o login **não funciona** em produção: fora do modo debug, a aplicação marca o cookie de sessão como `Secure` e o navegador o recusa em HTTP puro.

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d sigere.sua-instituicao.edu.br
```

Após emitir o certificado, descomente o redirecionamento 80→443 no bloco Nginx acima e adicione o bloco `listen 443 ssl` equivalente (o certbot faz isso automaticamente com `--nginx`).

### 6. Atualizando a aplicação

```bash
cd /var/www/sigere
sudo -u www-data git pull
sudo -u www-data venv/bin/pip install -r requirements.txt gunicorn
sudo -u www-data venv/bin/flask --app run db upgrade    # aplica migrações de schema
sudo systemctl restart sigere
# Se algum módulo novo trouxer permissões:
sudo -u www-data venv/bin/flask --app run sync-permissions
```

> Na **primeira** implantação, a rotina é: `db upgrade` → `seed` (opcional, dados de demonstração) → `db stamp head` se o banco já existia de versões anteriores ao Alembic → iniciar o serviço.

---

## 📖 Uso

### Fluxo típico de reserva

1. **Login** com uma conta de Professor ou Administrador
2. Acesse **Salas** e filtre por disponibilidade
3. Clique em **Reservar** ou acesse **Minhas Reservas → Nova Reserva**
4. Preencha sala, data, horário, curso, disciplina e professor
5. O sistema verifica conflitos automaticamente:
   - ✅ Sem conflitos → reserva **aprovada**
   - ⚠️ Professor ocupado → reserva **pendente** (requer aprovação admin)
   - ❌ Sala ocupada → **bloqueado**

Status possíveis da reserva: `approved` (aprovada), `pending` (aguardando aprovação por conflito de professor) e `cancelled` (cancelada — mantida no histórico).

### Alternar unidade ativa

Administradores com permissão `unity:switch` (ou `*`) veem o **seletor de unidade** no topo do sistema. Todas as telas — salas, reservas, cursos, feriados, cozinha — exibem os dados da unidade ativa.

### Importar feriados nacionais

1. Acesse o **Painel Administrativo → Feriados**
2. Clique em **Importar da BrasilAPI**
3. Informe o ano desejado
4. Os feriados nacionais brasileiros serão importados automaticamente (escopo da unidade ativa)

### Portal público (sem login)

| Página | URL | Conteúdo |
|--------|-----|----------|
| Início | `/` | Links para login, cronograma e buscas |
| Cronograma do dia | `/cronograma` | Aulas aprovadas do dia por período (manhã/tarde/noite) |
| Busca de aula | `/buscar-aula?q=` | Aula por título, curso, disciplina, professor ou sala |
| Busca de salas/professores | `/search?q=&type=classroom\|teacher` | Salas por nome/código, professores por nome |
| Totem | `/totem/?unity=<id>` | Display de corredor (clima, andares, auditórios) |

### Exportar relatórios

- **Salas:** `/classrooms/export_pdf` (PDF)
- **Disponibilidade mensal:** `/classrooms/<id>/export_availability` (PDF)
- **Pagamentos base:** `/payments/export/base` (Excel)
- **Horas extras:** `/payments/export/overtime` (Excel)
- **Requisição de compra:** `/kitchen/compras/export` (Excel, via seleção de preparações)

---

## 📁 Estrutura do Projeto

```
SIGerE/
│
├── run.py                     # Entrypoint: cria a app e roda o servidor
├── requirements.txt           # Dependências Python
├── migrations/                # Versionamento de schema (Alembic/Flask-Migrate)
├── instance/                  # Dados da instância (uploads, ignorado no git)
│   └── uploads/               # Fichas técnicas .docx enviadas (fora do static/)
│
└── app/                       # Pacote da aplicação
    ├── __init__.py            # Factory (create_app), blueprints, error handlers e context processors
    ├── config.py              # Configurações do Flask
    ├── extensions.py          # Instâncias de SQLAlchemy, LoginManager, CSRF, Limiter e Migrate
    ├── models.py              # Modelos (Unity, User, Classroom, Reservation, pagamentos, cozinha, etc.)
    ├── forms.py               # Definições de formulários WTForms
    ├── permissions.py         # Decoradores de controle de acesso por permissão
    ├── unity_context.py       # Contexto multi-unidade (unidade ativa, seletor, escopo de queries)
    ├── commands.py            # CLI (seed, sync-permissions) e catálogo de permissões/papéis
    │
    ├── services/              # Lógica de negócio compartilhada
    │   └── scheduling.py      # Validações de reserva e gravação atômica (locks anti double-booking)
    │
    ├── blueprints/            # Um módulo (ou subpacote) por funcionalidade
    │   ├── auth.py            # Autenticação (login, logout, troca de senha)
    │   ├── main.py            # Dashboard e troca de unidade ativa
    │   ├── admin.py           # Painel admin (usuários, salas, categorias, cursos, feriados, papéis, unidades)
    │   ├── classrooms.py      # Salas: listagem, detalhes, disponibilidade e exportação
    │   ├── reservations.py    # Reservas: CRUD, aprovações, repetição, séries e conflitos
    │   ├── schedule.py        # Calendário FullCalendar + API JSON de eventos
    │   ├── totem.py           # Display de quiosque para TVs
    │   ├── public.py          # Portal público (home, cronograma, busca de aula, busca geral)
    │   ├── payments.py        # Pagamentos docentes (base, aditivo, hora extra)
    │   └── kitchen/           # Módulo Cozinha
    │       ├── __init__.py    # Rotas: fichas técnicas, preparações e compras
    │       ├── parser.py      # Parser das Fichas Técnicas (.docx)
    │       └── export.py      # Requisição de compra em XLSX
    │
    ├── static/
    │   ├── css/style.css      # Estilos globais e variáveis de tema
    │   └── templates_excel/   # Modelos .xlsx (pagamentos, horas extras, requisição de compra)
    │
    └── templates/
        ├── base.html          # Layout principal, navbar, toggle de tema, seletor de unidade
        ├── index.html         # Dashboard (cronograma do dia)
        ├── home.html          # Página pública
        ├── cronograma.html    # Cronograma público do dia
        ├── buscar_aula.html   # Busca pública de aula do aluno
        ├── search.html        # Busca pública de salas/professores
        ├── calendar.html      # Calendário FullCalendar
        ├── totem.html         # Interface do quiosque
        ├── _pagination.html   # Macro de paginação reutilizável
        ├── _aula_macros.html  # Macros compartilhadas das telas de aula/cronograma
        ├── auth/              # Login, troca de senha
        ├── admin/             # Dashboard admin, usuários, salas, categorias, cursos, disciplinas, feriados, papéis, unidades
        ├── classrooms/        # Listagem, detalhes, disponibilidade mensal
        ├── reservations/      # Criar, editar, detalhes, minhas reservas, repetição, séries
        ├── payments/          # Formulários e listagens de pagamentos
        ├── kitchen/           # Fichas técnicas, preparações e compras
        └── errors/            # Páginas 403, 404, 500
```

---

## 🌍 APIs Externas

| Serviço | Uso | Endpoint utilizado |
|---------|-----|-------------------|
| **Open-Meteo** | Clima em tempo real no totem e portal | `https://api.open-meteo.com/v1/forecast` |
| **BrasilAPI** | Importação de feriados nacionais | `https://brasilapi.com.br/api/feriados/v1/{ano}` |
| **Nominatim (OpenStreetMap)** | Busca de endereço para geolocalizar unidades (clima) | `https://nominatim.openstreetmap.org/search` |

---

## 👤 Contas de Demonstração

O comando `flask --app run seed` sempre cria o administrador e, **interativamente**, pergunta se você quer popular dados de demonstração. Com a demonstração ativa, são criados: **3 unidades educacionais** (Centro, Norte e Sul), **100 usuários** (80 professores e 20 funcionários — dois deles também atuam como professores), **5 categorias de sala**, **28 salas**, **50 cursos**, **50 disciplinas**, **20 reservas** e lançamentos de pagamento base. Todos os usuários de demonstração são distribuídos entre as unidades.

| Perfil | Usuário | Senha | Permissões |
|--------|---------|-------|------------|
| **Super Administrador** | `admin` | `admin123` | Acesso total ao sistema (criado sempre, mesmo sem demonstração) |
| **Professor** | `teacher1` … `teacher80` | `teacher123` | Criar e gerenciar reservas, ver próprios pagamentos, acessar Cozinha |
| **Funcionário** | `employee1` … `employee20` | `employee123` | Visualização de salas e cursos, próprias reservas e Cozinha |

> ⚠️ **Atenção:** Por padrão, o sistema força a troca de senha no primeiro login. Para testes, as contas de demonstração já vêm com `force_password_change=False`.

---

## 🔐 Permissões e Papéis

O SIGerE utiliza um sistema de **RBAC (Role-Based Access Control)** com permissões granulares. Os papéis padrão são:

| Papel | Descrição |
|-------|-----------|
| **Super Administrador** | Acesso irrestrito a todas as funcionalidades (`*`) |
| **Administrador** | Gestão de usuários, unidades, salas, cursos, feriados, papéis e cozinha |
| **Administrador Financeiro** | Gestão de pagamentos, lançamentos e exportações |
| **Coordenador Pedagógico** | Aprovação de reservas, gestão de cursos e disciplinas |
| **Gestor de Salas** | Criação e gestão de salas, todas as reservas |
| **Professor** | Criar reservas, editar/cancelar próprias reservas, ver pagamentos, Cozinha |
| **Funcionário** | Visualização de salas e cursos, próprias reservas, Cozinha |
| **Visualizador** | Acesso somente leitura a salas, cursos e Cozinha |

Papéis e permissões são cadastrados no banco pelo `seed`/`sync-permissions` e podem ser **editados no painel** (Painel → Papéis) — inclusive criando papéis customizados com qualquer combinação de permissões.

---

## 🗂️ Catálogo de Permissões

Códigos definidos em `app/commands.py` e usados pelos decoradores de rota:

| Código | Descrição |
|--------|-----------|
| `user:read` / `user:create` / `user:edit` / `user:toggle` | Visualizar / criar / editar / ativar-desativar usuários |
| `unity:read` / `unity:create` / `unity:edit` / `unity:toggle` | Visualizar / criar / editar / ativar-desativar unidades |
| `unity:switch` | Alternar a unidade ativa de operação |
| `room:read` / `room:create` / `room:edit` / `room:toggle` | Visualizar / criar / editar / ativar-desativar salas |
| `reservation:read_all` / `reservation:read_own` | Ver todas / próprias reservas |
| `reservation:create` | Criar reservas |
| `reservation:edit_all` / `reservation:edit_own` | Editar todas / próprias reservas |
| `reservation:delete_all` | Excluir reservas permanentemente |
| `reservation:cancel_all` / `reservation:cancel_own` | Cancelar todas / próprias reservas |
| `reservation:approve` | Aprovar reservas pendentes |
| `course:read` / `course:create` / `course:edit` / `course:toggle` | Visualizar / criar / editar / ativar-desativar cursos e disciplinas |
| `holiday:read` / `holiday:create` / `holiday:edit` / `holiday:delete` | Visualizar / criar / editar / excluir feriados |
| `holiday:import` | Importar feriados da BrasilAPI |
| `payment:read` / `payment:read_own` | Ver todos / próprios pagamentos |
| `payment:create` / `payment:edit` / `payment:delete` | Criar / editar / excluir lançamentos |
| `payment:export` | Exportar pagamentos |
| `kitchen:read` | Acessar o módulo de Cozinha |
| `kitchen:sheet_create` | Enviar e salvar fichas técnicas (DOCX) |
| `kitchen:sheet_delete` | Excluir fichas técnicas e preparações |
| `kitchen:shopping_export` | Gerar e exportar a requisição de compra |
| `system:dashboard` | Acessar painel administrativo |
| `system:export` | Exportar dados diversos |
| `role:read` / `role:create` / `role:edit` / `role:delete` | Visualizar / criar / editar / excluir papéis |
| `*` | Permissão universal (super admin) |

---

## 🔒 Segurança

- **Hash de senhas** com Werkzeug (`generate_password_hash`)
- **Proteção CSRF global** (Flask-WTF `CSRFProtect`): todo POST exige token — formulários WTForms via `hidden_tag()` e botões de ação via `csrf_token()`; erro de CSRF exibe mensagem amigável em vez de página crua
- **Controle de acesso por permissões granulares** (ex: `reservation:create`, `payment:read`) com decorator "permissão OU dono da reserva"
- **Proteção contra double-booking concorrente:** locks por (sala, data), revalidação atômica na gravação e, em PostgreSQL, `SELECT ... FOR UPDATE` + advisory locks
- **Proteção contra auto-desativação:** administradores não podem desativar sua própria conta
- **Troca de senha forçada** no primeiro login ou após reset administrativo
- **Bloqueio de edição/exclusão** de reservas passadas (exceto para administradores)
- **Regras temporais** em pagamentos: edição até 30 dias, exclusão até 180 dias
- **`SECRET_KEY` obrigatória em produção** (fail-fast no boot fora do modo debug)
- **Cookies de sessão endurecidos:** `Secure` fora do debug e `SameSite=Lax`
- **Limite de upload** de 16 MB (`MAX_CONTENT_LENGTH`)
- **Fichas técnicas fora de `static/`:** armazenadas em `instance/uploads/` e servidas apenas pela rota autenticada de download
- **Escapagem de dados dinâmicos** em mensagens renderizadas com `|safe` (anti-XSS)
- **Rate limiting no login** (5 tentativas por minuto por IP, via Flask-Limiter) com aviso amigável ao exceder
- **API do calendário protegida:** intervalo de datas obrigatório e login exigido, evitando consultas sem limite

---

## 📝 Licença

Este projeto está licenciado sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.

---

<div align="center">

**Desenvolvido para instituições de ensino** 🎓

</div>
