"""Setup interativo do SIGerE.

Guia a implantação e a manutenção do sistema em um único comando:

    python setup_interativo.py

O menu inicial oferece três modos:

  1. Instalação completa — do zero, em uma máquina nova:
     1. Confere o Python (3.10+) e cria/reaproveita o ambiente virtual .venv;
     2. Instala as dependências (requirements.txt);
     3. Gera o arquivo .env (SECRET_KEY, banco de dados, Redis do rate limit, clima
        do totem);
     4. Cria a pasta de dados da instância (instance/uploads — fora do git);
     5. Cria/atualiza o schema do banco (flask --app run db upgrade);
     6. Popula os dados iniciais — implantação real (seed-admin), demonstração
        (seed / seed-demo) ou migração do sistema legado (import-legacy);
     7. Opcional: cadastra as unidades do Senac SC (seed-unidades);
     8. Opcional: inicia o servidor de desenvolvimento.

  2. Atualizar o sistema — rotina da seção "Atualizando a aplicação" de
     docs/implantacao-producao.md: backup de segurança, git pull, dependências,
     migrações (db upgrade) e sincronização de permissões (sync-permissions).

  3. Restaurar backup — escolhe um snapshot gerado pelo `flask backup`
     (SQLite ou PostgreSQL), sobrescreve o banco com ele e aplica as migrações
     pendentes.

Seguro de rodar mais de uma vez: etapas já concluídas são reaproveitadas e
cada comando de seed tem guarda própria contra duplicação de dados.

Somente biblioteca padrão — o script roda antes das dependências existirem.
"""
import gzip
import os
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote

RAIZ = Path(__file__).resolve().parent
ARQUIVO_ENV = RAIZ / '.env'
ARQUIVO_REQ = RAIZ / 'requirements.txt'
ARQUIVO_DB = RAIZ / 'reservation.db'
JSON_UNIDADES = RAIZ / 'docs' / 'unidades-senac-sc.json'

# Etapas concluídas, exibidas no resumo final.
passos = []


# ─────────────────────────── utilidades de terminal ───────────────────────────

def titulo(texto):
    traco = '━' * max(0, 62 - len(texto))
    print(f"\n\033[1;36m── {texto} {traco}\033[0m")


def ok(texto):
    print(f"\033[32m✅ {texto}\033[0m")
    passos.append(texto)


def aviso(texto):
    print(f"\033[33m⚠️  {texto}\033[0m")


def erro(texto):
    print(f"\033[31m❌ {texto}\033[0m")


def sim_nao(pergunta, padrao=True):
    sufixo = '[S/n]' if padrao else '[s/N]'
    while True:
        resposta = input(f"{pergunta} {sufixo} ").strip().lower()
        if not resposta:
            return padrao
        if resposta in ('s', 'sim', 'y', 'yes'):
            return True
        if resposta in ('n', 'nao', 'não', 'no'):
            return False
        print("   Responda 's' ou 'n'.")


def escolher(pergunta, opcoes, padrao=1):
    """Exibe opções numeradas e devolve o número escolhido (1-based)."""
    print(f"\n{pergunta}")
    for numero, descricao in enumerate(opcoes, start=1):
        marcador = '>' if numero == padrao else ' '
        print(f"  {marcador} {numero}) {descricao}")
    while True:
        resposta = input(f"Escolha [{padrao}]: ").strip()
        if not resposta:
            return padrao
        if resposta.isdigit() and 1 <= int(resposta) <= len(opcoes):
            return int(resposta)
        print(f"   Digite um número entre 1 e {len(opcoes)}.")


def entrada(pergunta, padrao=''):
    sufixo = f" [{padrao}]" if padrao else ''
    resposta = input(f"{pergunta}{sufixo}: ").strip()
    return resposta or padrao


# ────────────────────────────── ambiente virtual ──────────────────────────────

def python_da_venv():
    caminho = 'Scripts/python.exe' if os.name == 'nt' else 'bin/python'
    return RAIZ / '.venv' / caminho


def preparar_venv(rotulo='1. Ambiente virtual (Python)'):
    titulo(rotulo)

    if sys.version_info < (3, 10):
        erro(f"Python 3.10 ou superior é necessário (encontrado {sys.version.split()[0]}).\n"
             "   As dependências fixadas no requirements.txt (limits, redis) exigem 3.10+.")
        raise SystemExit(1)
    print(f"   Python {sys.version.split()[0]} — ok.")

    venv_python = python_da_venv()
    if venv_python.exists():
        print(f"   Ambiente virtual existente reaproveitado: {venv_python}")
        return str(venv_python)

    aviso('Ambiente virtual .venv não encontrado — ele será criado agora.')
    if subprocess.run([sys.executable, '-m', 'venv', str(RAIZ / '.venv')]).returncode != 0:
        erro('Falha ao criar o ambiente virtual. Verifique se o módulo venv está disponível.')
        raise SystemExit(1)
    ok('Ambiente virtual criado em .venv')
    return str(venv_python)


