"""Backup automático do banco de dados, com retenção e upload para a nuvem.

O comando `flask --app run backup` gera um snapshot consistente do banco
configurado em DATABASE_URL — os dois motores suportados pela aplicação:

- **PostgreSQL** (produção): dump SQL via `pg_dump --no-owner --no-privileges`,
  comprimido em `.sql.gz`. O binário `pg_dump` precisa estar no servidor
  (pacote `postgresql-client`); a senha NUNCA vai na linha de comando — as
  credenciais são passadas ao pg_dump por variáveis de ambiente (PGHOST,
  PGPASSWORD...), invisíveis no `ps` de outros usuários.
- **SQLite** (desenvolvimento): snapshot pela API de backup do SQLite
  (`Connection.backup`), consistente mesmo com a aplicação no ar, seguido de
  `PRAGMA integrity_check` no arquivo gerado.

Depois do dump: retenção local — política avô/pai/filho com **7 diárias + 4
semanais** — e, quando BACKUP_S3_BUCKET está definido, upload para qualquer
armazenamento compatível com a API S3 (AWS S3, Backblaze B2, Cloudflare R2,
Wasabi, MinIO, Google Cloud Storage com chaves HMAC) — a mesma política
aplicada aos objetos do bucket.

Configuração por variáveis de ambiente (todas opcionais):

| Variável                | Padrão            | Função                                          |
|-------------------------|-------------------|-------------------------------------------------|
| BACKUP_DIR              | `<projeto>/backups` | Pasta local dos arquivos                      |
| BACKUP_DAILY_KEEP       | `7`               | Guarda tudo gerado nas N datas mais recentes    |
| BACKUP_WEEKLY_KEEP      | `4`               | Guarda o mais novo de cada uma das últimas N semanas ISO (exceto a corrente) |
| BACKUP_RETENTION_DAYS   | `45`              | Teto de idade em dias: nada mais velho sobrevive (0 = manter tudo, retenção desligada) |
| BACKUP_S3_BUCKET        | (sem upload)      | Bucket de destino; ausente = só backup local    |
| BACKUP_S3_PREFIX        | `sigere`          | Prefixo (pasta) dos objetos no bucket           |
| BACKUP_S3_ENDPOINT      | AWS padrão        | Endpoint S3-compatível (B2, R2, MinIO, GCS...)  |
| BACKUP_S3_REGION        | padrão do boto3   | Região do bucket                                |
| BACKUP_S3_PATH_STYLE    | `false`           | `true` para provedores que exigem path-style (MinIO) |

A prova de que o backup volta é o comando irmão `flask --app run
verify-restore` (app/restore_verify.py): restaura o snapshot mais recente —
da nuvem, quando houver — num banco descartável e compara com a produção.

Credenciais: as variáveis padrão `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
(ou a cadeia padrão do boto3 — role da instância, perfil configurado etc.).
"""
import gzip
import os
import re
import shutil
import subprocess
import sqlite3
import tempfile
from datetime import datetime, timedelta
from urllib.parse import urlsplit, parse_qs, unquote

import click
from flask import current_app
from flask.cli import with_appcontext

# Raiz do projeto (o pacote app/ vive um nível abaixo) — mesma base de app.config.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

# Só arquivos gerados pelo próprio comando são elegíveis à retenção local —
# qualquer outra coisa na pasta (dump manual, anotação) fica intacta.
PADRAO_ARQUIVOS = ('sigere-', '.gz')

# Carimbo de geração gravado no nome do arquivo: sigere-AAAAMMDD-HHMMSS-…
CARIMBO_NO_NOME = re.compile(r'^sigere-(\d{8})-(\d{6})-')


class BackupError(Exception):
    """Falha de backup com mensagem apresentável ao operador."""


def _inteiro_da_ambiente(nome, padrao):
    """Inteiro da variável de ambiente, com mensagem apresentável ao operador.

    Negativo é sempre erro de digitação (são contagens e dias) — rejeitado
    com aviso em vez de reinterpretado silenciosamente (um BACKUP_DAILY_KEEP
    negativo desativaria as diárias sem dizer nada).
    """
    bruto = os.environ.get(nome)
    if bruto is None:
        return padrao
    try:
        valor = int(bruto)
    except ValueError:
        raise BackupError(
            f'{nome}="{bruto}" não é um número inteiro — ajuste o .env e rode '
            'de novo.') from None
    if valor < 0:
        raise BackupError(
            f'{nome}="{bruto}" é negativo — precisa ser >= 0 (0 desliga o '
            'nível; no teto, mantém tudo). Ajuste o .env e rode de novo.')
    return valor


