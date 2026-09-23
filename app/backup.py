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

Depois do dump: retenção local (apaga arquivos `sigere-*.gz` mais antigos que
BACKUP_RETENTION_DAYS) e, quando BACKUP_S3_BUCKET está definido, upload para
qualquer armazenamento compatível com a API S3 (AWS S3, Backblaze B2,
Cloudflare R2, Wasabi, MinIO, Google Cloud Storage com chaves HMAC) — com a
mesma retenção aplicada aos objetos antigos do bucket.

Configuração por variáveis de ambiente (todas opcionais):

| Variável                | Padrão            | Função                                          |
|-------------------------|-------------------|-------------------------------------------------|
| BACKUP_DIR              | `<projeto>/backups` | Pasta local dos arquivos                      |
| BACKUP_RETENTION_DAYS   | `14`              | Dias de retenção local e na nuvem (0 = manter tudo) |
| BACKUP_S3_BUCKET        | (sem upload)      | Bucket de destino; ausente = só backup local    |
| BACKUP_S3_PREFIX        | `sigere`          | Prefixo (pasta) dos objetos no bucket           |
| BACKUP_S3_ENDPOINT      | AWS padrão        | Endpoint S3-compatível (B2, R2, MinIO, GCS...)  |
| BACKUP_S3_REGION        | padrão do boto3   | Região do bucket                                |
| BACKUP_S3_PATH_STYLE    | `false`           | `true` para provedores que exigem path-style (MinIO) |

Credenciais: as variáveis padrão `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
(ou a cadeia padrão do boto3 — role da instância, perfil configurado etc.).
"""
import gzip
import os
import shutil
import subprocess
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, parse_qs, unquote

import click
from flask import current_app
from flask.cli import with_appcontext

# Raiz do projeto (o pacote app/ vive um nível abaixo) — mesma base de app.config.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

# Só arquivos gerados pelo próprio comando são elegíveis à retenção local —
# qualquer outra coisa na pasta (dump manual, anotação) fica intacta.
PADRAO_ARQUIVOS = ('sigere-', '.gz')


class BackupError(Exception):
    """Falha de backup com mensagem apresentável ao operador."""


def _configuracao(destino=None, dias_retencao=None):
    """Resolve a configuração: parâmetro da CLI > variável de ambiente > padrão."""
    return {
        'diretorio': (destino
                      or os.environ.get('BACKUP_DIR')
                      or os.path.join(BASE_DIR, 'backups')),
        'dias_retencao': int(dias_retencao
                             if dias_retencao is not None
                             else os.environ.get('BACKUP_RETENTION_DAYS', '14')),
        'bucket': os.environ.get('BACKUP_S3_BUCKET') or None,
        'prefixo': os.environ.get('BACKUP_S3_PREFIX', 'sigere').strip('/'),
        'endpoint': os.environ.get('BACKUP_S3_ENDPOINT') or None,
        'regiao': os.environ.get('BACKUP_S3_REGION') or None,
        'path_style': os.environ.get('BACKUP_S3_PATH_STYLE', '').strip().lower()
                      in ('1', 'true', 'yes', 'on'),
    }


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
    if partes.scheme not in ('postgres', 'postgresql'):
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


def _limpar_locais(diretorio, dias, agora=None):
    """Apaga backups locais (`sigere-*.gz`) mais antigos que `dias` dias."""
    if dias <= 0 or not os.path.isdir(diretorio):
        return []
    corte = (agora or datetime.now()) - timedelta(days=dias)
    removidos = []
    for nome in sorted(os.listdir(diretorio)):
        if not (nome.startswith(PADRAO_ARQUIVOS[0]) and nome.endswith(PADRAO_ARQUIVOS[1])):
            continue
        caminho = os.path.join(diretorio, nome)
        if os.path.isfile(caminho) and datetime.fromtimestamp(os.path.getmtime(caminho)) < corte:
            os.remove(caminho)
            removidos.append(nome)
    return removidos


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


def _limpar_nuvem(cfg, cliente=None, agora=None):
    """Apaga objetos do bucket (sob o prefixo) mais antigos que a retenção."""
    if cfg['dias_retencao'] <= 0:
        return []
    cliente = cliente or _criar_cliente_s3(cfg)
    corte = (agora or datetime.now(timezone.utc)) - timedelta(days=cfg['dias_retencao'])
    removidos = []
    paginador = cliente.get_paginator('list_objects_v2')
    for pagina in paginador.paginate(Bucket=cfg['bucket'], Prefix=cfg['prefixo'] + '/'):
        antigos = [obj for obj in pagina.get('Contents', [])
                   if obj['LastModified'] < corte]
        for inicio in range(0, len(antigos), 1000):
            lote = antigos[inicio:inicio + 1000]
            cliente.delete_objects(
                Bucket=cfg['bucket'],
                Delete={'Objects': [{'Key': obj['Key']} for obj in lote],
                        'Quiet': True})
            removidos.extend(obj['Key'] for obj in lote)
    return removidos


@click.command('backup')
@click.option('--dir', 'destino', default=None,
              type=click.Path(file_okay=False),
              metavar='CAMINHO',
              help='Pasta de destino (padrão: BACKUP_DIR ou ./backups).')
@click.option('--keep-days', 'dias', default=None, type=int, metavar='N',
              help='Dias de retenção local/nuvem (padrão: BACKUP_RETENTION_DAYS ou 14).')
@click.option('--no-upload', is_flag=True,
              help='Não envia para a nuvem, mesmo com BACKUP_S3_BUCKET definido.')
@with_appcontext
def backup_command(destino, dias, no_upload):
    """Gera o backup do banco de dados e envia para a nuvem.

    Snapshot comprimido (gzip) do banco configurado em DATABASE_URL — SQLite
    ou PostgreSQL — com retenção automática dos arquivos antigos e upload
    para bucket compatível com a API S3 quando BACKUP_S3_BUCKET está definido.

    Uso: flask --app run backup
         flask --app run backup --no-upload   # só o arquivo local (teste)
    """
    cfg = _configuracao(destino=destino, dias_retencao=dias)
    uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    motor, dados = _interpretar_uri(uri)

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
            _dump_sqlite(dados, arquivo_gz)
        else:
            _dump_postgres(dados, arquivo_gz)
    except BackupError as erro:
        click.echo(click.style(f'❌ Falha no backup: {erro}', fg='red', bold=True))
        raise SystemExit(1)

    click.echo(f'   ✅ Arquivo gerado: {arquivo_gz} ({_tamanho_legivel(arquivo_gz)})')

    antigos = _limpar_locais(cfg['diretorio'], cfg['dias_retencao'])
    if antigos:
        click.echo(f'   🧹 Retenção local: {len(antigos)} backup(s) antigo(s) apagado(s) '
                   f'(> {cfg["dias_retencao"]} dias)')

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