# ─────────────────────────────── dependências ─────────────────────────────────

def instalar_dependencias(venv_python, rotulo='2. Dependências (requirements.txt)',
                          perguntar_reinstalacao=True):
    titulo(rotulo)

    # `redis` na checagem: entrou depois no requirements.txt — quem já tinha a
    # venv pronta não seria perguntado sobre reinstalar e o pacote faltaria
    # (rate limit com RATELIMIT_STORAGE_URI apontando para o Redis quebra no
    # boot com ConfigurationError).
    instalado = subprocess.run(
        [venv_python, '-c', 'import flask, flask_migrate, dotenv, redis'],
        capture_output=True,
    ).returncode == 0
    if instalado and not perguntar_reinstalacao:
        # Modos de manutenção (restauração): só garante o necessário para os
        # comandos flask, sem interromper o fluxo com perguntas.
        print('   Dependências principais já presentes.')
        return
    if instalado and not sim_nao('As dependências principais já estão instaladas. Reinstalar?',
                                 padrao=False):
        print('   Instalação pulada.')
        return

    print('   Instalando (pode levar alguns minutos)...')
    if subprocess.run(
        [venv_python, '-m', 'pip', 'install', '-r', str(ARQUIVO_REQ)]
    ).returncode != 0:
        erro('Falha ao instalar as dependências. Rode manualmente e execute este setup de novo:\n'
             f'   "{venv_python}" -m pip install -r requirements.txt')
        raise SystemExit(1)
    ok('Dependências instaladas.')


# ────────────────────────────── arquivo .env ──────────────────────────────────

def ler_env(caminho):
    """Lê o .env em um dicionário, para repassar aos comandos executados."""
    valores = {}
    for linha in Path(caminho).read_text(encoding='utf-8').splitlines():
        linha = linha.strip()
        if not linha or linha.startswith('#') or '=' not in linha:
            continue
        chave, _, valor = linha.partition('=')
        valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def host_porta_da_url_redis(url):
    """Host e porta de uma URI redis:// (ignora credenciais e banco) — para o
    teste de conexão antes de gravar o .env."""
    autoridade = url.split('//', 1)[-1].split('/', 1)[0].split('@')[-1]
    host, _, porta = autoridade.partition(':')
    return host or 'localhost', int(porta) if porta.isdigit() else 6379