def _configuracao(destino=None, dias_retencao=None):
    """Resolve a configuração: parâmetro da CLI > variável de ambiente > padrão."""
    return {
        'diretorio': (destino
                      or os.environ.get('BACKUP_DIR')
                      or os.path.join(BASE_DIR, 'backups')),
        'diarias': _inteiro_da_ambiente('BACKUP_DAILY_KEEP', 7),
        'semanais': _inteiro_da_ambiente('BACKUP_WEEKLY_KEEP', 4),
        # Teto de idade: rede de segurança da política 7+4 — precisa cobrir as
        # 4 semanas ISO anteriores (~35 dias) com folga.
        'dias_retencao': (dias_retencao
                          if dias_retencao is not None
                          else _inteiro_da_ambiente('BACKUP_RETENTION_DAYS', 45)),
        'bucket': os.environ.get('BACKUP_S3_BUCKET') or None,
        'prefixo': os.environ.get('BACKUP_S3_PREFIX', 'sigere').strip('/'),
        'endpoint': os.environ.get('BACKUP_S3_ENDPOINT') or None,
        'regiao': os.environ.get('BACKUP_S3_REGION') or None,
        'path_style': os.environ.get('BACKUP_S3_PATH_STYLE', '').strip().lower()
                      in ('1', 'true', 'yes', 'on'),
    }


def _momento_de(nome, alternativo):
    """Momento de geração do backup: carimbo do nome; mtime/LastModified de reserva.

    O nome é a fonte confiável — mtime mente quando a pasta é copiada/rsyncada,
    o carimbo viaja com o arquivo.
    """
    achou = CARIMBO_NO_NOME.match(os.path.basename(nome))
    if achou:
        try:
            return datetime.strptime(achou.group(1) + achou.group(2), '%Y%m%d%H%M%S')
        except ValueError:
            # Carimbo sintaticamente válido mas impossível (ex.: 20260230 —
            # 30 de fevereiro): cai no mtime/LastModified em vez de derrubar
            # o comando com ValueError cru.
            pass
    return alternativo


