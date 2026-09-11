# 🚢 Implantação em Produção — Guia Completo

Documentação detalhada da **implantação e operação** do SIGerE em servidor real:
preparação da máquina, PostgreSQL, Redis, Gunicorn, Nginx, HTTPS, rotina de
atualização, backup, monitoramento e solução de problemas.

> **Público-alvo:** quem instala e mantém o sistema no servidor da instituição (Debian/Ubuntu).
> **Arquitetura de referência:** Nginx (TLS/proxy) → Gunicorn (WSGI) → Flask · PostgreSQL · Redis
> 🛠️ **Para desenvolver na sua máquina, leia:** [desenvolvimento-debug.md](desenvolvimento-debug.md)
> 📡 **API para integrações externas:** [api-reservas.md](api-reservas.md)

---

## Índice

- [Visão geral da arquitetura](#-visão-geral-da-arquitetura)
- [Requisitos](#-requisitos)
- [1. Preparar o servidor](#1-preparar-o-servidor)
- [2. Banco de dados (PostgreSQL)](#2-banco-de-dados-postgresql)
- [3. Redis](#3-redis)
- [4. Variáveis de ambiente](#4-variáveis-de-ambiente)
- [5. Inicializar o banco](#5-inicializar-o-banco)
- [6. Gunicorn via systemd](#6-gunicorn-via-systemd)
- [7. Nginx como proxy reverso](#7-nginx-como-proxy-reverso)
- [8. HTTPS (obrigatório)](#8-https-obrigatório)
- [9. Primeiro acesso e configuração inicial](#9-primeiro-acesso-e-configuração-inicial)
- [10. Atualizando a aplicação](#10-atualizando-a-aplicação)
- [Operação: monitoramento e backup](#-operação-monitoramento-e-backup)
- [Solução de problemas](#-solução-de-problemas)
- [Segurança em produção](#-segurança-em-produção)
- [Perguntas frequentes](#-perguntas-frequentes)

---

## 🏗️ Visão geral da arquitetura

```
                    ┌──────────────────────────────────────────────┐
 Internet ──HTTPS──▶│  Nginx :443                                  │
                    │  · TLS (certbot/Let's Encrypt)               │
                    │  · redireciona 80 → 443                      │
                    │  · serve /static/ direto do disco            │
                    │  · proxy → socket Unix                       │
                    └──────────────┬───────────────────────────────┘
                                   ▼
                    ┌──────────────────────────────────────────────┐
                    │  Gunicorn (systemd: sigere.service)          │
                    │  · WSGI, 3 workers × 2 threads               │
                    │  · socket /run/sigere/sigere.sock            │
                    │  · logs em /var/log/sigere/                  │
                    └──────┬───────────────────────┬───────────────┘
                           ▼                       ▼
                    ┌──────────────┐        ┌──────────────┐
                    │  PostgreSQL  │        │    Redis     │
                    │  dados       │        │  contadores  │
                    │  (locks      │        │  de rate     │
                    │   transacionais)      │  limit       │
                    └──────────────┘        └──────────────┘
```

O papel de cada componente — e por que ele é recomendado:

| Componente | Papel | Por quê |
|------------|-------|---------|
| **Nginx** | Proxy reverso, TLS, arquivos estáticos | Eficiente em servir CSS/JS/imagens; termina o HTTPS; os cabeçalhos `X-Forwarded-*` que ele envia são o que permite o rate limiting contar por IP real |
| **Gunicorn** | Servidor WSGI | O servidor nativo do Flask (`python run.py`) é para desenvolvimento — single-process, sem resiliência |
| **PostgreSQL** | Banco de dados | O agendamento usa `SELECT ... FOR UPDATE` e advisory locks para bloquear double-booking **entre processos** — recursos que o SQLite não tem |
| **Redis** | Armazenamento do rate limit | Com N workers, cada processo teria seu próprio contador em memória (limite N vezes mais frouxo); no Redis o contador é compartilhado |

> O SQLite padrão do `config.py` existe para desenvolvimento e avaliação. Em
> produção com múltiplos workers, use PostgreSQL — o driver (`psycopg2-binary`)
> já está no `requirements.txt`.

---

## 📋 Requisitos

- Servidor **Debian/Ubuntu** (ou derivado) com acesso root (`sudo`)
- **Python 3.8+** (`python3 --version`)
- Um **domínio** apontando para o servidor (ex.: `sigere.sua-instituicao.edu.br`) — necessário para o certificado HTTPS
- **Internet de saída** para os serviços externos usados pelo sistema:

  | Serviço | Uso |
  |---------|-----|
  | Open-Meteo | Clima do totem e portal |
  | BrasilAPI | Importação de feriados nacionais |
  | Nominatim/OpenStreetMap | Busca de endereço no cadastro de unidades |

- ⚠️ O servidor de desenvolvimento Flask **nunca** deve ser usado em produção.

---

## 1. Preparar o servidor

```bash
# Dependências do sistema
sudo apt update
sudo apt install python3-venv python3-pip nginx postgresql redis-server

# Código + ambiente virtual
sudo mkdir -p /var/www/sigere && sudo chown $USER /var/www/sigere
git clone https://github.com/jmisturini/SIGerE.git /var/www/sigere
cd /var/www/sigere
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt gunicorn
```

> 📝 O **Gunicorn não está no `requirements.txt`** de propósito: ele não funciona
> em Windows (máquina de desenvolvimento). Instale-o **apenas no servidor Linux**,
> como no comando acima.

Permissões — o Gunicorn roda como `www-data` e precisa escrever nos dados da instância:

```bash
sudo chown -R www-data:www-data /var/www/sigere/instance
sudo mkdir -p /var/log/sigere && sudo chown www-data:www-data /var/log/sigere
```

> A pasta `instance/` guarda os uploads (fichas técnicas `.docx` da Cozinha).
> O `.gitignore` a ignora — ela nasce vazia no clone, e o `chown` acima garante
> que o serviço consiga criá-la/preenchê-la.

---

## 2. Banco de dados (PostgreSQL)

Crie um usuário e um banco dedicados:

```bash
sudo -u postgres psql
```

```sql
CREATE USER sigere WITH PASSWORD 'escolha-uma-senha-forte';
CREATE DATABASE sigere OWNER sigere;
\q
```

Guarde as credenciais para o `DATABASE_URL` do passo 4. Boas práticas:

- Senha **gerada**, não digitada de cabeça
  (`openssl rand -base64 24`, por exemplo).
- O PostgreSQL padrão escuta só em `localhost` — mantenha assim; a aplicação
  roda na mesma máquina.
- Acesso futuro para manutenção: `sudo -u postgres psql sigere`.

---

## 3. Redis

Instalado no passo 1 (`redis-server`). Verifique:

```bash
redis-cli ping    # resposta esperada: PONG
```

O padrão da distribuição já escuta apenas em `127.0.0.1:6379`, sem senha —
suficiente, pois só a aplicação local o acessa. Ele será usado pelo
`RATELIMIT_STORAGE_URI` (passo 4); enquanto não configurado, os contadores
ficam em memória, separados por worker.

---

## 4. Variáveis de ambiente

Crie o arquivo `/var/www/sigere/.env` — **nunca versionado** (não faça commit;
o `systemd` o lê via `EnvironmentFile`):

```bash
SECRET_KEY="gere-com-o-comando-abaixo"
DATABASE_URL="postgresql://sigere:senha-forte@localhost:5432/sigere"
TOTEM_LATITUDE="-23.5505"
TOTEM_LONGITUDE="-46.6333"
RATELIMIT_STORAGE_URI="redis://localhost:6379/0"
```

Gerar a `SECRET_KEY`:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

| Variável | Obrigatória? | Descrição |
|----------|:------------:|-----------|
| `SECRET_KEY` | ✅ **Sim** | Base das sessões e do CSRF. Sem ela (fora do modo debug), a aplicação **se recusa a iniciar** |
| `DATABASE_URL` | ✅ Sim | URI PostgreSQL do passo 2 |
| `RATELIMIT_STORAGE_URI` | Recomendada | `redis://localhost:6379/0` — contador de rate limit compartilhado entre os workers |
| `TOTEM_LATITUDE` / `TOTEM_LONGITUDE` | Opcional | **Fallback** global do clima (totem/portal) para unidades sem coordenadas próprias. A localização de cada unidade é configurada no painel, com prioridade sobre estas variáveis |

Restrinja a leitura do arquivo:

```bash
chmod 600 /var/www/sigere/.env
```

> 🔑 **Sem `SECRET_KEY` definida, o sistema não sobe** — é um fail-fast
> intencional (`app/__init__.py`): com a chave de desenvolvimento qualquer um
> poderia forjar cookies de sessão. Comandos da CLI (`db upgrade`, `seed-admin`)
> não exigem a chave, pois não servem HTTP.

> 🍪 **Cookies endurecidos fora do modo debug:** a sessão recebe `Secure` (só
> trafega em HTTPS) e `SameSite=Lax`. Consequência prática: **login não funciona
> em HTTP puro** — o passo 8 (HTTPS) não é opcional.

---

## 5. Inicializar o banco

Com o `.env` criado (o `systemd` ainda não roda; exporte manualmente para os
comandos ou rode a partir de uma sessão com as variáveis carregadas):

```bash
cd /var/www/sigere
set -a; source .env; set +a    # carrega o .env no shell atual

sudo -u www-data venv/bin/flask --app run db upgrade     # cria o schema (Alembic)
sudo -u www-data venv/bin/flask --app run seed-admin     # cria SÓ o admin, senha definida interativamente (mín. 8 caracteres, oculta)
```

> ⚠️ **Não use `flask seed` em produção**: além do admin, ele oferece dados de
> demonstração (contas com senhas conhecidas, 29 salas fictícias etc.).
> `seed-admin` cria exclusivamente a conta do administrador.

Opcional — unidades do Senac SC (idempotente, pode rodar de novo sem duplicar):

```bash
sudo -u www-data venv/bin/flask --app run seed-unidades
```

Caso especial — banco que já existia de versões anteriores ao Alembic
(schema atual, sem `alembic_version`):

```bash
sudo -u www-data venv/bin/flask --app run db stamp head
```

> O boot da aplicação **não** cria nem altera schema — quem aplica é o Alembic,
> de forma segura até com múltiplos workers. Se o banco estiver vazio ou fora
> do fluxo, o boot apenas avisa no log.

---

## 6. Gunicorn via systemd

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
sudo mkdir -p /run/sigere
sudo chown www-data:www-data /run/sigere

# Ativar e iniciar
sudo systemctl daemon-reload
sudo systemctl enable --now sigere
sudo systemctl status sigere   # deve estar "active (running)"
```

Pontos de ajuste:

- **Workers:** use `--workers (2 × CPUs) + 1` como ponto de partida
  (`nproc` mostra o número de CPUs). `--threads 2` cobre requisições lentas
  simultâneas dentro de cada worker.
- **Entrypoint:** `run:app` — o `run.py` expõe `app = create_app()` no nível do módulo.
- **Timeout:** 120 s cobre exportações de relatórios maiores; alinhe com o
  `proxy_read_timeout` do Nginx (passo 7).
- **Reload × restart:** `sudo systemctl reload sigere` recarrega o código
  sem derrubar requisições em andamento (graceful); `restart` para tudo e sobe de novo.

---

## 7. Nginx como proxy reverso

Crie `/etc/nginx/sites-available/sigere`:

```nginx
server {
    listen 80;
    server_name sigere.sua-instituicao.edu.br;
    # Redirecione todo o tráfego HTTP para HTTPS após emitir o certificado (passo 8)

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

Detalhes que importam:

- **`client_max_body_size 16m`** precisa ser ≥ `MAX_CONTENT_LENGTH` da
  aplicação (16 MB) — do contrário uploads válidos morrem no Nginx com `413`.
- **`X-Forwarded-For` é obrigatório para o rate limiting por IP real.** Sem
  ele, todos os visitantes aparecem com o IP do Nginx e dividem o mesmo
  contador (o login, por exemplo, aceita 5 tentativas/min **no total** — veja
  [solução de problemas](#-solução-de-problemas)).
- **`instance/uploads/` não é servido pelo Nginx de propósito.** Fichas
  técnicas ficam fora de `static/` e só são baixadas pela rota autenticada
  `/kitchen/fichas/<id>/download` — nunca disponibilize essa pasta
  diretamente.

---

## 8. HTTPS (obrigatório)

Sem HTTPS o **login não funciona** em produção: fora do modo debug o cookie de
sessão recebe `Secure` e o navegador o recusa em HTTP puro.

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d sigere.sua-instituicao.edu.br
```

O certbot edita o bloco Nginx automaticamente: adiciona `listen 443 ssl` com o
certificado e o redirecionamento 80 → 443. A renovação é automática (timer do
systemd); para conferir:

```bash
sudo certbot renew --dry-run
```

> Todos os fluxos que dependem de sessão (login, CSRF, painel, Cozinha,
> download de fichas) passam a exigir o endereço em `https://`. A API de
> leitura também deve ser consumida em HTTPS — tokens Bearer trafegam no
> cabeçalho (ver [api-reservas.md](api-reservas.md)).

---

## 9. Primeiro acesso e configuração inicial

1. Acesse `https://sigere.sua-instituicao.edu.br/login` com o usuário `admin`
   e a senha definida no `seed-admin`.
2. O painel do super-admin exibe o **checklist de configuração inicial** —
   cada passo confere dados reais do banco e some quando completo:
   unidade, categorias, salas, professores, funcionários, cursos/disciplinas
   e feriados.
3. **Clima do totem:** para cada unidade, configure
   **Painel → Unidades → Editar → clima** (busca de endereço via
   Nominatim ou coordenadas manuais). As variáveis `TOTEM_*` do `.env`
   funcionam apenas como fallback.
4. **Feriados:** Painel → Feriados → *Importar da BrasilAPI* (por ano, escopo
   da unidade ativa).
5. **Tokens da API** (se houver apps externos): Painel Admin → Tokens da API
   — requer permissão `api:manage`. O valor completo é exibido uma única vez;
   mais detalhes e boas práticas em [api-reservas.md](api-reservas.md).

---

## 10. Atualizando a aplicação

Rotina padrão a cada nova versão:

```bash
cd /var/www/sigere
sudo -u www-data git pull
sudo -u www-data venv/bin/pip install -r requirements.txt gunicorn   # cobre dependências novas
sudo -u www-data venv/bin/flask --app run db upgrade                 # aplica migrações de schema
sudo systemctl restart sigere
# Se algum módulo novo trouxer permissões/papéis:
sudo -u www-data venv/bin/flask --app run sync-permissions
```

Notas:

- O boot executa um `sync-permissions` **silencioso e idempotente** a cada
  partida — permissões de módulos novos costumam entrar sem passo manual; o
  comando explícito serve para o fluxo documentado e para ver o que foi criado.
- Se a atualização só mudou código Python/templates (sem dependências nem
  migrações), `sudo systemctl reload sigere` basta e não derruba requisições.
- Migrações são seguras de rodar com o serviço no ar (Alembic), mas a prática
  recomendada é atualizar em janela de baixo uso.

---

## 🩺 Operação: monitoramento e backup

### Verificações do dia a dia

```bash
sudo systemctl status sigere        # serviço Gunicorn: active (running)?
sudo journalctl -u sigere -n 100    # últimas 100 linhas do serviço (boot, erros de arranque)
tail -f /var/log/sigere/error.log   # traceback de exceções da aplicação
tail -f /var/log/sigere/access.log  # acesso (IP, rota, status)
curl -fsS -o /dev/null -w '%{http_code}\n' https://SEU_DOMINIO/   # 200 esperado
```

Saúde dos dependentes: `sudo systemctl status postgresql redis-server nginx` e
`redis-cli ping` → `PONG`.

### Backup

O essencial para restaurar uma instalação completa:

| Item | Como |
|------|------|
| **Banco de dados** | `sudo -u postgres pg_dump sigere > backup-sigere-$(date +%F).sql` (agende via cron; restaure com `psql sigere < arquivo`) |
| **Uploads (fichas `.docx`)** | `/var/www/sigere/instance/uploads/` — copie a pasta inteira |
| **Configuração** | `/var/www/sigere/.env` (sem versionar; guarde em cofre de senhas) e `/etc/nginx/sites-available/sigere` + `/etc/systemd/system/sigere.service` |
| **Código** | O repositório git — a versão implantada é recuperável pelo commit/tag |

> O banco contém **hashes** de senha e os tokens da API **também são
> armazenados apenas como hash SHA-256** — um vazamento do backup não revela
> senhas nem tokens válidos. Ainda assim, trate o backup como confidencial.

### Dimensionamento

- Comece com os `--workers (2 × CPUs) + 1 --threads 2` do passo 6.
- O limite por resposta da API é `per_page=500`; painéis externos que
  atualizam a cada minuto ficam muito abaixo do limite de 120 req/min por IP.
- `--timeout 120` (Gunicorn) e `proxy_read_timeout 120s` (Nginx) formam um par
  — aumente os dois juntos se alguma exportação crescer.

---

## 🔧 Solução de problemas

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| `502 Bad Gateway` | Gunicorn parado ou socket sem permissão | `sudo systemctl status sigere`; confira `/run/sigere` (`chown www-data`); veja `journalctl -u sigere` |
| A aplicação não inicia: `RuntimeError: SECRET_KEY não configurada` | `.env` sem a chave ou `EnvironmentFile` apontando errado | Gere a chave (passo 4), confirme o caminho do `.env` na unit e `daemon-reload` |
| Login não mantém sessão / "recarrega a página" | Acesso por **HTTP puro** (cookie `Secure` rejeitado) ou relógio do servidor errado | Garanta HTTPS (passo 8); sincronize o relógio (`timedatectl`) |
| `429` em massa para todos os usuários | `X-Forwarded-For` não enviado — todos dividem o contador do IP do Nginx | Confirme os `proxy_set_header` do passo 7 |
| Rate limit "mais frouxo" que o configurado | Redis não configurado → contador em memória, por worker | Defina `RATELIMIT_STORAGE_URI="redis://localhost:6379/0"` e reinicie |
| Upload falha com `413` | `client_max_body_size` do Nginx menor que o arquivo | Aumente no Nginx (mantendo ≥ 16 MB da aplicação) |
| Upload falha com `500` / ficha não aparece | Permissão de escrita em `instance/uploads/` | `sudo chown -R www-data:www-data /var/www/sigere/instance` |
| Clima do totem "N/A" | Unidade sem coordenadas e/ou sem internet para Open-Meteo | Configure o clima por unidade no painel; teste a saída para `api.open-meteo.com` |
| API responde `401` para um token que funcionava | Token revogado/expirado ou conta do criador desativada | Reemita o token em Painel Admin → Tokens da API ([detalhes](api-reservas.md)) |
| `⚠️ Banco de dados vazio` no log após atualizar | Migração não aplicada | `sudo -u www-data venv/bin/flask --app run db upgrade` |
| Exportações Excel com erro de permissão | Diretório temporário/`static` sem permissão para `www-data` | Revise `chown` de `/var/www/sigere` (arquivos pertencem a `www-data`) |

Para investigar a fundo, o par mais útil é
`sudo journalctl -u sigere -e` (arranque/ambiente) +
`tail -100 /var/log/sigere/error.log` (traceback da aplicação).

---

## 🔒 Segurança em produção

O que a aplicação já faz sozinha (verificar que o ambiente permite cada item):

- **`SECRET_KEY` obrigatória** — fail-fast no boot sem ela (fora do modo debug).
- **Cookies de sessão endurecidos** — `Secure` automático fora do debug e `SameSite=Lax`.
- **CSRF global** — todo POST exige token; erros de CSRF caem em mensagem amigável.
- **Rate limiting** — login 5 tentativas/min por IP; API 120 req/min por endpoint/IP (Flask-Limiter + Redis).
- **Anti double-booking** — locks por (sala, data), revalidação atômica e, em PostgreSQL, `SELECT ... FOR UPDATE` + advisory locks.
- **Hash de senhas** com Werkzeug; troca forçada no primeiro login e após reset administrativo.
- **Tokens da API como hash SHA-256** — vazamento do banco não revela tokens; revogação imediata.
- **Uploads fora de `static/`** — `instance/uploads/` só é acessível por rota autenticada.
- **Limite de 16 MB** por requisição (`MAX_CONTENT_LENGTH`).
- **Proteção contra auto-desativação** — administrador não desativa a própria conta.

O que **você** precisa garantir no servidor:

- [ ] HTTPS válido e renovação automática do certificado (passo 8)
- [ ] `.env` com `chmod 600`, fora do git, com `SECRET_KEY` gerada
- [ ] Nginx enviando `X-Forwarded-For` (rate limit por IP real)
- [ ] `RATELIMIT_STORAGE_URI` apontando para Redis (contadores compartilhados)
- [ ] PostgreSQL e Redis escutando apenas em `localhost`
- [ ] Firewall mínimo: apenas 22, 80 e 443 abertos (`sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable`)
- [ ] Servidor atualizado (`sudo apt update && sudo apt upgrade` periódicos ou `unattended-upgrades`)
- [ ] Backups agendados do banco e de `instance/uploads/` (seção de operação)
- [ ] Conta `admin` com senha forte — **nunca** rodar `flask seed` (dados de demonstração) no servidor

---

## ❓ Perguntas frequentes

**Posso usar SQLite em produção se a instituição for pequena?**
Tecnicamente o sistema sobe, mas não é recomendado com múltiplos workers: sem
`SELECT ... FOR UPDATE` e advisory locks, a proteção contra double-booking
concorrente perde eficácia, e o rate limit por Redis continua valendo. Para
avaliação rápida, SQLite funciona; para operação real, PostgreSQL.

**Quantos workers devo configurar?**
`(2 × CPUs) + 1` é o ponto de partida clássico do Gunicorn. Observe
`error.log` e o uso de CPU em horário de pico; exportações grandes se beneficiam
mais das `--threads` do que de workers extras.

**Como aplico uma atualização sem derrubar usuários?**
`sudo systemctl reload sigere` faz reload graceful (workers novos assumem sem
cortar requisições em andamento). Use `restart` quando o `.env` ou a unit do
systemd mudarem — variáveis de ambiente só são relidas no restart.

**Preciso rodar `sync-permissions` em toda atualização?**
Não obrigatoriamente: o boot roda a mesma sincronização em modo silencioso.
Rode o comando explícito quando a nota de versão citar permissões/papéis novos
e você quiser ver o que foi criado.

**Onde ficam os arquivos que os usuários enviam?**
`/var/www/sigere/instance/uploads/`. Não versionados, não servidos pelo Nginx —
o download passa pela rota autenticada do sistema. Inclua a pasta no backup.

**Esqueci a senha do `admin` — como recupero?**
Pelo banco não (há apenas hash). O caminho suportado: outro administrador usa
Painel Admin → Usuários → *Resetar senha* (gera senha temporária exibida uma
única vez). Sem outro admin, recrie a conta em um banco de testes e copie o
hash de senha para o registro do `admin` em produção, ou recrie o usuário via
uma sessão `flask --app run shell` com `generate_password_hash`.

**A API fica pública na internet?**
Os endpoints `/api/v1/...` respondem sem token com o payload público
(data, horário, sala e título de reservas aprovadas) — é o desenho do produto
(totens e apps externos). Tokens Bearer habilitam o payload completo. Boas
práticas de exposição e autenticação em [api-reservas.md](api-reservas.md).

**Como mudar o domínio do sistema depois?**
Atualize `server_name` no Nginx, reemita o certificado
(`sudo certbot --nginx -d novo.dominio`), confirme `client_max_body_size` e
`reload nginx`. A aplicação em si não guarda o domínio — nada a ajustar no `.env`.