def configurar_env():
    titulo('3. Configuração do ambiente (.env)')

    if ARQUIVO_ENV.exists():
        aviso(f"Já existe um {ARQUIVO_ENV.name}. Chaves definidas hoje:")
        for chave in ler_env(ARQUIVO_ENV):
            print(f"   • {chave}")
        if not sim_nao('Substituir o .env com uma nova configuração?', padrao=False):
            print('   .env mantido sem alterações.')
            return ler_env(ARQUIVO_ENV)
        backup = RAIZ / '.env.bak'
        backup.write_text(ARQUIVO_ENV.read_text(encoding='utf-8'), encoding='utf-8')
        print(f"   Cópia de segurança salva em {backup.name}.")

    ambiente = escolher(
        'Qual o perfil desta instalação?',
        ['Desenvolvimento (FLASK_DEBUG=true, sem exigência de HTTPS)',
         'Produção (SECRET_KEY obrigatória, cookies Secure)'],
        padrao=1,
    )
    desenvolvimento = ambiente == 1

    # SECRET_KEY: gerada automaticamente — em produção a aplicação se recusa a
    # iniciar sem ela e, em desenvolvimento, evita a chave padrão do código.
    chave = secrets.token_urlsafe(48)
    if sim_nao('Usar uma SECRET_KEY gerada automaticamente (recomendado)?', padrao=True):
        print(f'   Chave gerada: {chave}')
    else:
        while True:
            chave = entrada('Digite a sua SECRET_KEY (vazio volta para a gerada)')
            if len(chave) >= 32:
                break
            if not chave:
                chave = secrets.token_urlsafe(48)
                print(f'   Usando a chave gerada: {chave}')
                break
            aviso('A chave deve ter pelo menos 32 caracteres.')

    linhas = [f'SECRET_KEY="{chave}"']
    if desenvolvimento:
        linhas.append('FLASK_DEBUG="true"')

    # Banco de dados: o padrão do projeto é SQLite na raiz; produção usa
    # PostgreSQL (necessário para os travas concorrentes do agendamento).
    banco = escolher(
        'Banco de dados:',
        ['SQLite — arquivo reservation.db na raiz (padrão, sem servidor)',
         'PostgreSQL — recomendado em produção (informe a URL de conexão)'],
        padrao=1 if desenvolvimento else 2,
    )
    if banco == 2:
        while True:
            url = entrada('DATABASE_URL (ex.: postgresql://usuario:senha@localhost:5432/sigere)')
            if url.startswith(('postgresql://', 'postgres://')):
                break
            aviso("A URL deve começar com 'postgresql://'.")
        linhas.append(f'DATABASE_URL="{url}"')
    elif ARQUIVO_DB.exists():
        print(f'   O arquivo {ARQUIVO_DB.name} já existe e será reaproveitado.')

    # Redis do rate limit: com múltiplos workers do Gunicorn, contador em
    # memória seria um por processo (limite N vezes mais frouxo). Guia:
    # docs/implantacao-producao.md, seção "Redis".
    if not desenvolvimento and sim_nao(
            'Rate limit no Redis (recomendado com múltiplos workers do Gunicorn)?',
            padrao=True):
        while True:
            url_redis = entrada('RATELIMIT_STORAGE_URI', 'redis://localhost:6379/0')
            if url_redis.startswith('redis://'):
                break
            aviso("A URL deve começar com 'redis://'.")
        host_redis, porta_redis = host_porta_da_url_redis(url_redis)
        try:
            with socket.create_connection((host_redis, porta_redis), timeout=2):
                print(f'   Redis acessível em {host_redis}:{porta_redis}.')
        except OSError:
            aviso(f'Redis não respondeu em {host_redis}:{porta_redis} — instale/inicie o '
                  'serviço (ex.: sudo apt install redis-server) antes de servir a '
                  'aplicação, ou as rotas com rate limit responderão erro.')
        linhas.append(f'RATELIMIT_STORAGE_URI="{url_redis}"')

    lat = entrada('Latitude do totem (clima, fallback global; vazio usa -23.5505)', '-23.5505')
    linhas.append(f'TOTEM_LATITUDE="{lat}"')
    lon = entrada('Longitude do totem (vazio usa -46.6333)', '-46.6333')
    linhas.append(f'TOTEM_LONGITUDE="{lon}"')

    ARQUIVO_ENV.write_text('\n'.join(linhas) + '\n', encoding='utf-8')
    ok(f".env criado (perfil {'desenvolvimento' if desenvolvimento else 'produção'}).")
    if not desenvolvimento:
        aviso('Proteja o arquivo .env — contém a SECRET_KEY e nunca deve ser versionado.')

    return ler_env(ARQUIVO_ENV)


# ───────────────────────── pasta de dados da instância ───────────────────────

def preparar_instance(env):
    """Cria instance/uploads (uploads de usuários, ex.: fichas técnicas .docx).

    A pasta é ignorada pelo .gitignore e o Flask não a cria no boot — sem ela,
    o chown para o usuário do serviço falha no servidor e o primeiro upload
    responde 500 (o www-data não pode criá-la dentro do projeto).
    """
    titulo('4. Pasta de dados da instância (instance/uploads)')
    pasta = RAIZ / 'instance' / 'uploads'
    if pasta.is_dir():
        print('   Pasta existente reaproveitada: instance/uploads')
        return
    pasta.mkdir(parents=True, exist_ok=True)
    ok('Pasta instance/uploads criada (uploads ficam fora do git).')
    if env.get('FLASK_DEBUG', '').lower() not in ('1', 'true', 'yes', 'on'):
        aviso('Em produção o Gunicorn roda como www-data — ajuste o dono da pasta: '
              'sudo chown -R www-data:www-data instance '
              '(docs/implantacao-producao.md, passo 1).')


# ───────────────────────────── schema do banco ────────────────────────────────

def executar_flask(venv_python, env, argumentos):
    """Roda um comando da CLI do Flask com o .env aplicado e o console herdado
    (necessário para prompts interativos, como a senha do seed-admin)."""
    if subprocess.run([venv_python, '-m', 'flask', '--app', 'run'] + argumentos,
                      env=env).returncode != 0:
        erro(f"Falha no comando: flask --app run {' '.join(argumentos)} — veja a mensagem acima.")
        raise SystemExit(1)


def aplicar_schema(venv_python, env, rotulo='5. Schema do banco (Flask-Migrate/Alembic)'):
    titulo(rotulo)
    print('   Executando: flask --app run db upgrade')
    executar_flask(venv_python, env, ['db', 'upgrade'])
    ok('Schema do banco criado/atualizado (alembic head).')


