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

O sistema possui **controle de acesso baseado em papéis (RBAC)** com permissões granulares, tema claro/escuro persistente, exportação de relatórios em PDF/CSV/Excel e seed automático de dados de demonstração.

---

## ✨ Funcionalidades

### 📅 Gestão de Reservas
- **Detecção inteligente de conflitos:** bloqueio automático de double-booking de salas
- **Conflito de professor:** se um professor já está alocado em outra sala no mesmo horário, a reserva é criada como **PENDENTE** e aguarda aprovação administrativa
- **Restrições de calendário:**
  - ❌ Domingos bloqueados
  - ❌ Feriados nacionais bloqueados (importados via BrasilAPI)
  - ⚠️ Sábados: apenas manhã e tarde (até 18h)
- **Repetição de reservas:** crie séries de aulas com opções de "mesmo dia da semana" e "pular fins de semana"
- **Auto-aprovação:** reservas sem conflitos são aprovadas instantaneamente
- **Filtros de disponibilidade:** salas disponíveis agora, em data/período específico ou por categoria

### 🏛️ Gestão de Salas e Categorias
- **Categorias dinâmicas:** Sala de Aula, Auditório, Laboratório de Informática, Laboratório de Saúde, Cozinha Experimental
- **Código automático:** geração de códigos no formato `SA101`, `AU101`, `LI105`, `LS301`, etc.
- **Visualização mensal:** calendário de ocupação por sala com navegação entre meses
- **Exportação:** CSV, PDF (landscape A4) e Excel

### 👥 Gestão de Usuários (Painel Admin)
- **Perfis distintos:**
  - **Professor:** departamento, matrícula, unidade
  - **Funcionário:** setor, função, unidade, com opção de "também atuar como professor"
- **Busca e filtros:** filtrar usuários por nome ou tipo de perfil
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
| **Relatórios** | FPDF2, OpenPyXL, CSV |
| **APIs Externas** | [Open-Meteo](https://open-meteo.com/) (clima), [BrasilAPI](https://brasilapi.com.br/) (feriados) |

---

## 🚀 Instalação

### Pré-requisitos
- Python 3.8 ou superior
- pip

### Passo a passo

```bash
# 1. Clone o repositório
git clone https://github.com/seu-usuario/SIGERE.git
cd SIGERE

# 2. Crie e ative um ambiente virtual
python -m venv venv

# Linux/macOS:
source venv/bin/activate

# Windows:
venv\Scripts\activate

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Execute a aplicação
python app.py
```

A aplicação estará disponível em: **http://localhost:5000**

> **Nota:** Na primeira execução, o banco de dados é criado automaticamente. Execute `flask seed` para popular com dados de demonstração (100 usuários, 27 salas, 50 cursos, 50 disciplinas e 20 reservas).

---

## ⚙️ Configuração

Edite o arquivo `config.py` ou utilize variáveis de ambiente:

```python
# config.py
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

### Configurar localização do Totem (Clima)

Edite `templates/totem.html` e ajuste as coordenadas geográficas:

```javascript
const lat = -23.5505;   // Latitude da sua instituição
const lon = -46.6333;   // Longitude da sua instituição
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

- **Salas:** `/classrooms/export` (CSV) ou `/classrooms/export_pdf` (PDF)
- **Disponibilidade mensal:** `/classrooms/<id>/export_availability` (PDF)
- **Pagamentos base:** `/payments/export/base` (Excel)
- **Horas extras:** `/payments/export/overtime` (Excel)

---

## 📁 Estrutura do Projeto

```
SIGERE/
│
├── app.py                 # Factory da aplicação, registro de blueprints e hooks de segurança
├── config.py              # Configurações do Flask
├── extensions.py          # Instâncias do SQLAlchemy e LoginManager
├── models.py              # Modelos do banco de dados (User, Classroom, Reservation, etc.)
├── forms.py               # Definições de formulários WTForms
├── requirements.txt       # Dependências Python
│
├── auth.py                # Autenticação (login, logout, troca de senha)
├── admin.py               # Painel administrativo (usuários, salas, cursos, feriados, papéis)
├── classrooms.py          # Listagem, detalhes, disponibilidade e exportação de salas
├── reservations.py        # CRUD de reservas, aprovações, repetição e conflitos
├── schedule.py            # API JSON para o FullCalendar
├── totem.py               # Display de quiosque para TVs
├── public.py              # Portal público (home, busca)
├── main.py                # Dashboard principal
├── payments.py            # Gestão de pagamentos docentes (base, aditivo, extra)
├── permissions.py         # Decoradores de controle de acesso baseado em permissões
├── commands.py            # Comandos CLI customizados (seed de dados)
│
├── static/
│   ├── css/style.css      # Estilos globais e variáveis de tema
│   └── templates_excel/   # Modelos .xlsx para exportação
│
└── templates/
    ├── base.html            # Layout principal, navbar, toggle de tema
    ├── index.html           # Dashboard
    ├── home.html            # Página pública
    ├── search.html          # Busca pública
    ├── calendar.html        # Calendário FullCalendar
    ├── totem.html           # Interface do quiosque
    ├── auth/                # Login, troca de senha
    ├── admin/               # Dashboard admin, usuários, salas, cursos, disciplinas, feriados
    ├── classrooms/          # Listagem, detalhes, disponibilidade mensal
    ├── reservations/        # Criar, editar, detalhes, minhas reservas, conflitos
    ├── payments/            # Formulários e listagens de pagamentos
    └── errors/              # Páginas 403, 404, 500
```

---

## 🌍 APIs Externas

| Serviço | Uso | Endpoint utilizado |
|---------|-----|-------------------|
| **Open-Meteo** | Clima em tempo real no totem | `https://api.open-meteo.com/v1/forecast` |
| **BrasilAPI** | Importação de feriados nacionais | `https://brasilapi.com.br/api/feriados/v1/{ano}` |

---

## 👤 Contas de Demonstração

Após executar `flask seed`, os seguintes logins estarão disponíveis:

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
- **Proteção CSRF** em todos os formulários via Flask-WTF
- **Controle de acesso por permissões granulares** (ex: `reservation:create`, `payment:read`)
- **Proteção contra auto-desativação:** administradores não podem desativar sua própria conta
- **Troca de senha forçada** no primeiro login ou após reset administrativo
- **Bloqueio de edição/exclusão** de reservas passadas (exceto para administradores)
- **Regras temporais** em pagamentos: edição até 30 dias, exclusão até 180 dias

---

## 📝 Licença

Este projeto está licenciado sob a licença MIT. Consulte o arquivo [LICENSE](LICENSE) para mais detalhes.

---

<div align="center">

**Desenvolvido para instituições de ensino** 🎓

</div>
