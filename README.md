<div align="center">

# 🏫 SIGerE — Sistema Integrado de Gerenciamento Educacional

[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-2.x-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5-7952B3?logo=bootstrap&logoColor=white)](https://getbootstrap.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Plataforma web completa para gestão de reservas de salas, cronogramas acadêmicos e pagamento de professores em instituições de ensino.**

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
- [Segurança](#-segurança)
- [Licença](#-licença)

---

## 🎯 Visão Geral

O **SIGerE** é um sistema web desenvolvido em **Flask** para instituições educacionais que precisam gerenciar de forma integrada:

- 🏛️ **Reservas de espaços físicos** — salas de aula, auditórios, laboratórios de informática/saúde, cozinhas experimentais
- 👨‍🏫 **Cronogramas de professores** com detecção automática de conflitos de horário
- 💰 **Pagamentos docentes** — remuneração base semestral, aditivos e horas extras
- 📺 **Totens digitais** para corredores com exibição em tempo real de ocupação de salas
- 📆 **Calendário interativo** com filtros avançados e visualização mensal

O sistema possui **controle de acesso baseado em papéis (RBAC)** com permissões granulares, tema claro/escuro persistente, exportação de relatórios em PDF/Excel e seed automático de dados de demonstração.

---

## ✨ Funcionalidades

### 📅 Gestão de Reservas
- **Detecção inteligente de conflitos:** bloqueio automático de double-booking de salas
- **Conflito de professor:** se um professor já está alocado em outra sala no mesmo horário, a reserva é criada como **PENDENTE** e aguarda aprovação administrativa
- **Restrições de calendário:**
  - ❌ Domingos bloqueados
  - ❌ Feriados nacionais bloqueados (importados via BrasilAPI)
  - ⚠️ Sábados: apenas manhã e tarde (até 18h)
- **Repetição de reservas:** crie séries de aulas com opções de "mesmo dia da semana" e "pular fins de semana" (intervalo limitado a 180 dias por lote)
- **Auto-aprovação:** reservas sem conflitos são aprovadas instantaneamente
- **Filtros de disponibilidade:** salas disponíveis agora, em data/período específico ou por categoria

### 🏛️ Gestão de Salas e Categorias
- **Categorias dinâmicas:** Sala de Aula, Auditório, Laboratório de Informática, Laboratório de Saúde, Cozinha Experimental
- **Código automático:** geração de códigos no formato `SA101`, `AU101`, `LI105`, `LS301`, etc.
- **Visualização mensal:** calendário de ocupação por sala com navegação entre meses
- **Exportação:** PDF (landscape A4) e Excel

### 👥 Gestão de Usuários (Painel Admin)
- **Perfis distintos:**
  - **Professor:** departamento, matrícula, unidade
  - **Funcionário:** setor, função, unidade, com opção de "também atuar como professor"
- **Busca e filtros:** filtrar usuários por nome ou tipo de perfil
- **Reset de senha pelo admin:** gera uma senha temporária aleatória (exibida uma única vez) e força a troca no próximo login
- **Segurança:** forçar troca de senha no primeiro login ou após reset administrativo
- **Ativação/desativação:** controle de status do usuário sem exclusão de dados

### 📚 Estrutura Acadêmica
- CRUD completo de **Cursos** e **Disciplinas**
- Vinculação de reservas a curso, disciplina e professor específicos
- Ativação/desativação de registros sem exclusão

### 🌤️ Totem / Quiosque Digital (`/totem`)
- Interface otimizada para **TVs de corredor**
- **Tema automático:** claro durante o dia, escuro à noite
- **Clima em tempo real** via Open-Meteo API
- Agrupamento de salas ocupadas por **andar**
- Exibição de reservas de auditórios para os próximos 7 dias

### 🗓️ Calendário Interativo (`/calendar`)
- Integração com **FullCalendar** (visões: dia, semana, mês)
- Filtros por sala, professor, curso, disciplina e período (manhã/tarde/noite)
- Eventos coloridos com detalhes ao clicar
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
- **Exportação Excel:** planilhas formatadas com modelo pré-definido (base e horas extras)

### 🍳 Cozinha (`/kitchen`)
- **Ficha Técnica:** envio de múltiplos arquivos `.docx` de fichas técnicas operacionais de uma vez; o sistema lê o conteúdo (nome da preparação, equipamentos, utensílios, tempo de preparo, rendimento, tabelas de insumos, modo de preparo e notas técnicas) e um botão **Salvar Ficha Técnica** gera a preparação; também é possível **criar a ficha manualmente** pelo botão "Criar Ficha Técnica", no mesmo modelo
- **Preparações:** cada ficha salva gera uma receita visualizável em **cards ou lista** (à escolha do usuário, persistida no navegador), com busca por nome; a visualização completa traz equipamentos, utensílios, tempo, rendimento, ingredientes por preparação (especificação, quantidade e unidade), modo de preparo geral, alergênicos, observações e referências; os ingredientes podem ser **editados e ativados/desativados** — desativados, ficam de fora da requisição de compra; há **recálculo das quantidades por porções desejadas** (base = menor rendimento informado, ex.: "4 a 6 porções" usa 4) e **edição de todos os campos da preparação**
- **Compras:** seleção de múltiplas preparações e **soma dos ingredientes por similaridade** (acentos, plurais e parênteses normalizados), com conversão automática de unidades (g→KG, ml→L, un→UN) e exportação da **requisição de compra em Excel** preenchendo o modelo `app/static/templates_excel/base_planilha_compras.xlsx` ("REQUISIÇÃO DE COMPRA - GASTRONOMIA", com aba de centros de custo); a coluna OBSERVAÇÃO é exportada em branco, com as linhas da grade, para ser preenchida posteriormente
- **Multi-unidade:** fichas e preparações são isoladas por unidade educacional
- **Permissões:** `kitchen:read`, `kitchen:sheet_create`, `kitchen:sheet_delete`, `kitchen:shopping_export`

### 🌐 Portal Público
- Página inicial pública com links para login, calendário e busca
- Busca por salas (nome/código) e professores (nome)

### 🎨 UI/UX
- **Tema Claro/Escuro:** alternância global com persistência no `localStorage`
- **Design responsivo:** Bootstrap 5, funcional em mobile, tablet e desktop
- **Interface em Português:** todo o sistema localizado para pt-BR

---

## 🛠️ Tecnologias

| Camada | Tecnologia |
|--------|-----------|
| **Backend** | Python 3.8+, Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF |
| **Banco de Dados** | SQLite (padrão), compatível com PostgreSQL/MySQL |
| **Frontend** | Bootstrap 5, Bootstrap Icons, Jinja2, FullCalendar |
| **Relatórios** | FPDF2, OpenPyXL |
| **Rate limiting** | Flask-Limiter |
| **Produção** | Gunicorn (WSGI) + Nginx (proxy/TLS) |
| **APIs Externas** | [Open-Meteo](https://open-meteo.com/) (clima), [BrasilAPI](https://brasilapi.com.br/) (feriados) |

---

## 🚀 Instalação

### Pré-requisitos
- Python 3.8 ou superior
- pip

### Passo a passo

```bash
# 1. Clone o repositório
git clone https://github.com/jmisturini/SIGerE.git
cd SIGERE

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

# 5. Execute a aplicação
python run.py
```

A aplicação estará disponível em: **http://localhost:5000**

> **Nota:** em produção (`FLASK_DEBUG != true`) a aplicação exige a variável `SECRET_KEY` definida e se recusa a iniciar sem ela (ver [Configuração](#️-configuração)).

> **Nota:** Na primeira execução, o banco de dados é criado automaticamente. Execute `flask --app run seed` para popular com dados de demonstração (100 usuários, 27 salas, 50 cursos, 50 disciplinas e 20 reservas).

> **Atualizando uma instalação existente:** ao receber atualizações que adicionam novos módulos, execute `flask --app run sync-permissions` para criar as novas permissões e vinculá-las aos papéis sem precisar popular o banco novamente.

---

## ⚙️ Configuração

Edite o arquivo `app/config.py` ou utilize variáveis de ambiente:

```python
# app/config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///reservation.db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
```

### Variáveis de ambiente recomendadas (produção)

```bash
export SECRET_KEY="sua-chave-secreta-forte-aqui"
export DATABASE_URL="postgresql://user:pass@localhost/sigere"
```

> **Obrigatório em produção:** sem `SECRET_KEY` definida (fora do modo debug), a aplicação se recusa a iniciar. Além disso, os cookies de sessão recebem o atributo `Secure` automaticamente quando `FLASK_DEBUG != true` — sirva a aplicação atrás de HTTPS.

### Configurar localização do Totem (Clima)

As coordenadas vêm do `Config` (ou variáveis de ambiente) e alimentam o totem e o portal:

```bash
export TOTEM_LATITUDE="-23.5505"    # Latitude da sua instituição
export TOTEM_LONGITUDE="-46.6333"   # Longitude da sua instituição
```

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

> **Por que PostgreSQL?** O SQLite padrão serve para avaliação, mas em produção com múltiplos workers o recomendado é PostgreSQL (driver já incluído no `requirements.txt`).

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
sudo systemctl restart sigere
# Se algum módulo novo trouxer permissões:
sudo -u www-data venv/bin/flask --app run sync-permissions
```

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

### Importar feriados nacionais

1. Acesse o **Painel Administrativo → Feriados**
2. Clique em **Importar da BrasilAPI**
3. Informe o ano desejado
4. Os feriados nacionais brasileiros serão importados automaticamente

### Exportar relatórios

- **Salas:** `/classrooms/export_pdf` (PDF)
- **Disponibilidade mensal:** `/classrooms/<id>/export_availability` (PDF)
- **Pagamentos base:** `/payments/export/base` (Excel)
- **Horas extras:** `/payments/export/overtime` (Excel)

---

## 📁 Estrutura do Projeto

```
SIGERE/
│
├── run.py                     # Entrypoint: cria a app e roda o servidor
├── requirements.txt           # Dependências Python
├── reservation.db             # Banco SQLite (criado na primeira execução)
│
└── app/                       # Pacote da aplicação
    ├── __init__.py            # Factory (create_app), registro de blueprints e migrações leves
    ├── config.py              # Configurações do Flask
    ├── extensions.py          # Instâncias do SQLAlchemy e LoginManager
    ├── models.py              # Modelos do banco de dados (User, Classroom, Reservation, etc.)
    ├── forms.py               # Definições de formulários WTForms
    ├── permissions.py         # Decoradores de controle de acesso por permissão
    ├── unity_context.py       # Contexto multi-unidade (unidade ativa, seletor, escopo de queries)
    ├── commands.py            # Comandos CLI (seed, sync-permissions)
    │
    ├── blueprints/            # Um módulo (ou subpacote) por funcionalidade
    │   ├── auth.py            # Autenticação (login, logout, troca de senha)
    │   ├── main.py            # Dashboard principal
    │   ├── admin.py           # Painel administrativo (usuários, salas, cursos, feriados, papéis)
    │   ├── classrooms.py      # Salas: listagem, detalhes, disponibilidade e exportação
    │   ├── reservations.py    # Reservas: CRUD, aprovações, repetição e conflitos
    │   ├── schedule.py        # API JSON para o FullCalendar
    │   ├── totem.py           # Display de quiosque para TVs
    │   ├── public.py          # Portal público (home, busca)
    │   ├── payments.py        # Pagamentos docentes (base, aditivo, hora extra)
    │   └── kitchen/           # Módulo Cozinha
    │       ├── __init__.py    # Rotas: fichas técnicas, preparações e compras
    │       ├── parser.py      # Parser das Fichas Técnicas (.docx)
    │       └── export.py      # Requisição de compra em XLSX
    │
    ├── static/
    │   ├── css/style.css      # Estilos globais e variáveis de tema
    │   ├── templates_excel/   # Modelos .xlsx para exportação
    │   └── uploads/           # Arquivos enviados pelos usuários (ignorado no git)
    │
    └── templates/
        ├── base.html          # Layout principal, navbar, toggle de tema
        ├── index.html         # Dashboard
        ├── home.html          # Página pública
        ├── search.html        # Busca pública
        ├── calendar.html      # Calendário FullCalendar
        ├── totem.html         # Interface do quiosque
        ├── auth/              # Login, troca de senha
        ├── admin/             # Dashboard admin, usuários, salas, cursos, disciplinas, feriados
        ├── classrooms/        # Listagem, detalhes, disponibilidade mensal
        ├── reservations/      # Criar, editar, detalhes, minhas reservas, conflitos
        ├── payments/          # Formulários e listagens de pagamentos
        ├── kitchen/           # Fichas técnicas, preparações e compras
        └── errors/            # Páginas 403, 404, 500
```

---

## 🌍 APIs Externas

| Serviço | Uso | Endpoint utilizado |
|---------|-----|-------------------|
| **Open-Meteo** | Clima em tempo real no totem | `https://api.open-meteo.com/v1/forecast` |
| **BrasilAPI** | Importação de feriados nacionais | `https://brasilapi.com.br/api/feriados/v1/{ano}` |

---

## 👤 Contas de Demonstração

Após executar `flask --app run seed`, os seguintes logins estarão disponíveis:

| Perfil | Usuário | Senha | Permissões |
|--------|---------|-------|------------|
| **Super Administrador** | `admin` | `admin123` | Acesso total ao sistema |
| **Professor** | `teacher1` | `teacher123` | Criar e gerenciar reservas, ver próprios pagamentos |
| **Funcionário** | `employee1` | `employee123` | Visualização de salas e cursos |

> ⚠️ **Atenção:** Por padrão, o sistema força a troca de senha no primeiro login. Para testes, as contas de demonstração já vêm com `force_password_change=False`.

---

## 🔐 Permissões e Papéis

O SIGerE utiliza um sistema de **RBAC (Role-Based Access Control)** com permissões granulares. Os papéis padrão são:

| Papel | Descrição |
|-------|-----------|
| **Super Administrador** | Acesso irrestrito a todas as funcionalidades |
| **Administrador** | Gestão completa de usuários, salas, cursos, feriados e papéis |
| **Administrador Financeiro** | Gestão de pagamentos, lançamentos e exportações |
| **Coordenador Pedagógico** | Aprovação de reservas, gestão de cursos e disciplinas |
| **Gestor de Salas** | Criação e gestão de salas, todas as reservas |
| **Professor** | Criar reservas, editar/cancelar próprias reservas, ver pagamentos |
| **Funcionário** | Visualização de salas e cursos |
| **Visualizador** | Acesso somente leitura a salas e cursos |

---

## 🔒 Segurança

- **Hash de senhas** com Werkzeug (`generate_password_hash`)
- **Proteção CSRF global** (Flask-WTF `CSRFProtect`): todo POST exige token — formulários WTForms via `hidden_tag()` e botões de ação via `csrf_token()`
- **Controle de acesso por permissões granulares** (ex: `reservation:create`, `payment:read`)
- **Proteção contra auto-desativação:** administradores não podem desativar sua própria conta
- **Troca de senha forçada** no primeiro login ou após reset administrativo
- **Bloqueio de edição/exclusão** de reservas passadas (exceto para administradores)
- **Regras temporais** em pagamentos: edição até 30 dias, exclusão até 180 dias
- **`SECRET_KEY` obrigatória em produção** (fail-fast no boot fora do modo debug)
- **Cookies de sessão endurecidos:** `Secure` fora do debug e `SameSite=Lax`
- **Limite de upload** de 16 MB (`MAX_CONTENT_LENGTH`)
- **Fichas técnicas fora de `static/`:** armazenadas em `instance/uploads/` e servidas apenas pela rota autenticada de download
- **Escapagem de dados dinâmicos** em mensagens renderizadas com `|safe` (anti-XSS)
- **Rate limiting no login** (5 tentativas por minuto por IP, via Flask-Limiter)

---

## 📝 Licença

Este projeto está licenciado sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.

---

<div align="center">

**Desenvolvido para instituições de ensino** 🎓

</div>