# ──────────────────────────── dados iniciais ──────────────────────────────────

def popular_dados(venv_python, env):
    titulo('6. Dados iniciais')

    if ARQUIVO_DB.exists() and ARQUIVO_DB.stat().st_size > 4096:
        aviso(f'O banco {ARQUIVO_DB.name} já existe. Os comandos de seed pulam a população '
              'quando já há dados — para recomeçar do zero, apague o arquivo antes.')

    opcao = escolher(
        'Como o sistema deve ser populado?',
        [
            'Implantação real — cria apenas o admin e pede uma senha sua (seed-admin)',
            'Demonstração simples — admin/admin123 + salas, usuários e reservas (seed)',
            'Demonstração completa — todos os módulos, cozinha, financeiro e API (seed-demo)',
            'Migração do sistema legado — importa o dump MySQL do sistema antigo (import-legacy)',
            'Não popular agora (posso rodar este setup de novo depois)',
        ],
        padrao=1,
    )

    if opcao == 1:
        print('   A senha será pedida pelo próprio comando (mínimo 8 caracteres, digitação oculta).')
        executar_flask(venv_python, env, ['seed-admin'])
        ok('Comando seed-admin executado — a conta admin@school.edu está pronta '
           '(se já existia, foi preservada).')
        return 'seed-admin'
    if opcao == 2:
        executar_flask(venv_python, env, ['seed'])
        ok('Seed básico executado (admin@school.edu / admin123 e dados de demonstração opcionais).')
        return 'seed'
    if opcao == 3:
        argumentos = ['seed-demo']
        if sim_nao('Apagar uma demonstração anterior e recriar (--reset)?', padrao=False):
            argumentos.append('--reset')
        executar_flask(venv_python, env, argumentos)
        ok('Cenário de demonstração completo criado (seed-demo).')
        return 'seed-demo'
    if opcao == 4:
        while True:
            dump = entrada('Caminho do dump .sql (phpMyAdmin) — vazio para cancelar')
            if not dump:
                print('   Migração cancelada.')
                return None
            caminho_dump = Path(dump).expanduser()
            if caminho_dump.exists():
                break
            erro(f'Arquivo não encontrado: {dump}')
        executar_flask(venv_python, env,
                       ['import-legacy', '--dump', str(caminho_dump)])
        ok('Dados do sistema legado importados (usuários iniciam com troca de senha obrigatória).')
        return 'import-legacy'

    print('   População pulada — rode este setup novamente ou os comandos do README quando quiser.')
    return None


def unidades_senac(venv_python, env):
    titulo('7. Unidades do Senac SC (opcional)')
    if not JSON_UNIDADES.exists():
        aviso(f'Arquivo {JSON_UNIDADES.name} não encontrado — etapa indisponível.')
        return
    if not sim_nao('Cadastrar as unidades educacionais do Senac SC (seed-unidades)?', padrao=False):
        print('   Etapa pulada — pode ser feita depois: flask --app run seed-unidades')
        return
    executar_flask(venv_python, env, ['seed-unidades'])
    ok('Unidades cadastradas (idempotente — pode rodar de novo sem duplicar).')


# ───────────────────────── modo: atualizar o sistema ─────────────────────────

def preparar_manutencao():
    """Base dos modos de manutenção (atualizar/restaurar): venv pronto e .env
    existente — estes modos não reconfiguram nada, exigem instalação concluída."""
    venv_python = preparar_venv(rotulo='Ambiente virtual (Python)')
    if not ARQUIVO_ENV.exists():
        erro('Arquivo .env não encontrado — atualização e restauração exigem uma '
             'instalação já configurada.\n   Rode a instalação completa primeiro (opção 1 do menu).')
        raise SystemExit(1)
    env_arquivo = ler_env(ARQUIVO_ENV)
    # Mesma coisa da instalação completa: repassa o .env no ambiente do processo
    # para os comandos flask não dependerem da leitura do arquivo.
    return venv_python, {**os.environ, **env_arquivo}, env_arquivo