def _selecionar_manter(registros, agora, diarias, semanais, teto_dias):
    """Escolhe quais backups sobrevivem à retenção (7 diárias + 4 semanais).

    `registros` são pares (momento, nome) em **naive local** — o mesmo
    calendário do servidor nas janelas diária/semanal, local ou nuvem.

    Política avô/pai/filho:
    - Teto de idade: nada gerado há mais de `teto_dias` dias sobrevive.
      **`teto_dias <= 0` desliga a retenção inteira — mantém tudo** (contrato
      antigo do `--keep-days 0`/`BACKUP_RETENTION_DAYS=0` preservado).
    - Diárias: tudo gerado nas `diarias` datas de calendário mais recentes.
    - Semanais: o backup mais novo de cada uma das `semanais` semanas ISO
      anteriores à semana corrente, dentro da janela real de 4 semanas ISO
      (não "4 semanas preenchidas") — é o que estende o alcance além das
      diárias (até ~35 dias no pior caso).
    - Rede de segurança: o mais recente dos elegíveis sempre permanece —
      mesmo quando diárias/semanais o deixariam de fora (o recém-gerado cai
      na semana corrente, que a seleção semanal pula).
    """
    if teto_dias <= 0:
        return {nome for _, nome in registros}
    corte = agora - timedelta(days=teto_dias)
    elegiveis = [par for par in registros if par[0] >= corte]
    elegiveis.sort(key=lambda par: par[0], reverse=True)

    manter = set()
    datas = []
    for momento, nome in elegiveis:
        dia = momento.date()
        if dia not in datas:
            datas.append(dia)
        if len(datas) <= diarias:
            manter.add(nome)

    semana_corrente = agora.isocalendar()[:2]
    # Janela semanal real: começa na segunda-feira da `semanais`-ésima semana
    # ISO anterior. Contar "semanas preenchidas" traria para dentro da
    # política um backup de semana vazia intermediária — dentro do teto de
    # idade, mas fora das 4 semanas prometidas.
    if semanais > 0:
        # Meia-noite da segunda — sem isto, a janela herdaria o horário da
        # execução e um backup gerado na segunda anterior MAS antes da hora
        # da limpeza (03:00 vs 03:20) cairia fora das N semanas prometidas.
        segunda_corrente = (agora - timedelta(days=agora.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)
        inicio_janela_semanal = segunda_corrente - timedelta(days=7 * semanais)
    else:
        inicio_janela_semanal = None
    semanas = []
    for momento, nome in elegiveis:
        if inicio_janela_semanal is not None and momento < inicio_janela_semanal:
            break  # elegíveis estão em ordem desc — tudo daqui para trás é velho demais
        semana = momento.isocalendar()[:2]
        if semana == semana_corrente or semana in semanas:
            continue
        if len(semanas) >= semanais:
            break
        semanas.append(semana)
        manter.add(nome)

    # O backup mais recente jamais sai — sem isto, BACKUP_DAILY_KEEP=0 com
    # semanais ativas deixaria o recém-gerado de fora (a seleção semanal pula
    # a semana corrente) e a limpeza — que roda ANTES do upload — o apagaria.
    if elegiveis:
        manter.add(elegiveis[0][1])
    return manter


def _interpretar_uri(uri):
    """Classifica a DATABASE_URL da aplicação.

    Retorna ('sqlite', caminho_do_arquivo) ou ('postgresql', {host, port, user,
    password, database, sslmode}). Esquemas fora desses dois caem em
    BackupError — o comando não adivinha motores que a aplicação não usa.
    """
    if uri.startswith('sqlite'):
        if ':memory:' in uri:
            raise BackupError(
                'O banco em memória (sqlite:///:memory:) não tem backup — '
                'configure um DATABASE_URL em arquivo.')
        resto = uri.split('sqlite://', 1)[1]
        # Convenção do SQLAlchemy: 'sqlite:///arquivo.db' é relativo;
        # 'sqlite:////caminho/absoluto' é absoluto (uma barra a mais).
        caminho = resto[1:] if resto.startswith('//') else resto.lstrip('/')
        return 'sqlite', caminho

    partes = urlsplit(uri)
    # SQLAlchemy aceita driver no scheme (postgresql+psycopg2://): o motor é
    # o que vem antes do "+".
    motor = partes.scheme.split('+', 1)[0]
    if motor not in ('postgres', 'postgresql'):
        raise BackupError(
            f'Motor de banco não suportado para backup: "{partes.scheme}". '
            'Use uma DATABASE_URL SQLite ou PostgreSQL.')
    sslmodes = parse_qs(partes.query).get('sslmode')
    # SQLAlchemy decodifica %XX em usuário/senha (ex.: senha com '@' vira
    # %40 na URI) — o pg_dump via ambiente espera o valor real.
    return 'postgresql', {
        'host': partes.hostname or 'localhost',
        'port': partes.port or 5432,
        'user': unquote(partes.username) if partes.username else None,
        'password': unquote(partes.password) if partes.password else None,
        'database': (partes.path or '').lstrip('/'),
        'sslmode': sslmodes[0] if sslmodes else None,
    }


def _caminho_sqlite(caminho):
    """Caminho absoluto do banco SQLite da aplicação.

    Flask-SQLAlchemy resolve caminho relativo na DATABASE_URL contra a pasta
    instance/ — backup e verificação precisam ler o MESMO arquivo que a
    aplicação escreve, não um homônimo relativo ao diretório corrente.
    """
    if os.path.isabs(caminho):
        return caminho
    return os.path.join(current_app.instance_path, caminho)


def _dump_sqlite(caminho_banco, arquivo_gz):
    """Snapshot consistente do SQLite (funciona com a aplicação no ar)."""
    if not os.path.exists(caminho_banco):
        raise BackupError(f'Banco SQLite não encontrado: {caminho_banco}')

    # A API de backup copia página a página com transação consistente —
    # diferente de copiar o .db direto, não corre o risco de pegar o arquivo
    # no meio de uma escrita (e inclui o que estiver no WAL).
    snapshot = arquivo_gz[:-3]  # mesmo nome sem o .gz, apagado após comprimir
    origem = sqlite3.connect(caminho_banco)
    try:
        destino = sqlite3.connect(snapshot)
        try:
            with destino:
                origem.backup(destino)
            integridade = destino.execute('PRAGMA integrity_check').fetchone()[0]
            if integridade != 'ok':
                raise BackupError(
                    f'Snapshot SQLite reprovado na verificação de integridade: '
                    f'{integridade}')
        finally:
            destino.close()
    finally:
        origem.close()

    with open(snapshot, 'rb') as bruto, gzip.open(arquivo_gz, 'wb') as gz:
        shutil.copyfileobj(bruto, gz)
    os.remove(snapshot)


def _dump_postgres(parametros, arquivo_gz, binario=None):
    """Dump SQL do PostgreSQL direto para o gzip, sem carregar tudo em memória."""
    binario = binario or os.environ.get('BACKUP_PG_DUMP_BIN', 'pg_dump')

    # Credenciais via ambiente (PGHOST/PGPASSWORD...): o `ps` de outros usuários
    # mostra os argumentos do processo, mas nunca o ambiente dele.
    env = os.environ.copy()
    env['PGHOST'] = str(parametros['host'])
    env['PGPORT'] = str(parametros['port'])
    env['PGDATABASE'] = parametros['database']
    if parametros.get('user'):
        env['PGUSER'] = parametros['user']
    if parametros.get('password'):
        env['PGPASSWORD'] = parametros['password']
    if parametros.get('sslmode'):
        env['PGSSLMODE'] = parametros['sslmode']

    with tempfile.TemporaryFile() as erros:
        try:
            processo = subprocess.Popen(
                [binario, '--no-owner', '--no-privileges'],
                stdout=subprocess.PIPE, stderr=erros, env=env)
        except FileNotFoundError:
            raise BackupError(
                f'Binário "{binario}" não encontrado. Instale o cliente '
                'PostgreSQL no servidor (Debian/Ubuntu: sudo apt install '
                'postgresql-client) ou aponte BACKUP_PG_DUMP_BIN para ele.')

        with processo.stdout, gzip.open(arquivo_gz, 'wb') as gz:
            shutil.copyfileobj(processo.stdout, gz)
        codigo = processo.wait()

        if codigo != 0:
            if os.path.exists(arquivo_gz):
                os.remove(arquivo_gz)
            erros.seek(0)
            detalhe = erros.read().decode('utf-8', 'replace').strip()
            raise BackupError(
                f'pg_dump terminou com código {codigo}: {detalhe or "sem detalhes"}')

    # Sanidade mínima: todo dump do pg_dump abre com esta marca.
    with gzip.open(arquivo_gz, 'rb') as gz:
        cabecalho = gz.read(256)
    if b'PostgreSQL database dump' not in cabecalho:
        raise BackupError(
            'O arquivo gerado não parece um dump do PostgreSQL — backup '
            'descartado por segurança.')


def _tamanho_legivel(caminho):
    tamanho = os.path.getsize(caminho)
    for unidade in ('B', 'KB', 'MB', 'GB'):
        if tamanho < 1024 or unidade == 'GB':
            return f'{tamanho:.1f} {unidade}' if unidade != 'B' else f'{tamanho} B'
        tamanho /= 1024


def _limpar_locais(diretorio, diarias, semanais, teto_dias, agora=None):
    """Aplica a retenção 7+4 aos arquivos locais `sigere-*.gz`.

    Devolve (nomes apagados, quantidade mantida, falhas de exclusão).
    Arquivos estranhos à pasta nunca são tocados; quem não pôde ser apagado
    (travado, sem permissão) fica de pé e volta separado em `falhas` — o
    resumo do operador não pode disfarçar retenção furada. Teto `<= 0`
    desliga a retenção: nada é apagado.
    """
    if teto_dias <= 0 or not os.path.isdir(diretorio):
        return [], 0, 0
    agora = agora or datetime.now()
    registros = []
    for nome in os.listdir(diretorio):
        if not (nome.startswith(PADRAO_ARQUIVOS[0]) and nome.endswith(PADRAO_ARQUIVOS[1])):
            continue
        caminho = os.path.join(diretorio, nome)
        if os.path.isfile(caminho):
            registros.append((_momento_de(nome, datetime.fromtimestamp(
                os.path.getmtime(caminho))), nome))

    manter = _selecionar_manter(registros, agora, diarias, semanais, teto_dias)
    removidos = []
    falhas = 0
    for momento, nome in registros:
        if nome in manter:
            continue
        try:
            os.remove(os.path.join(diretorio, nome))
        except OSError as erro:
            # Arquivo travado/sem permissão não derruba o backup — avisa e segue.
            click.echo(click.style(
                f'   ⚠️  Não consegui apagar {nome}: {erro}', fg='yellow'))
            falhas += 1
            continue
        removidos.append(nome)
    return sorted(removidos), len(manter), falhas


def _criar_cliente_s3(cfg):
    """Cliente S3 (boto3) para o endpoint configurado.

    Import preguiçoso: quem só faz backup local não precisa do boto3 instalado
    (e os testes substituem esta função por um cliente falso).
    """
    try:
        import boto3
    except ImportError:
        raise BackupError(
            "O pacote 'boto3' não está instalado — rode 'pip install boto3' "
            'no ambiente (já consta no requirements.txt).')
    from botocore.config import Config as ConfigBoto
    sessao = boto3.session.Session(region_name=cfg['regiao'])
    return sessao.client(
        's3',
        endpoint_url=cfg['endpoint'],
        config=ConfigBoto(
            s3={'addressing_style': 'path' if cfg['path_style'] else 'auto'}))


def _enviar_nuvem(caminho, cfg, cliente=None):
    """Sobe um arquivo para o bucket; devolve a chave do objeto criado."""
    cliente = cliente or _criar_cliente_s3(cfg)
    chave = f"{cfg['prefixo']}/{os.path.basename(caminho)}"
    cliente.upload_file(str(caminho), cfg['bucket'], chave)
    return chave


def _momento_nuvem(nome, alternativo):
    """Momento de um objeto do bucket: carimbo do nome; LastModified de reserva.

    Mesma fonte e mesmo calendário da retenção local — o carimbo viaja com o
    arquivo (LastModified mente quando o objeto é re-enviado/copiado) e é
    gravado em hora local do servidor, então um LastModified consciente é
    convertido de volta para naive local: as janelas diária/semanal são
    idênticas dos dois lados (23:30 local não vira "semana seguinte" na nuvem
    só porque o UTC já virou o dia).
    """
    momento = _momento_de(nome, alternativo)
    if momento.tzinfo is not None:
        momento = momento.astimezone().replace(tzinfo=None)
    return momento


def _limpar_nuvem(cfg, cliente=None, agora=None):
    """Aplica a mesma política 7+4 aos objetos de backup do bucket.

    Só objetos com o padrão de nome do próprio comando (`sigere-*.gz`) são
    elegíveis — qualquer outra coisa sob o prefixo não é tocada, espelhando
    o comportamento da pasta local. Teto `<= 0` desliga a retenção.
    """
    if cfg['dias_retencao'] <= 0:
        return []
    cliente = cliente or _criar_cliente_s3(cfg)
    agora = agora or datetime.now()  # naive local — mesmo calendário da pasta
    registros = []  # (momento, chave completa)
    paginador = cliente.get_paginator('list_objects_v2')
    for pagina in paginador.paginate(Bucket=cfg['bucket'], Prefix=cfg['prefixo'] + '/'):
        for obj in pagina.get('Contents', []):
            nome = obj['Key'].rsplit('/', 1)[-1]
            if not (nome.startswith(PADRAO_ARQUIVOS[0]) and nome.endswith(PADRAO_ARQUIVOS[1])):
                continue
            registros.append((_momento_nuvem(nome, obj['LastModified']),
                              obj['Key']))

    # Identidade é a CHAVE COMPLETA: cópias manuais em subpastas sob o
    # prefixo podem compartilhar o basename — decidir pelo nome apagaria ou
    # preservaria os dois de uma vez.
    manter = _selecionar_manter(
        registros, agora, cfg['diarias'], cfg['semanais'], cfg['dias_retencao'])
    vencidos = [chave for momento, chave in registros if chave not in manter]
    removidos = []
    for inicio in range(0, len(vencidos), 1000):
        lote = vencidos[inicio:inicio + 1000]
        resposta = cliente.delete_objects(
            Bucket=cfg['bucket'],
            Delete={'Objects': [{'Key': chave} for chave in lote],
                    'Quiet': True})
        # Quiet não esconde erro: chaves com permissão negada/object lock
        # voltam em Errors e precisam sair dos removidos — senão o resumo
        # informa uma retenção que não aconteceu.
        falhas = {erro['Key'] for erro in resposta.get('Errors', [])}
        if falhas:
            click.echo(click.style(
                f'   ⚠️  {len(falhas)} objeto(s) não foram apagados no bucket — '
                'verifique permissões/object lock.', fg='yellow'))
        removidos.extend(chave for chave in lote if chave not in falhas)
    return removidos


@click.command('backup')
@click.option('--dir', 'destino', default=None,
              type=click.Path(file_okay=False),
              metavar='CAMINHO',
              help='Pasta de destino (padrão: BACKUP_DIR ou ./backups).')
@click.option('--keep-days', 'dias', default=None, type=int, metavar='N',
              help='Teto de idade em dias (padrão: BACKUP_RETENTION_DAYS ou 45). '
                   '0 mantém tudo para sempre — desliga a retenção inteira, '
                   'como no contrato antigo; a política 7 diárias + 4 semanais '
                   'vem de BACKUP_DAILY_KEEP/BACKUP_WEEKLY_KEEP.')
@click.option('--no-upload', is_flag=True,
              help='Não envia para a nuvem, mesmo com BACKUP_S3_BUCKET definido.')
@with_appcontext
def backup_command(destino, dias, no_upload):
    """Gera o backup do banco de dados e envia para a nuvem.

    Snapshot comprimido (gzip) do banco configurado em DATABASE_URL — SQLite
    ou PostgreSQL — com retenção automática (7 diárias + 4 semanais) e upload
    para bucket compatível com a API S3 quando BACKUP_S3_BUCKET está definido.

    Uso: flask --app run backup
         flask --app run backup --no-upload   # só o arquivo local (teste)
    """
    try:
        cfg = _configuracao(destino=destino, dias_retencao=dias)
        uri = current_app.config['SQLALCHEMY_DATABASE_URI']
        motor, dados = _interpretar_uri(uri)
    except BackupError as erro:
        click.echo(click.style(f'❌ Falha no backup: {erro}', fg='red', bold=True))
        raise SystemExit(1)

    os.makedirs(cfg['diretorio'], exist_ok=True)
    carimbo = datetime.now().strftime('%Y%m%d-%H%M%S')
    if motor == 'sqlite':
        nome_arquivo = f'sigere-{carimbo}-sqlite.sqlite.gz'
    else:
        nome_arquivo = f'sigere-{carimbo}-postgres.sql.gz'
    arquivo_gz = os.path.join(cfg['diretorio'], nome_arquivo)

    click.echo(click.style(
        f'💾 Backup do banco ({motor}) iniciado...', fg='green', bold=True))
    try:
        if motor == 'sqlite':
            _dump_sqlite(_caminho_sqlite(dados), arquivo_gz)
        else:
            _dump_postgres(dados, arquivo_gz)
    except BackupError as erro:
        click.echo(click.style(f'❌ Falha no backup: {erro}', fg='red', bold=True))
        raise SystemExit(1)

    click.echo(f'   ✅ Arquivo gerado: {arquivo_gz} ({_tamanho_legivel(arquivo_gz)})')

    antigos, mantidos, falhas = _limpar_locais(
        cfg['diretorio'], cfg['diarias'], cfg['semanais'], cfg['dias_retencao'])
    if antigos:
        click.echo(f'   🧹 Retenção local: {mantidos} mantido(s), {len(antigos)} apagado(s) '
                   f'({cfg["diarias"]} diárias + {cfg["semanais"]} semanais)')
    if falhas:
        click.echo(click.style(
            f'   ⚠️  Retenção incompleta: {falhas} backup(s) não pôde ser apagado(s) — '
            'a pasta segue com mais do que a política manda.', fg='yellow'))

    if no_upload:
        click.echo(click.style('✅ Backup concluído (upload pulado por --no-upload).',
                               fg='green', bold=True))
        return
    if not cfg['bucket']:
        click.echo(click.style(
            'ℹ️  Backup concluído, apenas local — defina BACKUP_S3_BUCKET no .env '
            'para enviar à nuvem (docs/implantacao-producao.md).', fg='green', bold=True))
        return

    try:
        cliente = _criar_cliente_s3(cfg)
        chave = _enviar_nuvem(arquivo_gz, cfg, cliente)
        removidos = _limpar_nuvem(cfg, cliente)
    except BackupError as erro:
        click.echo(click.style(f'❌ Falha no backup: {erro}', fg='red', bold=True))
        raise SystemExit(1)
    click.echo(f'   ☁️  Enviado para s3://{cfg["bucket"]}/{chave}')
    if removidos:
        click.echo(f'   🧹 Retenção na nuvem: {len(removidos)} objeto(s) antigo(s) apagado(s)')
    click.echo(click.style('✅ Backup concluído e enviado para a nuvem!',
                           fg='green', bold=True))
