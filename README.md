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
- [Capturas de Tela](#-capturas-de-tela)
- [Funcionalidades](#-funcionalidades)
- [Tecnologias](#-tecnologias)
- [Documentação](#-documentação)
- [Instalação](#-instalação)
- [Configuração](#-configuração)
- [Deploy em Produção (Gunicorn + Nginx)](#-deploy-em-produção-gunicorn--nginx)
- [Uso](#-uso)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [APIs Externas](#-apis-externas)
- [API de Reservas (Integrações)](#-api-de-reservas-integrações)
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
- 💰 **Financeiro** — horas extras docentes e Vale Transporte (importação do Pedido de Compra, revisão/editação dos dados e exportação da planilha de pagamento)
- 🍳 **Cozinha** — fichas técnicas (.docx), preparações e requisição de compra
- 📺 **Totens digitais** para corredores com exibição em tempo real de ocupação de salas
- 📆 **Calendário interativo** com filtros avançados e visualização mensal
- 🌐 **Portal público** com cronograma do dia e busca de aula para alunos
- 🏢 **Multi-unidade** — dados isolados por unidade educacional (salas, reservas, cursos, feriados, cozinha), com alternância de unidade para administradores

O sistema possui **controle de acesso baseado em papéis (RBAC)** com permissões granulares, tema claro/escuro persistente, exportação de relatórios em PDF/Excel, layout responsivo (mobile/tablet/desktop) e seed opcional de dados de demonstração.

**Primeira implantação:** após o `seed-admin`, o painel do super-admin exibe um **checklist de configuração inicial** (unidade, categorias, salas, professores, funcionários, cursos/disciplinas e feriados) — cada passo confere dados reais do banco, marca o que já existe e some quando a implantação está completa.

---

## 📸 Capturas de Tela

Telas do sistema com os dados de demonstração (`flask seed`) — disponíveis em [`docs/screenshots/`](docs/screenshots/).

| Painel (resumo do dia) | Calendário com filtros |
|---|---|
| ![Painel com o resumo das reservas do dia](docs/screenshots/02-dashboard.png) | ![Calendário com filtros de reserva](docs/screenshots/03-calendario.png) |

| Lista de Reservas | Disponibilidade mensal da sala |
|---|---|
| ![Lista de todas as reservas com situações](docs/screenshots/04-reservas.png) | ![Disponibilidade mensal da sala](docs/screenshots/05-disponibilidade-sala.png) |

| Totem digital (TV de corredor) | Portal público |
|---|---|
| ![Totem de ocupação de salas com clima](docs/screenshots/06-totem.png) | ![Cronograma público do dia](docs/screenshots/08-portal-cronograma.png) |

| API de Reservas (JSON) | Quadro de porta para tablet (app de exemplo) |
|---|---|
| ![Resposta JSON da API de reservas](docs/screenshots/09-api-json.png) | ![Quadro de porta consumindo a API](docs/screenshots/10-quadro-porta.png) |

<details>
<summary>Mais telas</summary>

| Login | Home pública |
|---|---|
| ![Tela de login](docs/screenshots/01-login.png) | ![Home pública](docs/screenshots/07-portal-home.png) |

</details>

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
- **Reservas passadas são registro:** com a data anterior a hoje, o detalhe fica somente leitura (sem repetir, cancelar, editar ou excluir) e as rotas recusam as alterações — inclusive para administradores
- **Ciclo de vida:** aprovar, cancelar (status `cancelled` mantém histórico) e excluir permanentemente (admins)
- **Filtros de disponibilidade:** salas disponíveis agora, em data/período específico ou por categoria
- **Compartilhar reserva:** botão no detalhe gera mensagem enxuta e amigável (sala, curso, disciplina, professor, data/hora por extenso e descrição/finalidade) para enviar por **e-mail** ou **WhatsApp** — abre o programa de e-mail (`mailto:`) ou o WhatsApp (`wa.me`) do próprio usuário, sem configuração de SMTP no servidor; mensagem editável antes do envio e opção de copiar. Não aparece em reservas passadas nem canceladas

### 🏛️ Gestão de Salas e Categorias
- **Categorias com CRUD completo** no painel (Painel → Categorias): nome, sigla, código, **cor de destaque, ícone e janela de exibição no totem** (período atual ou próximos 7 dias)
- **Categorias são dados, não código:** totem, dashboard e listagem se montam a partir do cadastro — criar a categoria "Quadra de Esportes" e vinculá-la a uma sala faz ela aparecer nas telas sem qualquer alteração no sistema
- **Categorias padrão da seed:** Sala de Aula (`SA`), Auditório (`AU`), Cozinha (`CO`), Laboratório de Informática (`LI`), Laboratório de Saúde (`LS`) e Quadra de Esportes (`QE`)
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
- Cronograma do dia separado em **uma seção por categoria cadastrada** (nome, ícone e cor vindos do cadastro)
- Destaque para o **período atual** (manhã/tarde/noite) com as reservas aprovadas em andamento
- Escopado na unidade ativa

### 🌤️ Totem / Quiosque Digital (`/totem`)
- Interface otimizada para **TVs de corredor**
- **Tema automático:** claro durante o dia, escuro à noite
- **Clima em tempo real** via Open-Meteo, usando a localização da unidade exibida
- **Blocos dinâmicos por categoria:** a tela consulta as categorias cadastradas e monta as seções sozinha, usando a **cor e o ícone** de cada uma para diferenciação visual — cada categoria define seu recorte de tempo (**período atual** ou **próximos 7 dias**)
- Agrupamento de salas ocupadas por **andar** dentro de cada categoria do período
- Alternância rápida de unidade por parâmetro (`?unity=<id>`) — uma TV por unidade

### 🗓️ Calendário Interativo (`/calendar`)
- Integração com **FullCalendar** (visões: dia, semana, mês)
- Filtros por sala, professor, curso, disciplina e período (manhã/tarde/noite)
- API JSON (`/calendar/api/events`) com intervalo de datas obrigatório e filtros combináveis
- Eventos coloridos com detalhes ao clicar (link para a reserva)
- Adaptação automática ao tema claro/escuro

### 💰 Financeiro
- **Horas Extras:** com nível de ensino, valor hora, turno e dias selecionados no calendário (gravados apenas como dia, separados por vírgula — o mês/ano vêm do Mês Base)
- **Regras de negócio:**
  - Bloqueio de lançamento em meses anteriores ao atual (mensagem de erro visível) e de edição/exclusão de meses anteriores ou com mais de 30 dias
  - Lançamentos do mês corrente só até o dia 25
- **Consulta:** filtro de Mês Base em caixa de seleção (meses já lançados + mês atual, abrindo no mês atual, com opção "Todos os meses") combinado com filtro por professor
- **Código Orçamentário:** máscara automática com pontos — `xx.xx.xxxx.x` (9 dígitos) ou `xx.xx.xxxx.xx.xxxx` (14 dígitos), aplicada no cadastro e na exportação
- **Exportação Excel:** planilha formatada com modelo pré-definido (`base_pagamento_extra.xlsx`), filtrável por mês e/ou professor

### 🚌 Vale Transporte (`/vt`)
Módulo dividido em duas páginas, com sub-menus próprios no menu lateral (Hora Extra e Vale Transporte):
- **Importação (`/vt/`):** upload do arquivo `.xlsx` do Pedido de Compra; o sistema lê a aba "Vale Transporte" inteira (todas as 16 colunas: matrícula, nome, optante, vínculo, unidade, empresas A/B com valores e passes, totais) e grava tudo para revisão — mesmo fluxo das fichas técnicas da Cozinha (importar → revisar/editar → exportar). Ao concluir, leva direto para a listagem
- **Colaboradores (`/vt/colaboradores`):** listagem com filtros e exportação:
- **Padronização de nomes:** nomes fora do padrão "iniciais maiúsculas" (ex.: `JOÃO ALFREDO MISTURINI` → `João Alfredo Misturini`) são formatados automaticamente na importação/edição, com o original preservado no selo "nome ajustado" da listagem
- **Marcação de inconsistências:** linhas com **nome repetido** ou **matrícula repetida** ficam destacadas com selos de aviso (a verificação cobre toda a base da unidade, mesmo com filtros ativos)
- **Filtros e organização:** busca por nome, filtros por vínculo e unidade, ordenação por nome/matrícula/valor total e opção de esconder não optantes com valor R$ 0,00
- **Edição individual:** cada colaborador pode ter todos os campos corrigidos pela tela (valores monetários aceitam vírgula decimal); um novo upload substitui os dados vigentes e há botão "Limpar tudo"
- **Exportação por grupo:** gera a planilha de pagamento preenchendo o modelo `planilha_base_vt.xlsx` (Matrícula, Nome e Valor Total a partir da linha 5), filtrável pelos grupos do gerador original — Técnico-Administrativo (Faculdade), Professores e Técnico-Administrativo (Restaurante/Lanchonete) — incluindo apenas Optante "Sim" com passes maior que zero; a coluna UO e a tabela de códigos de unidades do modelo são preservadas intactas

### 🍳 Cozinha (`/kitchen`)
- **Ficha Técnica:** envio de múltiplos arquivos `.docx` de fichas técnicas operacionais de uma vez; o sistema lê o conteúdo do modelo em tabelas (nome da preparação, equipamentos, utensílios, tempo de preparo, rendimento, tabela única de insumos com especificações/quantidade/unidade, modo de preparo e notas técnicas — observações, alergênicos e referências) e um botão **Salvar Ficha Técnica** gera a preparação; também é possível **criar a ficha manualmente** pelo botão "Criar Ficha Técnica", no mesmo modelo
- **Preparações:** cada ficha salva gera uma receita visualizável em **cards ou lista** (à escolha do usuário, persistida no navegador), com busca por nome; a visualização completa traz equipamentos, utensílios, tempo, rendimento, ingredientes por preparação (especificação, quantidade e unidade), modo de preparo geral, alergênicos, observações e referências; os ingredientes podem ser **editados e ativados/desativados** — desativados, ficam de fora da requisição de compra; há **recálculo das quantidades por porções desejadas** (base = menor rendimento informado, ex.: "4 a 6 porções" usa 4) com prévia instantânea e botão **Salvar quantidades**, que persiste a escala na preparação — a partir daí a exibição e a requisição de compra usam os novos valores, com "Restaurar originais" para voltar ao rendimento da ficha — e **edição de todos os campos da preparação**
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
- **Menu lateral contrátil:** botão no cabeçalho alterna entre expandido e modo compacto de ícones (desktop), com preferência salva no navegador; clicar num grupo com submenu reexpande o menu
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

## 📚 Documentação

Guias detalhados disponíveis no diretório [`docs/`](docs/):

| Guia | Conteúdo |
|------|----------|
| 🛠️ [Desenvolvimento e Debug](docs/desenvolvimento-debug.md) | Ambiente na sua máquina: modo debug (`FLASK_DEBUG`), banco local, migrações, testes, depuração e erros comuns |
| 🚢 [Implantação em Produção](docs/implantacao-producao.md) | Servidor real: PostgreSQL, Redis, Gunicorn + systemd, Nginx, HTTPS, atualização, backup e solução de problemas |
| 📡 [API de Reservas](docs/api-reservas.md) | Uso da API REST de leitura para apps externos: autenticação, parâmetros, exemplos e FAQ |

---

## 🚀 Instalação

> 🛠️ **Guia completo de desenvolvimento** (modo debug, banco local, migrações, testes e depuração): [docs/desenvolvimento-debug.md](docs/desenvolvimento-debug.md)

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

# 4. Crie o schema do banco (Flask-Migrate/Alembic)
# Comandos de manutenção da CLI não exigem SECRET_KEY nem FLASK_DEBUG
flask --app run db upgrade

# 5. Popule o banco — escolha UMA das opções:
#    a) cria o admin com senha definida por você (sem dados de demonstração):
flask --app run seed-admin
#    b) cria o admin padrão (admin/admin123) e pergunta sobre dados de demonstração:
flask --app run seed

# 6. Em desenvolvimento, habilite o modo debug antes de servir a aplicação
# Linux/macOS:
export FLASK_DEBUG=true
# Windows PowerShell:
# $env:FLASK_DEBUG="true"

# 7. Execute a aplicação
python run.py
```

A aplicação estará disponível em: **http://localhost:5000**

> **Nota:** o schema do banco é versionado com Flask-Migrate/Alembic (não é criado automaticamente no boot). O boot apenas avisa no terminal quando o banco está vazio ou fora do fluxo de migrações.

> **Nota:** o comando `seed` cria sempre o administrador (`admin`/`admin123`) e, em seguida, **pergunta interativamente** se você quer popular dados de demonstração (responda `y` para receber também as contas `teacher1` e `employee1`). Veja detalhes em [Contas de Demonstração](#-contas-de-demonstração).

> **Implantação real:** prefira o comando `flask --app run seed-admin` — cria **apenas** a conta do administrador (sem dados de demonstração) e **solicita que você defina a senha** no terminal (mínimo de 8 caracteres, digitação oculta).

> **Unidades do Senac SC:** para cadastrar as unidades educacionais reais (extraídas do portal https://portal.sc.senac.br/unidades), execute `flask --app run seed-unidades` — cria as unidades ausentes e atualiza endereço/telefone das existentes a partir de `docs/unidades-senac-sc.json`. O comando é idempotente e pode ser executado mais de uma vez.

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
| Instalação nova (banco vazio) | `flask --app run db upgrade` + `flask --app run seed-admin` (ou `seed`, com demonstração) |
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

> 🚢 **Guia completo de implantação e operação** (PostgreSQL, Redis, systemd, Nginx, HTTPS, backup e solução de problemas): [docs/implantacao-producao.md](docs/implantacao-producao.md)

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
| Totem | `/totem/?unity=<id>` | Display de corredor (clima, blocos por categoria) |

### Exportar relatórios

- **Salas:** `/classrooms/export_pdf` (PDF)
- **Disponibilidade mensal:** `/classrooms/<id>/export_availability` (PDF)
- **Horas extras:** `/payments/export/overtime` (Excel)
- **Vale Transporte:** `/vt/exportar?group=faculdade|professores|restaurante` (Excel, modelo `planilha_base_vt.xlsx`)
- **Requisição de compra:** `/kitchen/compras/export` (Excel, via seleção de preparações)

---

## 📁 Estrutura do Projeto

```
SIGerE/
│
├── run.py                     # Entrypoint: cria a app e roda o servidor
├── requirements.txt           # Dependências Python
├── migrations/                # Versionamento de schema (Alembic/Flask-Migrate)
├── docs/                      # Documentação e capturas de tela
│   ├── api-reservas.md        # Documentação detalhada da API de reservas
│   ├── desenvolvimento-debug.md  # Guia completo de desenvolvimento e debug
│   ├── implantacao-producao.md   # Guia completo de implantação em produção
│   └── screenshots/           # Imagens exibidas no README
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
    │   ├── api.py             # API REST de leitura de reservas para apps externos (/api/v1)
    │   ├── payments.py        # Pagamentos docentes (hora extra)
    │   ├── vt.py              # Vale Transporte: upload, parser, edição e exportação
    │   └── kitchen/           # Módulo Cozinha
    │       ├── __init__.py    # Rotas: fichas técnicas, preparações e compras
    │       ├── parser.py      # Parser das Fichas Técnicas (.docx)
    │       └── export.py      # Requisição de compra em XLSX
    │
    ├── static/
    │   ├── css/style.css      # Estilos globais e variáveis de tema
    │   └── templates_excel/   # Modelos .xlsx (hora extra, requisição de compra)
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
        ├── payments/          # Formulário e listagem de horas extras
        ├── vt/                # Vale Transporte: importação, colaboradores e edição
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

## 🔌 API de Reservas (Integrações)

API REST **somente leitura** para aplicativos externos exibirem a ocupação das salas. Erros e respostas são sempre JSON e a URL base é `/api/v1`.

> 📖 **Documentação detalhada de uso** (autenticação, parâmetros, exemplos em cURL/Python/JavaScript e FAQ): [docs/api-reservas.md](docs/api-reservas.md)
>
> 🚪 **App de exemplo:** quadro de sala para tablet na porta, consumindo a API anonimamente — [examples/quadro-sala](examples/quadro-sala/)

### Autenticação e visibilidade

| Modo | Como usar | O que a resposta traz |
|------|-----------|----------------------|
| **Sem token** | basta chamar a API | Apenas **data, horário, sala e título** — e somente reservas **aprovadas** |
| **Com token Bearer** | cabeçalho `Authorization: Bearer sige_…` — token gerado em **Painel Admin → Tokens da API** (permissão `api:manage`) | **Todos os detalhes** da reserva (descrição, situação, docente, curso, disciplina, criador, unidade, sala completa...) em qualquer situação (aprovada, pendente, cancelada) |

```bash
# Público (campos reduzidos)
curl http://localhost:5000/api/v1/reservations

# Com token (todos os detalhes)
curl -H "Authorization: Bearer sige_SEU_TOKEN" http://localhost:5000/api/v1/reservations
```

O valor completo do token é exibido **uma única vez** na geração (o banco guarda apenas o hash SHA-256); a página admin lista prefixo, último uso e validade, e permite revogar/excluir. Tokens inválidos, expirados ou revogados retornam `401` com `WWW-Authenticate: Bearer`; requisição sem token funciona com o payload público (não há bloqueio).

### Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| `GET` | `/api/v1/reservations` | Lista paginada de reservas da unidade |
| `GET` | `/api/v1/reservations/<id>` | Detalhe de uma reserva |
| `GET` | `/api/v1/rooms` | Salas ativas da unidade (para resolver códigos de sala) |

### Parâmetros de `/api/v1/reservations`

| Parâmetro | Valores | Padrão |
|-----------|---------|--------|
| `start` / `end` | Datas `AAAA-MM-DD` (intervalo de datas) | sem limite |
| `status` | `approved`, `pending`, `cancelled` ou `all` | `approved` (ignorado sem autenticação) |
| `classroom_id` / `classroom_code` | ID ou código da sala (ex.: `S101`) | — |
| `teacher_id`, `course_id`, `subject_id` | IDs numéricos | — |
| `period` | `morning`, `afternoon` ou `night` | — |
| `unity_id` | ID da unidade — respeitado apenas por anônimos e por quem pode alternar unidade; usuário comum fica preso à própria unidade | unidade do usuário / primeira ativa |
| `page` / `per_page` | Paginação (`per_page` máximo 500) | `1` / `100` |

### Exemplos

```jsonc
// GET /api/v1/reservations/42 — sem autenticação
{
  "id": 42,
  "title": "Aula de Matemática",
  "date": "2026-09-10",
  "start_time": "08:00:00",
  "end_time": "10:00:00",
  "classroom": { "id": 7, "code": "S101", "name": "Sala 101" }
}

// GET /api/v1/reservations/42 — autenticado (campos adicionais)
{
  "id": 42,
  "title": "Aula de Matemática",
  "description": "Capítulo 4",
  "date": "2026-09-10",
  "start_time": "08:00:00",
  "end_time": "10:00:00",
  "status": "approved",
  "classroom": { "id": 7, "code": "S101", "name": "Sala 101", "building": "A",
                 "floor": "1º Andar", "capacity": 30, "category": "Sala de Aula" },
  "unity": { "id": 1, "code": "CTR", "name": "Unidade Centro" },
  "created_by": { "id": 3, "username": "prof1", "full_name": "Prof. Um" },
  "teacher": { "id": 5, "username": "prof5", "full_name": "Prof. Cinco" },
  "course": { "id": 2, "code": "INF", "name": "Informática" },
  "subject": { "id": 9, "code": "MAT", "name": "Matemática" },
  "reviewed_by": null,
  "review_note": null,
  "repeat_group_id": null,
  "created_at": "2026-09-01T13:22:41",
  "updated_at": "2026-09-01T13:22:41"
}
```

A listagem usa um envelope com metadados: `unity_id`, `authenticated`, `page`, `per_page`, `total`, `pages` e `reservations`. Códigos de erro (`400`, `401`, `404`) também vêm em JSON (`{"error": "..."}`).

---

## 👤 Contas de Demonstração

O comando `flask --app run seed` sempre cria o administrador e, **interativamente**, pergunta se você quer popular dados de demonstração. Com a demonstração ativa, são criados: **3 unidades educacionais** (Centro, Norte e Sul), **100 usuários** (80 professores e 20 funcionários — dois deles também atuam como professores), **6 categorias de sala**, **29 salas**, **50 cursos**, **50 disciplinas**, **20 reservas** e lançamentos de hora extra. Todos os usuários de demonstração são distribuídos entre as unidades.

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
| **Administrador** | Gestão de usuários, unidades, salas, cursos, feriados, papéis, cozinha e tokens da API |
| **Administrador Financeiro** | Financeiro: horas extras, Vale Transporte e exportações |
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
| `api:manage` | Gerenciar tokens de acesso à API de reservas |
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
- **Regras temporais** em hora extra: edição/exclusão até 30 dias e bloqueio de meses anteriores
- **`SECRET_KEY` obrigatória em produção** (fail-fast no boot fora do modo debug)
- **Cookies de sessão endurecidos:** `Secure` fora do debug e `SameSite=Lax`
- **Limite de upload** de 16 MB (`MAX_CONTENT_LENGTH`)
- **Fichas técnicas fora de `static/`:** armazenadas em `instance/uploads/` e servidas apenas pela rota autenticada de download
- **Escapagem de dados dinâmicos** em mensagens renderizadas com `|safe` (anti-XSS)
- **Rate limiting no login** (5 tentativas por minuto por IP, via Flask-Limiter) com aviso amigável ao exceder
- **API do calendário protegida:** intervalo de datas obrigatório e login exigido, evitando consultas sem limite
- **API de reservas com mínimo de dados anônimo:** sem token expõe apenas data, horário, sala e título de reservas aprovadas; acesso completo via Bearer token gerado no painel admin (permissão `api:manage`), armazenado como hash SHA-256 com revogação imediata, erros em JSON e rate limiting por IP

---

## 📝 Licença

Este projeto está licenciado sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.

---

<div align="center">

**Desenvolvido para instituições de ensino** 🎓

</div>