def atualizar_sistema():
    """Rotina da seção "Atualizando a aplicação" de docs/implantacao-producao.md,
    guiada: backup de segurança → git pull → dependências → db upgrade →
    sync-permissions."""
    titulo('Modo: atualização do sistema')
    venv_python, env_processo, env_arquivo = preparar_manutencao()

    titulo('Backup de segurança')
    if sim_nao('Criar um backup do banco antes de atualizar (recomendado)?', padrao=True):
        executar_flask(venv_python, env_processo, ['backup'])
    else:
        aviso('Sem backup — se algo der errado na atualização, não haverá ponto de retorno fácil.')

    titulo('Código (git)')
    if (RAIZ / '.git').is_dir():
        print('   Executando: git pull --ff-only')
        if subprocess.run(['git', 'pull', '--ff-only'], cwd=RAIZ).returncode != 0:
            erro('Falha no git pull. Resolva manualmente (alterações locais não enviadas: '
                 'git stash ou commit) e rode o setup de novo.')
            raise SystemExit(1)
        ok('Código atualizado do repositório.')
    else:
        aviso('Sem repositório git nesta pasta — etapa de código pulada (atualize os '
              'arquivos pelo seu método de implantação).')

    # Sem pergunta de reinstalação: a rotina documentada sempre roda o pip —
    # dependências novas do release não são detectadas pela checagem de imports.
    titulo('Dependências (requirements.txt)')
    print('   Instalando/atualizando (pode levar alguns minutos)...')
    if subprocess.run(
            [venv_python, '-m', 'pip', 'install', '-r', str(ARQUIVO_REQ)]).returncode != 0:
        erro('Falha ao instalar as dependências. Rode manualmente e execute este setup de novo:\n'
             f'   "{venv_python}" -m pip install -r requirements.txt')
        raise SystemExit(1)
    ok('Dependências em dia com o requirements.txt.')

    aplicar_schema(venv_python, env_processo,
                   rotulo='Schema do banco (Flask-Migrate/Alembic)')

    titulo('Permissões e papéis')
    print('   Executando: flask --app run sync-permissions')
    executar_flask(venv_python, env_processo, ['sync-permissions'])
    ok('Permissões e papéis sincronizados (sync-permissions).')

    titulo('Resumo da atualização')
    for passo in passos:
        print(f'   • {passo}')
    print('\n   Próximos passos:')
    if env_arquivo.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on'):
        iniciar_servidor(venv_python, env_processo, rotulo='Servidor de desenvolvimento')
    else:
        print('     • Reinicie o serviço: sudo systemctl restart sigere')
        print('     • Teste o login e a navegação: http://localhost:5000')


# ─────────────────────────── modo: restaurar backup ──────────────────────────

NOME_MOTOR = {'sqlite': 'SQLite', 'postgres': 'PostgreSQL'}


def classificar_uri(uri):
    """Motor e dados de conexão a partir da DATABASE_URL: ('sqlite', caminho do
    arquivo), ('postgres', None) ou (None, None) quando o setup não sabe
    restaurar. Mesma convenção do SQLAlchemy: 3 barras = caminho relativo,
    4 = absoluto (mesma lógica de app/backup.py)."""
    if ':memory:' in uri:
        return None, None
    if uri.startswith('sqlite'):
        resto = uri.split('sqlite://', 1)[1]
        caminho = resto[1:] if resto.startswith('//') else resto.lstrip('/')
        caminho = Path(caminho)
        return 'sqlite', caminho if caminho.is_absolute() else RAIZ / caminho
    if uri.startswith(('postgres://', 'postgresql://')):
        return 'postgres', None
    return None, None


def parametros_postgres(uri):
    """Componentes de conexão de uma URI postgresql:// (para o ambiente do psql)."""
    partes = urlsplit(uri)
    sslmodes = parse_qs(partes.query).get('sslmode')
    return {
        'host': partes.hostname or 'localhost',
        'porta': partes.port or 5432,
        'usuario': unquote(partes.username) if partes.username else None,
        'senha': unquote(partes.password) if partes.password else None,
        'banco': (partes.path or '').lstrip('/'),
        'sslmode': sslmodes[0] if sslmodes else None,
    }


def _ambiente_psql(parametros):
    """Credenciais via variáveis de ambiente (PGHOST/PGPASSWORD...): o `ps` de
    outros usuários mostra a linha de comando, nunca o ambiente — mesma técnica
    do flask backup (app/backup.py)."""
    env = os.environ.copy()
    env['PGHOST'] = str(parametros['host'])
    env['PGPORT'] = str(parametros['porta'])
    env['PGDATABASE'] = parametros['banco']
    if parametros['usuario']:
        env['PGUSER'] = parametros['usuario']
    if parametros['senha']:
        env['PGPASSWORD'] = parametros['senha']
    if parametros['sslmode']:
        env['PGSSLMODE'] = parametros['sslmode']
    return env


def tamanho_legivel(caminho):
    tamanho = os.path.getsize(caminho)
    for unidade in ('B', 'KB', 'MB', 'GB'):
        if tamanho < 1024 or unidade == 'GB':
            return f'{tamanho:.1f} {unidade}' if unidade != 'B' else f'{tamanho} B'
        tamanho /= 1024


