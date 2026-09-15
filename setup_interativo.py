"""Setup interativo inicial do SIGerE.

Guia a implantação do sistema em um único comando, perguntando o necessário
e executando cada etapa documentada no README (seção "Instalação"):

    python setup_interativo.py

Etapas:
  1. Confere o Python (3.8+) e cria/reaproveita o ambiente virtual .venv;
  2. Instala as dependências (requirements.txt);
  3. Gera o arquivo .env (SECRET_KEY, banco de dados, clima do totem);
  4. Cria/atualiza o schema do banco (flask --app run db upgrade);
  5. Popula os dados iniciais — implantação real (seed-admin), demonstração
     (seed / seed-demo) ou migração do sistema legado (import-legacy);
  6. Opcional: cadastra as unidades do Senac SC (seed-unidades);
  7. Opcional: inicia o servidor de desenvolvimento.

Seguro de rodar mais de uma vez: etapas já concluídas são reaproveitadas e
cada comando de seed tem guarda própria contra duplicação de dados.

Somente biblioteca padrão — o script roda antes das dependências existirem.
"""
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path

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


def preparar_venv():
    titulo('1. Ambiente virtual (Python)')

    if sys.version_info < (3, 8):
        erro(f"Python 3.8 ou superior é necessário (encontrado {sys.version.split()[0]}).")
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

def instalar_dependencias(venv_python):
    titulo('2. Dependências (requirements.txt)')

    instalado = subprocess.run(
        [venv_python, '-c', 'import flask, flask_migrate, dotenv'],
        capture_output=True,
    ).returncode == 0
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

    lat = entrada('Latitude do totem (clima, fallback global; vazio usa -23.5505)', '-23.5505')
    linhas.append(f'TOTEM_LATITUDE="{lat}"')
    lon = entrada('Longitude do totem (vazio usa -46.6333)', '-46.6333')
    linhas.append(f'TOTEM_LONGITUDE="{lon}"')

    ARQUIVO_ENV.write_text('\n'.join(linhas) + '\n', encoding='utf-8')
    ok(f".env criado (perfil {'desenvolvimento' if desenvolvimento else 'produção'}).")
    if not desenvolvimento:
        aviso('Proteja o arquivo .env — contém a SECRET_KEY e nunca deve ser versionado.')

    return ler_env(ARQUIVO_ENV)


# ───────────────────────────── schema do banco ────────────────────────────────

def executar_flask(venv_python, env, argumentos):
    """Roda um comando da CLI do Flask com o .env aplicado e o console herdado
    (necessário para prompts interativos, como a senha do seed-admin)."""
    if subprocess.run([venv_python, '-m', 'flask', '--app', 'run'] + argumentos,
                      env=env).returncode != 0:
        erro(f"Falha no comando: flask --app run {' '.join(argumentos)} — veja a mensagem acima.")
        raise SystemExit(1)


def aplicar_schema(venv_python, env):
    titulo('4. Schema do banco (Flask-Migrate/Alembic)')
    print('   Executando: flask --app run db upgrade')
    executar_flask(venv_python, env, ['db', 'upgrade'])
    ok('Schema do banco criado/atualizado (alembic head).')


# ──────────────────────────── dados iniciais ──────────────────────────────────

def popular_dados(venv_python, env):
    titulo('5. Dados iniciais')

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
    titulo('6. Unidades do Senac SC (opcional)')
    if not JSON_UNIDADES.exists():
        aviso(f'Arquivo {JSON_UNIDADES.name} não encontrado — etapa indisponível.')
        return
    if not sim_nao('Cadastrar as unidades educacionais do Senac SC (seed-unidades)?', padrao=False):
        print('   Etapa pulada — pode ser feita depois: flask --app run seed-unidades')
        return
    executar_flask(venv_python, env, ['seed-unidades'])
    ok('Unidades cadastradas (idempotente — pode rodar de novo sem duplicar).')


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
    print('     • Atualizações futuras: git pull && flask --app run db upgrade '
          '&& flask --app run sync-permissions')


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


def iniciar_servidor(venv_python, env):
    titulo('7. Servidor de desenvolvimento')
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
        venv_python = preparar_venv()
        instalar_dependencias(venv_python)
        env_arquivo = configurar_env()

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
