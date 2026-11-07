"""Setup interativo do SIGerE.

Guia a implantação e a manutenção do sistema em um único comando:

    python setup_interativo.py

O menu inicial oferece três modos:

  1. Instalação completa — do zero, em uma máquina nova:
     1. Confere o Python (3.11+) e cria/reaproveita o ambiente virtual .venv;
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
import tempfile
import zlib
from datetime import datetime
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

    if sys.version_info < (3, 11):
        erro(f"Python 3.11 ou superior é necessário (encontrado {sys.version.split()[0]}).\n"
             "   As dependências fixadas no requirements.txt (pillow 13) exigem 3.11+.")
        raise SystemExit(1)
    print(f"   Python {sys.version.split()[0]} — ok.")

    venv_python = python_da_venv()
    if venv_python.exists():
        versao = subprocess.run([str(venv_python), '--version'],
                                capture_output=True, text=True).stdout.strip()
        # O piso vale para o interpretador da .venv reaproveitada, não só
        # para o do sistema: uma .venv criada com Python 3.10 passa na
        # checagem acima, mas as dependências (pillow 13) não instalam.
        compativel = subprocess.run(
            [str(venv_python), '-c',
             'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'],
        ).returncode == 0
        if not compativel:
            erro(f"O ambiente .venv existente usa {versao}, anterior ao Python 3.11.\n"
                 "   Apague a pasta .venv e rode este setup novamente para recriá-la.")
            raise SystemExit(1)
        print(f"   Ambiente virtual existente reaproveitado: {venv_python} ({versao})")
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


def _gravar_segredos(caminho, conteudo):
    """Grava arquivo com segredos já protegido: o temporário vem do
    tempfile.mkstemp — nome aleatório exclusivo (um processo interrompido
    não deixa resto que trave a próxima chamada, mesmo com PID reusado) e
    criado já 0o600, sem janela legível entre a criação e um chmod.
    Substitui o destino de uma vez — sem janela em que o .env fica legível
    no meio da gravação."""
    fd, nome = tempfile.mkstemp(dir=caminho.parent,
                                prefix=caminho.name + '.', suffix='.tmp')
    temporario = Path(nome)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as arquivo:
            arquivo.write(conteudo)
        os.replace(temporario, caminho)
    finally:
        if temporario.exists():
            temporario.unlink()


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
        # Segredos no backup: leitura apenas do dono (gravação protegida).
        _gravar_segredos(backup, ARQUIVO_ENV.read_text(encoding='utf-8'))
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

    # O .env carrega a SECRET_KEY: gravação já protegida (leitura só do dono).
    _gravar_segredos(ARQUIVO_ENV, '\n'.join(linhas) + '\n')
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


def capturar_flask(venv_python, env, argumentos):
    """Roda um comando da CLI capturando o stdout em linhas — usado para
    registrar o estado dos vínculos papel↔permissão antes/depois do sync.
    Separa só por \\n (o delimitador do dump-permissions, que escapa \\n e \\r
    nos nomes): splitlines() também quebraria em \\x85, \\u2028 e afins,
    que podem existir em nomes de papéis legados."""
    resultado = subprocess.run([venv_python, '-m', 'flask', '--app', 'run'] + argumentos,
                               env=env, capture_output=True, text=True)
    if resultado.returncode != 0:
        erro(f"Falha no comando: flask --app run {' '.join(argumentos)}.")
        if resultado.stderr.strip():
            erro('Saída de erro capturada:\n' + resultado.stderr.strip())
        raise SystemExit(1)
    return [linha for linha in resultado.stdout.split('\n') if linha.strip()]


def registrar_snapshot_vinculos(antes, depois):
    """Grava os snapshots pré/pós-sync em logs/ — fica de registro para o
    operador reaplicar revogações confirmadas (e auditar o que mudou).
    Devolve True só quando os dois arquivos foram gravados: sem essa
    confirmação, o inventário pré-sync pendente não pode ser descartado."""
    pasta = RAIZ / 'logs'
    try:
        pasta.mkdir(exist_ok=True)
        marca = datetime.now().strftime('%Y%m%d-%H%M%S')
        (pasta / f'sync-permissions-{marca}-antes.txt').write_text(
            '\n'.join(antes) + '\n', encoding='utf-8')
        (pasta / f'sync-permissions-{marca}-depois.txt').write_text(
            '\n'.join(depois) + '\n', encoding='utf-8')
        ok(f'Snapshots dos vínculos salvos em {pasta} (sync-permissions-{marca}-*.txt)')
        return True
    except OSError as exc:
        aviso(f'Não foi possível gravar os snapshots em {pasta}: {exc} — '
              'os vínculos alterados seguem listados abaixo e o inventário '
              'pré-sync pendente fica preservado para a próxima execução.')
        return False


# Inventário pré-sync gravado ANTES de qualquer mudança: se a execução falhar
# depois do sync (a captura do pós, por exemplo), ele sobrevive e é
# reutilizado na próxima tentativa até a conferência concluir.
ARQUIVO_INVENTARIO_PENDENTE = RAIZ / 'logs' / 'sync-permissions-antes-pendente.txt'


def _sync_diretorio(pasta):
    """Sincroniza as entradas de uma pasta no disco, para o nome novo do
    pendente sobreviver a uma queda (POSIX: fsync no fd do diretório). No
    Windows não há como abrir um diretório — e o replace já é durável pela
    semântica do NTFS — então não há nada a fazer."""
    if os.name != 'posix':
        return
    fd = os.open(pasta, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def capturar_inventario_antes(venv_python, env):
    """Estado dos vínculos antes do sync, preservado entre tentativas.

    Sem o arquivo pendente, uma falha depois do commit do sync perderia o
    "antes": na nova execução o dump já sairia sincronizado, o sync diria
    que nada foi adicionado e as revogações a reaplicar ficariam ocultas.
    Havendo inventário pendente, ele é oferecido como estado anterior — com a
    durabilidade reconfirmada (sync de logs/ e da raiz) antes de liberar o
    sync-permissions: a execução anterior pode ter caído entre o replace e a
    sincronização, deixando o arquivo publicado porém não garantido em disco."""
    if ARQUIVO_INVENTARIO_PENDENTE.exists():
        aviso('Inventário pré-sync pendente encontrado '
              f'({ARQUIVO_INVENTARIO_PENDENTE.relative_to(RAIZ)}): uma execução '
              'anterior falhou depois de sincronizar. O dump atual já pode estar '
              'sincronizado e não serve de estado "antes".')
        if sim_nao('Reutilizar o inventário pendente como estado anterior ao sync?',
                   padrao=True):
            # A publicação anterior pode não ter chegado ao disco: queda entre o
            # replace e o sync do diretório, ou arquivo gravado por uma versão
            # anterior do script, sem fsync do conteúdo. Reconfirma o arquivo
            # (fsync nos dados — aberto para leitura/escrita porque o fsync do
            # Windows exige handle de escrita) e as duas sincronizações de
            # diretório — logs/ e a raiz, pois o logs/ pode ter nascido naquela
            # execução — antes de liberar o sync. Sem essas garantias o
            # inventário não pode ser tratado como durável e o sync não roda.
            try:
                with open(ARQUIVO_INVENTARIO_PENDENTE, 'r+b') as arquivo:
                    os.fsync(arquivo.fileno())
                # Leitura à parte, em modo texto: a publicação em Windows grava
                # \r\n — read_text converte (universal newlines) e a separação
                # continua sendo só por \n.
                conteudo = ARQUIVO_INVENTARIO_PENDENTE.read_text(encoding='utf-8')
                _sync_diretorio(ARQUIVO_INVENTARIO_PENDENTE.parent)
                _sync_diretorio(ARQUIVO_INVENTARIO_PENDENTE.parent.parent)
            except OSError as exc:
                erro(f'Falha ao confirmar a durabilidade do inventário pendente ({exc}) — '
                     'a falha ocorreu depois da publicação do arquivo: ele segue em logs/, '
                     'mas não está garantido em disco e não pode ser tratado como durável. '
                     'Corrija a falha (permissão ou espaço) e rode de novo; se o conteúdo '
                     'importar, copie-o antes para um local seguro.')
                raise SystemExit(1)
            # Mesma separação do capturar_flask: só \n delimita linhas.
            return [linha for linha in conteudo.split('\n') if linha.strip()]
        # Se a remoção falhar, a gravação atômica abaixo substitui o arquivo
        # pelo inventário novo — ou também falha e interrompe antes do sync.
        descartar_inventario_pendente()
    print('   Registrando o estado atual dos vínculos (flask --app run dump-permissions)')
    antes = capturar_flask(venv_python, env, ['dump-permissions'])
    # Publicação durável: grava num temporário da mesma pasta, força os dados
    # para o disco (flush + fsync — o host pode cair logo após o commit do
    # sync) e troca pelo destino; o diretório é sincronizado depois para o
    # nome novo sobreviver a uma queda. Sem essa garantia o sync não roda:
    # uma falha depois do commit perderia o "antes" e a próxima execução
    # esconderia as revogações a reaplicar.
    temporario = ARQUIVO_INVENTARIO_PENDENTE.with_suffix('.tmp')
    pasta_criada = not ARQUIVO_INVENTARIO_PENDENTE.parent.exists()
    try:
        ARQUIVO_INVENTARIO_PENDENTE.parent.mkdir(exist_ok=True)
        with open(temporario, 'w', encoding='utf-8') as arquivo:
            arquivo.write('\n'.join(antes) + '\n')
            arquivo.flush()
            os.fsync(arquivo.fileno())
        temporario.replace(ARQUIVO_INVENTARIO_PENDENTE)
        _sync_diretorio(ARQUIVO_INVENTARIO_PENDENTE.parent)
        if pasta_criada:
            _sync_diretorio(ARQUIVO_INVENTARIO_PENDENTE.parent.parent)
    except OSError as exc:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
        erro(f'Não foi possível preservar o inventário pré-sync em disco: {exc} — '
             'corrija a falha (permissão ou espaço em logs/) antes de executar o sync.')
        raise SystemExit(1)
    return antes


def descartar_inventario_pendente():
    """Remove o inventário pendente. Devolve True quando ele não existe mais
    (removido ou já ausente) e False quando a remoção falhou — quem chama
    decide se a falha interrompe o fluxo (a restauração interrompe)."""
    try:
        ARQUIVO_INVENTARIO_PENDENTE.unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        erro(f'Não foi possível remover {ARQUIVO_INVENTARIO_PENDENTE}: {exc} — '
             'apague-o à mão para a próxima execução não oferecê-lo de novo.')
        return False
    return True


# Na restauração, o pendente é renomeado (não apagado) logo antes da primeira
# alteração no banco: se a etapa falhar sem alterá-lo, volta a ser o pendente;
# senão fica só como registro em logs/.
ARQUIVO_INVENTARIO_INVALIDADO = ARQUIVO_INVENTARIO_PENDENTE.with_name(
    'sync-permissions-antes-invalidado.txt')


def invalidar_inventario_pendente():
    """Invalida o inventário pendente imediatamente antes da primeira
    alteração no banco restaurado: ele descreve o banco que será substituído
    e não pode ser reaproveitado depois de uma restauração, nem parcial. Sem
    conseguir invalidá-lo, a restauração para antes de alterar o banco.
    Devolve True quando havia um pendente (agora invalidado)."""
    if not ARQUIVO_INVENTARIO_PENDENTE.exists():
        return False
    try:
        ARQUIVO_INVENTARIO_PENDENTE.replace(ARQUIVO_INVENTARIO_INVALIDADO)
    except OSError as exc:
        erro('Restauração interrompida antes de alterar o banco: o inventário '
             f'pré-sync pendente não pôde ser invalidado ({exc}).')
        raise SystemExit(1)
    aviso('Inventário pré-sync pendente de uma execução anterior invalidado '
          f'({ARQUIVO_INVENTARIO_INVALIDADO.name}): ele descreve o banco que está '
          'sendo substituído pelo backup.')
    return True


def reabilitar_inventario_pendente(invalidado):
    """Etapa interrompida sem alterar o banco: o inventário invalidado volta a
    ser o pendente, pois continua descrevendo o banco atual."""
    if not invalidado:
        return
    try:
        ARQUIVO_INVENTARIO_INVALIDADO.replace(ARQUIVO_INVENTARIO_PENDENTE)
    except OSError as exc:
        erro(f'Não foi possível reabilitar o inventário pendente ({exc}) — em logs/, '
             f'renomeie {ARQUIVO_INVENTARIO_INVALIDADO.name} para '
             f'{ARQUIVO_INVENTARIO_PENDENTE.name} antes da próxima atualização.')


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
            'Demonstração simples — admin com senha aleatória + salas, usuários e reservas (seed)',
            'Demonstração completa — todos os módulos, cozinha, financeiro e API (seed-demo)',
            'Migração do sistema legado — importa o dump MySQL do sistema antigo (import-legacy)',
            'Não popular agora (posso rodar este setup de novo depois)',
        ],
        padrao=1,
    )

    if opcao == 1:
        print('   A senha será pedida pelo próprio comando (no mínimo 8 caracteres,')
        print('   com 1 letra maiúscula e 1 número; digitação oculta).')
        executar_flask(venv_python, env, ['seed-admin'])
        ok('Comando seed-admin executado — a conta admin@school.edu está pronta '
           '(se já existia, foi preservada).')
        return 'seed-admin'
    if opcao == 2:
        executar_flask(venv_python, env, ['seed'])
        ok('Seed básico executado (admin@school.edu com a senha aleatória exibida pelo comando e dados de demonstração opcionais).')
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


# Estados do `systemctl is-active` que contam como serviço no ar (inclusive em
# transição). inactive/failed contam como parado; qualquer outra saída
# (unknown, vazia, erro de barramento) é falha de consulta.
ESTADOS_SYSTEMD_ATIVOS = {'active', 'activating', 'deactivating', 'reloading', 'refreshing'}


def servico_ativo(servico):
    """True com o serviço no ar, False parado e None quando o systemctl não
    informa o estado — uma falha na consulta não pode passar por serviço
    parado e liberar o sync-permissions."""
    resultado = subprocess.run(['systemctl', 'is-active', servico],
                               capture_output=True, text=True)
    estado = resultado.stdout.strip()
    if resultado.returncode == 0 or estado in ESTADOS_SYSTEMD_ATIVOS:
        return True
    if estado in ('inactive', 'failed'):
        return False
    return None


def conferir_servicos_parados(permitir_nginx_alheio=False):
    """Interrompe a manutenção com os serviços no ar: o sync-permissions
    devolve revogações intencionais ao papel e, com a aplicação acessível,
    elas ficam expostas antes da conferência.

    O sigere no ar sempre interrompe. O Nginx pode estar ativo por outros
    sites da máquina (comum em desenvolvimento): com permitir_nginx_alheio, o
    operador confirma que ele não encaminha tráfego a esta instalação e a
    atualização segue — a proteção continua quando ele publica o SIGerE. Na
    restauração (padrão), qualquer um dos dois ativo interrompe. Estado que
    o systemctl não consegue informar também interrompe. Sem systemd em
    execução (sem systemctl, ou sem /run/systemd/system — contêineres, WSL
    sem systemd) não há serviço gerenciado a conferir."""
    if not shutil.which('systemctl') or not Path('/run/systemd/system').is_dir():
        return
    estados = {s: servico_ativo(s) for s in ('sigere', 'nginx')}
    sem_estado = [s for s, ativo in estados.items() if ativo is None]
    if sem_estado:
        erro(f"Não foi possível consultar o estado de {', '.join(sem_estado)} pelo "
             'systemctl — sem essa confirmação o sync-permissions não roda. Confira à '
             'mão (sudo systemctl is-active nginx sigere: ambos devem estar inactive) '
             'e rode o setup de novo.')
        raise SystemExit(1)
    ativos = [s for s, ativo in estados.items() if ativo]
    if 'nginx' in ativos and 'sigere' not in ativos and permitir_nginx_alheio:
        if not sim_nao('O Nginx ativo encaminha tráfego para esta instalação do SIGerE?',
                       padrao=True):
            aviso('Nginx mantido no ar: confirmado que ele não atende esta instalação.')
            return
    if ativos:
        erro(f"Serviço(s) no ar ({', '.join(ativos)}): o sync-permissions devolve as "
             'revogações intencionais ao papel e, com a aplicação acessível, elas ficam '
             'expostas antes da conferência. Pare-os primeiro (sudo systemctl stop '
             f"{' '.join(ativos)}) e rode o setup de novo.")
        raise SystemExit(1)


def atualizar_sistema():
    """Rotina da seção "Atualizando a aplicação" de docs/implantacao-producao.md,
    guiada: backup de segurança → git pull → dependências → db upgrade →
    sync-permissions."""
    titulo('Modo: atualização do sistema')
    venv_python, env_processo, env_arquivo = preparar_manutencao()

    # O sync devolve revogações intencionais ao papel — com os serviços no ar,
    # elas ficam expostas antes da conferência. Guarda igual à rotina
    # documentada e ao modo de restauração; aqui o operador pode confirmar
    # que um Nginx ativo atende apenas outros sites da máquina.
    conferir_servicos_parados(permitir_nginx_alheio=True)

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
    # Snapshot antes/depois: sem ele, o operador não distingue um vínculo novo
    # de catálogo de uma revogação intencional que o sync acabou de devolver ao
    # papel (mesma proteção do modo de restauração).
    antes = capturar_inventario_antes(venv_python, env_processo)
    print('   Executando: flask --app run sync-permissions (idempotente; o boot não sincroniza)')
    executar_flask(venv_python, env_processo, ['sync-permissions'])
    depois = capturar_flask(venv_python, env_processo, ['dump-permissions'])
    ok('Permissões e papéis sincronizados (sync-permissions).')
    # O pendente só sai daí quando os snapshots confirmam a gravação — sem
    # eles, o "antes" permanece preservado para a próxima execução.
    if registrar_snapshot_vinculos(antes, depois):
        descartar_inventario_pendente()
    adicionados = sorted(set(depois) - set(antes))
    removidos = sorted(set(antes) - set(depois))
    titulo('Vínculos papel↔permissão alterados pelo sync')
    if adicionados:
        print('   Revise cada vínculo abaixo: entre eles podem estar permissões que')
        print('   estavam revogadas de propósito no painel antes da atualização — as')
        print('   confirmadas devem voltar a ficar ausentes (veja "Próximos passos"):')
        for linha in adicionados:
            print(f'     + {linha}')
    else:
        print('   Nenhum vínculo foi adicionado pelo sync.')
    for linha in removidos:
        print(f'     - {linha} (aposentada do catálogo pelo sync)')

    titulo('Resumo da atualização')
    for passo in passos:
        print(f'   • {passo}')
    print('\n   Próximos passos:')
    if env_arquivo.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on'):
        iniciar_servidor(venv_python, env_processo, rotulo='Servidor de desenvolvimento')
    else:
        print('     • Com o tráfego ainda bloqueado, reaplique as revogações confirmadas:')
        print('       os vínculos "+" acima que eram revogações intencionais devem voltar a')
        print('       ficar ausentes — Flask shell via SSH com Nginx/sigere parados, ou')
        print('       Painel Admin → Papéis numa instância local (docs/implantacao-producao.md).')
        print('     • Só então reinicie o serviço: sudo systemctl restart sigere')
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


def _copiar_metadados_arquivo(origem, destino):
    """Replica dono, grupo e modo do arquivo existente no novo (Linux: só o
    root muda o dono — chown sem permissão levanta e a restauração para
    antes de trocar o banco; no Windows só o modo importa e é ignorado).

    Banco ausente (perdido, ou o operador pulou o backup do estado atual):
    em vez de abortar com uma orientação sobre um arquivo que não existe,
    aplica a política da instalação ao restaurado — modo 0o644 e o dono/grupo
    de instance/, a pasta que a implantação entrega ao usuário do serviço —
    e avisa para conferir o dono antes de reiniciar os serviços."""
    try:
        stat = origem.stat()
    except FileNotFoundError:
        aviso(f'O banco {origem.name} não existe (perdido, ou o backup do estado '
              'atual foi pulado): o restaurado nasce com modo 0o644 e o dono/grupo '
              'de instance/ — confirme que o dono é o usuário do serviço '
              '(www-data em produção) antes de reiniciar os serviços.')
        modo = 0o644
        try:
            # A pasta do projeto (RAIZ/instance), não relativa ao banco: um
            # DATABASE_URL dentro de instance/ procuraria instance/instance.
            stat = (RAIZ / 'instance').stat()
        except OSError:
            stat = None
    else:
        modo = stat.st_mode & 0o7777
    os.chmod(destino, modo)
    if stat is not None and hasattr(os, 'chown'):
        os.chown(destino, stat.st_uid, stat.st_gid)


def _afastar_wal_anterior(caminho_db):
    """Renomeia -wal/-shm do banco atual para '<nome>.restaurando-antigo' antes
    da troca: o banco restaurado nunca nasce com o WAL da sessão anterior ao
    lado — o SQLite o recuperaria como transações dele, corrompendo os dados.
    Devolve a lista de pares (nome original, nome afastado): o chamador recoloca
    os arquivos se a troca falhar (banco atual segue par coerente com o WAL) e
    apaga os afastados depois que ela tiver sucesso. Falha em renomear recoloca
    o que já saiu e propaga: o banco atual não pode ficar sem o próprio WAL."""
    afastados = []
    try:
        for sufixo in ('-wal', '-shm'):
            lateral = Path(f'{caminho_db}{sufixo}')
            if lateral.exists():
                afastado = Path(f'{lateral}.restaurando-antigo')
                lateral.replace(afastado)
                afastados.append((lateral, afastado))
    except OSError:
        for lateral, afastado in afastados:
            try:
                afastado.replace(lateral)
            except OSError:
                pass
        raise
    return afastados


def restaurar_sqlite(caminho_db, arquivo_backup):
    """Substitui o arquivo do banco pelo snapshot gzip
    (docs/implantacao-producao.md, seção "Restaurar").

    O snapshot é descompactado num temporário ao lado do banco e só então
    troca de lugar com ele (os.replace, atômico): falhas até a troca deixam
    o banco atual intocado — e o inventário pré-sync pendente, invalidado
    só imediatamente antes dela, preservado.

    O -wal/-shm do banco atual é afastado ANTES da troca (função
    _afastar_wal_anterior): o banco restaurado nunca fica exposto ao WAL
    anterior, nem se a limpeza depois da troca falhar, nem se algo interromper
    entre a troca e a limpeza."""
    with gzip.open(arquivo_backup, 'rb') as gz:
        cabecalho = gz.read(16)
    if not cabecalho.startswith(b'SQLite format 3'):
        erro('O arquivo não parece um snapshot SQLite válido (cabeçalho inesperado) — '
             'restauração abortada, o banco atual não foi tocado.')
        raise SystemExit(1)

    caminho_db.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho_db.with_name(caminho_db.name + '.restaurando')
    try:
        try:
            with gzip.open(arquivo_backup, 'rb') as origem, open(temporario, 'wb') as destino:
                shutil.copyfileobj(origem, destino)
        except (OSError, EOFError, zlib.error) as exc:
            erro(f'Falha ao descompactar o backup ({exc}) — restauração abortada, o banco '
                 'atual não foi tocado.')
            raise SystemExit(1)
        # O serviço (www-data no Linux) precisa continuar dono e com permissão
        # de escrita do banco: o temporário pode ter nascido de outro usuário
        # e, na troca, deixaria o SQLite readonly. Falha em preservar
        # interrompe antes de substituir o banco.
        try:
            _copiar_metadados_arquivo(caminho_db, temporario)
        except OSError as exc:
            erro(f'Não foi possível replicar dono/permissões de {caminho_db.name} no '
                 f'arquivo temporário ({exc}) — ajuste-os à mão e rode a restauração '
                 'de novo. O banco atual não foi tocado.')
            raise SystemExit(1)
        invalidado = invalidar_inventario_pendente()
        try:
            afastados = _afastar_wal_anterior(caminho_db)
        except OSError as exc:
            reabilitar_inventario_pendente(invalidado)
            erro(f'Não foi possível afastar o WAL do banco atual ({exc}) — restauração '
                 'abortada: o banco atual segue intacto, com o WAL dele.')
            raise SystemExit(1)
        try:
            os.replace(temporario, caminho_db)
        except OSError as exc:
            # A troca falhou: o banco atual volta a formar par com o próprio WAL.
            for lateral, afastado in afastados:
                try:
                    afastado.replace(lateral)
                except OSError:
                    pass
            reabilitar_inventario_pendente(invalidado)
            erro(f'Não foi possível substituir {caminho_db} ({exc}) — se estiver em uso, '
                 'pare a aplicação/servidor e rode a restauração de novo. O banco atual '
                 'não foi alterado.')
            raise SystemExit(1)
        # Troca feita: o restaurado nasceu sem WAL anterior ao lado; os arquivos
        # afastados são lixo (o nome não colide mais com o par banco+WAL) — a
        # remoção que falhar é só aviso.
        for lateral, afastado in afastados:
            try:
                afastado.unlink(missing_ok=True)
            except OSError as exc:
                aviso(f'Não foi possível remover o WAL anterior ({afastado.name}): {exc} — '
                      'o banco restaurado não o usa; apague-o à mão quando puder.')
    finally:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass


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
    """Executa o dump no PostgreSQL via psql. Devolve True quando restaurou.

    O inventário pré-sync pendente é invalidado imediatamente antes da
    primeira alteração (dropdb ou psql) e só volta a valer se o dropdb
    falhar — o DROP DATABASE é atômico, então a falha não alterou nada —
    ou se o dump nem abrir (sem recriar o banco, o psql nem começa e o
    banco segue intocado). Falhas no createdb ou no psql deixam o banco
    alterado: o inventário continua invalidado. A conclusão exige o
    marcador final anexado ao stream na saída do psql: sair 0 sem
    processar o dump inteiro (\\q em arquivo manual) também interrompe."""
    parametros = parametros_postgres(uri)
    env_psql = _ambiente_psql(parametros)

    psql = localizar_binario(
        'psql',
        'instale o cliente PostgreSQL — Debian/Ubuntu: sudo apt install postgresql-client')
    if not psql:
        print('   Restauração cancelada.')
        return False

    recriar = sim_nao('Recriar o banco antes de restaurar (apaga o atual e restaura '
                      'limpo — recomendado)?', padrao=True)
    if recriar:
        pasta_bin = Path(psql).parent
        sufixo = '.exe' if os.name == 'nt' else ''
        dropdb, createdb = pasta_bin / f'dropdb{sufixo}', pasta_bin / f'createdb{sufixo}'
        if not (dropdb.is_file() and createdb.is_file()):
            erro(f'Binários dropdb/createdb não encontrados ao lado de "{psql}".')
            raise SystemExit(1)

    invalidado = invalidar_inventario_pendente()
    if recriar:
        print(f'   Recriando o banco {parametros["banco"]} em '
              f'{parametros["host"]}:{parametros["porta"]}...')
        if subprocess.run([str(dropdb), '--if-exists', parametros['banco']],
                          env=env_psql).returncode != 0:
            reabilitar_inventario_pendente(invalidado)
            erro('Falha ao apagar o banco (dropdb) — confira as credenciais no .env.')
            raise SystemExit(1)
        dono = ['--owner', parametros['usuario']] if parametros['usuario'] else []
        if subprocess.run([str(createdb), *dono, parametros['banco']],
                          env=env_psql).returncode != 0:
            reabilitar_inventario_pendente(invalidado)
            erro('Falha ao criar o banco (createdb).')
            raise SystemExit(1)
        print('   Banco vazio recriado.')

    print('   Restaurando o dump (pode levar alguns minutos)...')
    try:
        dump = gzip.open(arquivo_backup, 'rb')
    except OSError as exc:
        # Sem o dump, o psql nem começa: quando o banco não foi recriado, a
        # 1ª alteração ainda não aconteceu e o inventário volta a valer.
        if not recriar:
            reabilitar_inventario_pendente(invalidado)
        erro(f'Falha ao abrir o backup ({exc}) — o psql não foi iniciado'
             + ('; o banco segue recriado e vazio até a restauração conseguir.'
                if recriar else '; o banco atual segue intocado.'))
        raise SystemExit(1)
    # O psql não lê gzip: stdin=dump passaria o descritor do arquivo COMPRIMIDO
    # (o fileno() do GzipFile é do arquivo por baixo) e o psql engoliria bytes
    # gzip como se fossem SQL. O conteúdo descomprimido é bombeado por PIPE —
    # com a saída em arquivo, para o resultado das consultas do dump não encher
    # um stdout=PIPE e travar o bombeio.
    MARCA_FIM = b'SIGERE-RESTAURACAO-ATE-O-FIM'
    descriptor_saida, caminho_saida = tempfile.mkstemp(
        prefix='sigere-restauracao-psql-', suffix='.out')
    try:
        with os.fdopen(descriptor_saida, 'w+b') as saida:
            psql_processo = subprocess.Popen([psql, '-q', '-v', 'ON_ERROR_STOP=1'],
                                             stdin=subprocess.PIPE, stdout=saida,
                                             env=env_psql)
            copia_ok, falha_copia = True, None
            try:
                shutil.copyfileobj(dump, psql_processo.stdin)
                # Marcador anexado ao fim do stream: chega à saída só se o psql
                # processou tudo que veio antes — um \q em limite de comando
                # (arquivo manual) encerra o psql 0 sem executá-lo, e um \q
                # dentro de um statement vira erro de SQL (ON_ERROR_STOP).
                psql_processo.stdin.write(b'\n\\echo ' + MARCA_FIM + b'\n')
            except (OSError, EOFError, zlib.error) as exc:
                copia_ok, falha_copia = False, exc
            finally:
                dump.close()
                try:
                    psql_processo.stdin.close()  # EOF: o psql processa o que recebeu
                except OSError as exc:
                    # O flush pendente falhou (o psql saiu sem ler o resto do buffer —
                    # dump manual com \q, por exemplo): viraria falso sucesso com dump
                    # parcial. Sem uma falha de cópia anterior, é ela que conta.
                    if copia_ok:
                        copia_ok, falha_copia = False, exc
            if psql_processo.wait() != 0:
                erro('Falha na restauração — o psql parou no primeiro erro (ON_ERROR_STOP). '
                     'Se o banco não estava vazio, tente de novo recriando-o antes.')
                raise SystemExit(1)
            if not copia_ok:
                # Guarda contra falso sucesso: o psql saiu 0 sem receber o dump inteiro
                # (gzip corrompido truncando num limite de comando, por exemplo).
                erro(f'Falha ao transferir o backup ao psql ({falha_copia}) — o dump pode '
                     'estar corrompido: o psql saiu sem receber o conteúdo inteiro.')
                raise SystemExit(1)
            # Prova de execução até o fim: saiu 0 e a cópia foi completa, mas um
            # \q no meio do dump encerra o psql 0 também — sem o marcador na
            # saída, o que veio antes dele não foi processado por completo.
            saida.seek(0, os.SEEK_END)
            saida.seek(max(0, saida.tell() - 2048))
            rabo_bruto = saida.read()
            if MARCA_FIM not in rabo_bruto:
                erro('O psql saiu sem processar o dump até o fim (\\q no arquivo manual '
                     'ou conteúdo interrompido): a restauração não foi confirmada.')
                rabo = rabo_bruto.decode('utf-8', errors='replace').strip()
                if rabo:
                    aviso('Fim da saída do psql:\n   ' + rabo.replace('\n', '\n   '))
                raise SystemExit(1)
        return True
    finally:
        try:
            os.unlink(caminho_saida)
        except OSError:
            pass


def restaurar_backup():
    """Modo guiado de restauração de backup (SQLite ou PostgreSQL).

    Substitui todos os dados atuais do banco pelo dump escolhido, aplica as
    migrações posteriores ao backup (db upgrade) e oferece o sync-permissions
    sob confirmação do operador: executá-lo devolve ao papel permissões
    revogadas no backup, e pular o deixa ausentes as permissões novas do
    catálogo — o resumo final orienta como tratar cada caso antes de
    reiniciar os serviços e liberar o acesso.
    """
    titulo('Modo: restauração de backup')
    venv_python, env_processo, env_arquivo = preparar_manutencao()

    # Antes de tocar no banco: com sigere/Nginx no ar, os usuários seguiriam
    # acessando o sistema enquanto o banco é substituído e o sync devolve
    # revogações — mesma guarda da atualização, sem a exceção do Nginx.
    conferir_servicos_parados()

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

    # O inventário pré-sync pendente (de uma atualização que falhou depois do
    # sync) descreve o banco atual: fica preservado até a primeira alteração
    # no banco — restaurar_sqlite/restaurar_postgres o invalidam logo antes
    # dela e o reabilitam se a etapa falhar sem alterar nada.

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

    titulo('Permissões após o backup')
    aviso('O sync-permissions devolve aos papéis padrão da aplicação (ROLES_CONFIG) '
          'cada permissão do catálogo que estiver ausente — inclusive uma que tenha '
          'sido revogada de propósito no painel (Painel Admin → Papéis) antes do '
          'backup. A adição de vínculos se limita aos papéis de ROLES_CONFIG, mas '
          'permissões removidas de PERMISSION_DATA são apagadas com seus vínculos '
          'de qualquer papel (inclusive legados ou criados manualmente) — confira '
          'esses vínculos manualmente.')
    aviso('Pular o sync também deixa ausentes as permissões NOVAS do catálogo: o painel '
          'só lista as já gravadas no banco e não consegue recriá-las — fluxos param de '
          'funcionar (ex.: reserva de Professor deixa de nascer Pendente). Recomendado: '
          'rodar o sync e reaplicar as revogações no painel depois.')
    sync_executado = sim_nao('Executar sync-permissions agora? Responda NÃO apenas se o '
                             'backup veio da MESMA versão da aplicação (catálogo '
                             'completo) e há revogações a preservar.', padrao=True)
    if sync_executado:
        # Snapshot antes/depois: sem ele, o operador não distingue um vínculo
        # novo de catálogo de uma revogação intencional que o sync acabou de
        # devolver ao papel.
        antes = capturar_inventario_antes(venv_python, env_processo)
        print('   Executando: flask --app run sync-permissions (idempotente; o boot não sincroniza)')
        executar_flask(venv_python, env_processo, ['sync-permissions'])
        depois = capturar_flask(venv_python, env_processo, ['dump-permissions'])
        ok('Permissões e papéis sincronizados (sync-permissions).')
        # Igual à atualização: descarte só com snapshots gravados.
        if registrar_snapshot_vinculos(antes, depois):
            descartar_inventario_pendente()
        adicionados = sorted(set(depois) - set(antes))
        removidos = sorted(set(antes) - set(depois))
        titulo('Vínculos papel↔permissão alterados pelo sync')
        if adicionados:
            print('   Revise cada vínculo abaixo: entre eles podem estar permissões que')
            print('   estavam revogadas de propósito no backup — as confirmadas devem')
            print('   voltar a ficar ausentes em Painel Admin → Papéis, com o tráfego')
            print('   ainda bloqueado:')
            for linha in adicionados:
                print(f'     + {linha}')
        else:
            print('   Nenhum vínculo foi adicionado pelo sync.')
        for linha in removidos:
            print(f'     - {linha} (aposentada do catálogo pelo sync)')
    else:
        aviso('sync-permissions pulado: revogações do backup preservadas. Confirme que o '
              'catálogo está completo — se faltar permissão, rode o sync com o tráfego '
              'bloqueado e reaplique as revogações em Painel Admin → Papéis ANTES de '
              'liberar o acesso dos usuários.')

    titulo('Resumo da restauração')
    for passo in passos:
        print(f'   • {passo}')
    print('\n   Próximos passos:')
    print('     • Em servidor remoto, abra um túnel SSH antes de acessar o painel: '
          'ssh -N -L 5000:127.0.0.1:5000 usuario@servidor')
    print('     • Com Nginx e o serviço normal parados, suba uma instância local — '
          f'PowerShell: & "{venv_python}" -m flask --app run run; demais shells: '
          f'"{venv_python}" -m flask --app run run — com FLASK_DEBUG=true (somente '
          'para esse acesso de restauração: fora do debug o cookie de sessão é '
          'Secure e o login falha em HTTP; acesse http://localhost:5000) ou, sem '
          'debug, por HTTPS: --cert /caminho/cert.pem --key /caminho/chave.pem '
          '(acesse https://localhost:5000)')
    if sync_executado:
        print('     • Revise os vínculos adicionados pelo sync (listados acima) e '
              'reaplique em Painel Admin → Papéis as revogações confirmadas; encerre '
              'a instância local antes de reiniciar os serviços e liberar o acesso '
              'normal')
    if not sync_executado:
        print('     • Confirme que o catálogo de permissões está completo (permissão '
              'nova só entra rodando flask --app run sync-permissions; o painel não '
              'a recria) e reaplique em Painel Admin → Papéis as revogações '
              'preservadas do backup; encerre a instância local antes de liberar o '
              'acesso normal')
    if env_arquivo.get('FLASK_DEBUG', '').lower() in ('1', 'true', 'yes', 'on'):
        print('     • Suba o servidor: flask --app run run --debug')
        print('     • Teste o login e a navegação: http://localhost:5000')
    else:
        print('     • Reinicie Nginx e o serviço: sudo systemctl start nginx && '
              'sudo systemctl restart sigere')
        print('     • Teste o login e a navegação pelo endereço normal do sistema')
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
    if modo_dados == 'seed':
        print('     • admin@school.edu — se o seed criou a conta agora, a senha aleatória apareceu na execução dele; se a conta já existia, ela foi preservada com a senha anterior (demonstração — troque a senha!)')
    if modo_dados == 'seed-demo':
        print('     • admin@school.edu — senha de demonstração fixa exibida na execução do seed-demo; se a conta já existia, ela foi preservada com a senha anterior (demonstração — troque a senha!)')
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