def motor_do_arquivo(caminho):
    """Motor marcado no nome do backup gerado pelo flask backup
    (`sigere-...-sqlite.sqlite.gz` / `sigere-...-postgres.sql.gz`) —
    None quando o nome não marca (arquivo manual)."""
    nome = Path(caminho).name
    if '-sqlite.' in nome:
        return 'sqlite'
    if '-postgres.' in nome:
        return 'postgres'
    return None


def escolher_arquivo_backup(motor, env):
    """Oferece os backups da pasta configurada (BACKUP_DIR ou ./backups) e
    devolve o caminho escolhido (None = cancelado)."""
    pasta = Path(env.get('BACKUP_DIR') or (RAIZ / 'backups'))
    elegiveis = []
    if pasta.is_dir():
        for arq in sorted(pasta.glob('sigere-*.gz'),
                          key=lambda a: a.stat().st_mtime, reverse=True):
            if motor_do_arquivo(arq) in (None, motor):
                elegiveis.append(arq)

    if elegiveis:
        recentes = elegiveis[:10]
        opcoes = [f'{a.name} ({tamanho_legivel(str(a))})' for a in recentes]
        opcoes.append('Outro arquivo (informar o caminho)')
        escolha = escolher('Qual backup restaurar? (mais recente primeiro)', opcoes, padrao=1)
        if escolha <= len(recentes):
            return elegiveis[escolha - 1]
    else:
        aviso(f'Nenhum backup na pasta {pasta} — o flask backup grava ali por padrão.')

    while True:
        caminho = entrada('Caminho do arquivo de backup (.gz) — vazio para cancelar')
        if not caminho:
            return None
        candidato = Path(caminho).expanduser()
        if not candidato.is_file():
            erro(f'Arquivo não encontrado: {caminho}')
            continue
        marca = motor_do_arquivo(candidato)
        if marca and marca != motor:
            erro(f'O arquivo é um backup de {NOME_MOTOR[marca]}, mas o banco configurado '
                 f'é {NOME_MOTOR[motor]} — informe o backup do motor correto.')
            continue
        return candidato


def restaurar_sqlite(caminho_db, arquivo_backup):
    """Sobrescreve o arquivo do banco com o snapshot gzip
    (docs/implantacao-producao.md, seção "Restaurar")."""
    with gzip.open(arquivo_backup, 'rb') as gz:
        cabecalho = gz.read(16)
    if not cabecalho.startswith(b'SQLite format 3'):
        erro('O arquivo não parece um snapshot SQLite válido (cabeçalho inesperado) — '
             'restauração abortada, o banco atual não foi tocado.')
        raise SystemExit(1)

    caminho_db.parent.mkdir(parents=True, exist_ok=True)
    try:
        with gzip.open(arquivo_backup, 'rb') as origem, open(caminho_db, 'wb') as destino:
            shutil.copyfileobj(origem, destino)
    except PermissionError:
        erro(f'O arquivo {caminho_db} está em uso — pare a aplicação/servidor e rode a '
             'restauração de novo.')
        raise SystemExit(1)

    # Restos de WAL de sessões anteriores podem invalidar o banco recém-gravado.
    for sufixo in ('-wal', '-shm'):
        lateral = Path(f'{caminho_db}{sufixo}')
        if lateral.exists():
            lateral.unlink()


def localizar_binario(nome, dica_instalacao):
    """Binário no PATH ou caminho informado pelo operador (None = cancelado)."""
    binario = shutil.which(nome)
    if binario:
        return binario
    while True:
        informado = entrada(f"Binário '{nome}' não está no PATH — informe o caminho completo "
                            f"(vazio cancela; {dica_instalacao})")
        if not informado:
            return None
        candidato = Path(informado).expanduser()
        if candidato.is_file():
            return str(candidato)
        erro(f'Arquivo não encontrado: {informado}')


def restaurar_postgres(uri, arquivo_backup):
    """Executa o dump no PostgreSQL via psql. Devolve True quando restaurou."""
    parametros = parametros_postgres(uri)
    env_psql = _ambiente_psql(parametros)

    psql = localizar_binario(
        'psql',
        'instale o cliente PostgreSQL — Debian/Ubuntu: sudo apt install postgresql-client')
    if not psql:
        print('   Restauração cancelada.')
        return False

    if sim_nao('Recriar o banco antes de restaurar (apaga o atual e restaura limpo — recomendado)?',
               padrao=True):
        pasta_bin = Path(psql).parent
        sufixo = '.exe' if os.name == 'nt' else ''
        dropdb, createdb = pasta_bin / f'dropdb{sufixo}', pasta_bin / f'createdb{sufixo}'
        if not (dropdb.is_file() and createdb.is_file()):
            erro(f'Binários dropdb/createdb não encontrados ao lado de "{psql}".')
            raise SystemExit(1)
        print(f'   Recriando o banco {parametros["banco"]} em '
              f'{parametros["host"]}:{parametros["porta"]}...')
        if subprocess.run([str(dropdb), '--if-exists', parametros['banco']],
                          env=env_psql).returncode != 0:
            erro('Falha ao apagar o banco (dropdb) — confira as credenciais no .env.')
            raise SystemExit(1)
        dono = ['--owner', parametros['usuario']] if parametros['usuario'] else []
        if subprocess.run([str(createdb), *dono, parametros['banco']],
                          env=env_psql).returncode != 0:
            erro('Falha ao criar o banco (createdb).')
            raise SystemExit(1)
        print('   Banco vazio recriado.')

    print('   Restaurando o dump (pode levar alguns minutos)...')
    with gzip.open(arquivo_backup, 'rb') as dump:
        resultado = subprocess.run([psql, '-q', '-v', 'ON_ERROR_STOP=1'],
                                   stdin=dump, env=env_psql)
    if resultado.returncode != 0:
        erro('Falha na restauração — o psql parou no primeiro erro (ON_ERROR_STOP). '
             'Se o banco não estava vazio, tente de novo recriando-o antes.')
        raise SystemExit(1)
    return True


def restaurar_backup():
    titulo('Modo: restauração de backup')
    venv_python, env_processo, env_arquivo = preparar_manutencao()

    instalar_dependencias(venv_python, rotulo='Dependências do ambiente',
                          perguntar_reinstalacao=False)

    uri = env_arquivo.get('DATABASE_URL') or f'sqlite:///{ARQUIVO_DB}'
    motor, caminho_db = classificar_uri(uri)
    if motor is None:
        erro(f'DATABASE_URL não suportada para restauração: "{uri}".\n'
             '   O setup restaura bancos SQLite ou PostgreSQL (os mesmos do flask backup).')
        raise SystemExit(1)

    titulo(f'Backup a restaurar (banco {NOME_MOTOR[motor]})')
    arquivo = escolher_arquivo_backup(motor, env_arquivo)
    if arquivo is None:
        print('   Restauração cancelada.')
        return

    if motor == 'sqlite':
        destino = caminho_db
    else:
        p = parametros_postgres(uri)
        destino = f'{p["banco"]} em {p["host"]}:{p["porta"]}'
    aviso(f'A restauração SUBSTITUI todos os dados atuais do banco ({destino}).')
    aviso('Se o servidor estiver no ar, pare-o antes (Ctrl+C no Flask de desenvolvimento; '
          'sudo systemctl stop sigere em produção).')
    if not sim_nao('Confirma a restauração? Os dados atuais serão perdidos.', padrao=False):
        print('   Restauração cancelada.')
        return

    if sim_nao('Guardar um backup do estado atual antes de sobrescrever (recomendado)?',
               padrao=True):
        executar_flask(venv_python, env_processo, ['backup'])

    titulo(f'Restaurando ({NOME_MOTOR[motor]})')
    if motor == 'sqlite':
        restaurar_sqlite(caminho_db, arquivo)
        ok(f'Banco {caminho_db.name} restaurado de {arquivo.name}.')
    else:
        if not restaurar_postgres(uri, arquivo):
            return
        ok(f'Dump PostgreSQL aplicado a partir de {arquivo.name}.')

    titulo('Migrações após o backup')
    print('   Executando: flask --app run db upgrade (aplica migrações feitas depois do backup)')
    executar_flask(venv_python, env_processo, ['db', 'upgrade'])
    ok('Migrações aplicadas ao banco restaurado (alembic head).')

    titulo('Resumo da restauração')
    for passo in passos:
        print(f'   • {passo}')
    print('\n   Próximos passos:')
    print('     • Teste o login e a navegação: http://localhost:5000')
    if env_arquivo.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on'):
        print('     • Suba o servidor: flask --app run run --debug')
    else:
        print('     • Reinicie o serviço: sudo systemctl restart sigere')
    print('     • O backup do banco não inclui os uploads (instance/uploads) nem o .env — '
          'para reconstruir uma máquina inteira, copie também essas partes '
          '(docs/implantacao-producao.md, "restaurar uma instalação completa").')


# ────────────────────────────── resumo / servidor ─────────────────────────────

def resumo_final(env, modo_dados):
    titulo('Resumo da instalação')
    for passo in passos:
        print(f'   • {passo}')

    desenvolvimento = env.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on')

    print('\n   Acessos:')
    if modo_dados in ('seed', 'seed-demo'):
        print('     • admin@school.edu / admin123 (demonstração — troque a senha!)')
    if modo_dados == 'seed-admin':
        print('     • admin@school.edu + a senha que você definiu')
    if modo_dados == 'import-legacy':
        print('     • Cada usuário entra com a senha antiga e troca no primeiro acesso')
    print('     • Aplicação: http://localhost:5000')
    print('     • No primeiro acesso, o painel do super-admin exibe o checklist de '
          'configuração inicial (unidade, categorias, salas, pessoas, cursos).')

    print('\n   Próximos passos:')
    if desenvolvimento:
        print('     • Servidor de desenvolvimento: flask --app run run --debug')
    else:
        print('     • Sirva atrás de Gunicorn + Nginx (guia: docs/implantacao-producao.md) — '
              'não use python run.py em produção.')
    print('     • Atualizações futuras: python setup_interativo.py — modo '
          '"Atualizar o sistema" (backup, git pull, dependências, db upgrade '
          'e sync-permissions).')


def ip_da_rede_local():
    """Endereço IP da máquina na rede local (para acessar de celulares/totens).

    Truque do socket UDP: o connect() escolhe a rota sem enviar nenhum pacote.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except OSError:
        return None


def iniciar_servidor(venv_python, env, rotulo='8. Servidor de desenvolvimento'):
    titulo(rotulo)
    if not sim_nao('Iniciar o servidor agora (Ctrl+C para parar)?', padrao=True):
        print('   Para iniciar depois: flask --app run run --debug')
        return

    rede = sim_nao('Acessível por outros aparelhos na rede (totens, celulares, '
                   'outras máquinas — 0.0.0.0)?', padrao=False)
    argumentos = ['run', '--debug']
    if rede:
        argumentos.append('--host=0.0.0.0')

    if rede:
        print('   Servindo em todas as interfaces — Ctrl+C encerra. URLs:')
        print('     • Nesta máquina:   http://localhost:5000')
        ip = ip_da_rede_local()
        if ip:
            print(f'     • Na rede local:   http://{ip}:5000')
        else:
            print('     • Na rede local:   http://<IP-desta-máquina>:5000')
    else:
        print('   Servindo em http://localhost:5000 — Ctrl+C encerra.')

    try:
        # `flask ... run --debug` em vez de `python run.py`: a CLI do Flask lê o
        # .env automaticamente (run.py não chama load_dotenv).
        subprocess.run([venv_python, '-m', 'flask', '--app', 'run'] + argumentos, env=env)
    except KeyboardInterrupt:
        pass
    print('\n   Servidor encerrado.')


# ──────────────────────────────────── main ────────────────────────────────────

def main():
    # Terminais Windows em cp1252 quebram com emoji — melhor degradar o caractere
    # do que abortar o setup no meio.
    for stream in (sys.stdout, sys.stderr):
        try:
            # line_buffering: mantém a ordem das mensagens quando a saída é um
            # pipe (os subcomandos escrevem direto no terminal).
            stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
        except AttributeError:
            pass

    print()
    print('\033[1;36m══════════════════════════════════════════════════════')
    print('        🏫  SIGerE — Setup interativo inicial')
    print('   Sistema Integrado de Gerenciamento Educacional')
    print('══════════════════════════════════════════════════════\033[0m')
    print(f'   Projeto: {RAIZ}')

    try:
        modo = escolher(
            'O que você quer fazer?',
            [
                'Instalação completa — do zero, em uma máquina nova '
                '(venv, .env, banco e dados iniciais)',
                'Atualizar o sistema — nova versão do código, dependências, '
                'migrações e permissões',
                'Restaurar um backup do banco de dados',
            ],
            padrao=1,
        )

        if modo == 2:
            atualizar_sistema()
        elif modo == 3:
            restaurar_backup()
        else:
            venv_python = preparar_venv()
            instalar_dependencias(venv_python)
            env_arquivo = configurar_env()
            preparar_instance(env_arquivo)

            # Repassa o .env também no ambiente do processo: garante que os comandos
            # enxerguem a configuração mesmo sem depender da leitura do arquivo.
            env_processo = {**os.environ, **env_arquivo}

            aplicar_schema(venv_python, env_processo)
            modo_dados = popular_dados(venv_python, env_processo)
            unidades_senac(venv_python, env_processo)
            resumo_final(env_arquivo, modo_dados)

            if env_arquivo.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on'):
                iniciar_servidor(venv_python, env_processo)

        print('\nSetup concluído. Bom uso! 🎓')
    except KeyboardInterrupt:
        print('\n\nSetup interrompido pelo usuário. Nada foi desfeito — '
              'rode o script novamente para continuar de onde parou.')
        raise SystemExit(130)


if __name__ == '__main__':
    main()
