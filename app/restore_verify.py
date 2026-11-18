"""Verificação de restauração — a prova de que o backup volta.

O comando `flask --app run verify-restore` pega o snapshot mais recente — da
pasta local ou, com BACKUP_S3_BUCKET definido, baixa o objeto mais novo do
bucket (a cópia que está fora do servidor é a testada) — restaura em um banco
descartável, separado da produção, e compara os dois:

- toda tabela da produção precisa existir na cópia restaurada (tabela só na
  cópia também é reportada — sintoma clássico de backup anterior a uma
  migration);
- a contagem de linhas de cada tabela é conferida com a produção; diferença
  maior que --tolerancia (padrão 0) reprova.

O tempo de restauração é medido e impresso — é o número real para o runbook.
O banco descartável é apagado ao final, inclusive quando a verificação falha.

Agende junto do backup (no mesmo timer/cron): restaurar o snapshot de minutos
atrás contra uma produção parada da madrugada é o cenário sem desvio de
linhas — desvio reprova de verdade.
"""
import gzip
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from datetime import datetime

import click
from flask import current_app
from flask.cli import with_appcontext

# Reaproveita a configuração, a leitura da DATABASE_URL e o cliente S3 do
# módulo de backup — mesma pasta, mesmas credenciais, um só lugar para ajustar.
from app.backup import (BackupError, PADRAO_ARQUIVOS, _criar_cliente_s3,
                        _configuracao, _interpretar_uri, _momento_de)

# Tabelas cujo vazio/ausência indica restauração inútil mesmo sem desvio
# aparente — aparecem destacadas no relatório.
TABELAS_ESSENCIAIS = ('users', 'unities', 'classrooms', 'reservations')


class RestoreError(Exception):
    """Falha de verificação com mensagem apresentável ao operador."""


def _nome_seguro(identificador):
    """Coloca aspas duplas em identificador SQL (serve em SQLite e PostgreSQL)."""
    return '"' + identificador.replace('"', '""') + '"'


# ── Localizar o backup a conferir ─────────────────────────────────────────

def _mais_recente_local(diretorio):
    """Caminho do `sigere-*.gz` mais novo da pasta (None se não houver)."""
    mais_novo = None
    if os.path.isdir(diretorio):
        for nome in os.listdir(diretorio):
            if not (nome.startswith(PADRAO_ARQUIVOS[0]) and nome.endswith(PADRAO_ARQUIVOS[1])):
                continue
            caminho = os.path.join(diretorio, nome)
            if not os.path.isfile(caminho):
                continue
            momento = _momento_de(nome, datetime.fromtimestamp(
                os.path.getmtime(caminho)))
            if mais_novo is None or momento > mais_novo[0]:
                mais_novo = (momento, caminho)
    return mais_novo[1] if mais_novo else None


def _mais_recente_nuvem(cfg, cliente):
    """Chave do objeto mais novo sob o prefixo do bucket (None se vazio)."""
    paginador = cliente.get_paginator('list_objects_v2')
    mais_novo = None
    for pagina in paginador.paginate(Bucket=cfg['bucket'], Prefix=cfg['prefixo'] + '/'):
        for obj in pagina.get('Contents', []):
            if mais_novo is None or obj['LastModified'] > mais_novo['LastModified']:
                mais_novo = obj
    return mais_novo['Key'] if mais_novo else None


def _localizar_backup(cfg, arquivo):
    """Devolve (caminho_local_do_gz, descrição_da_origem) ou levanta BackupError.

    Com --arquivo usa o caminho dado; sem ele prefere o mais novo da pasta
    local e, na falta deste, baixa o objeto mais novo do bucket — é a cópia
    fora do servidor que precisa voltar, não a que está ao lado do banco.
    """
    if arquivo:
        if not os.path.isfile(arquivo):
            raise BackupError(f'Backup indicado não encontrado: {arquivo}')
        return arquivo, 'arquivo informado'

    caminho = _mais_recente_local(cfg['diretorio'])
    if caminho:
        return caminho, f'pasta local ({caminho})'
    if not cfg['bucket']:
        raise BackupError(
            f'Nenhum backup em {cfg["diretorio"]} e nenhum BACKUP_S3_BUCKET '
            'configurado — gere um antes com `flask --app run backup`.')

    os.makedirs(cfg['diretorio'], exist_ok=True)
    cliente = _criar_cliente_s3(cfg)
    chave = _mais_recente_nuvem(cfg, cliente)
    if not chave:
        raise BackupError(
            f'O bucket s3://{cfg["bucket"]}/{cfg["prefixo"]}/ está vazio — '
            'gere um backup antes com `flask --app run backup`.')
    caminho = os.path.join(cfg['diretorio'], chave.rsplit('/', 1)[-1])
    cliente.download_file(cfg['bucket'], chave, caminho)
    return caminho, f'nuvem (s3://{cfg["bucket"]}/{chave})'


# ── Restaurar o snapshot em banco descartável ─────────────────────────────

def _restaurar_sqlite(arquivo_gz, destino):
    """Descomprime o snapshot num arquivo novo e valida a integridade."""
    with gzip.open(arquivo_gz, 'rb') as gz, open(destino, 'wb') as bruto:
        shutil.copyfileobj(gz, bruto)
    conexao = sqlite3.connect(destino)
    try:
        integridade = conexao.execute('PRAGMA integrity_check').fetchone()[0]
        if integridade != 'ok':
            raise BackupError(
                f'Cópia restaurada reprovou na verificação de integridade: '
                f'{integridade}')
    finally:
        conexao.close()


def _conectar_postgres(parametros, banco):
    """Conexão crua (psycopg2) com o servidor do DATABASE_URL."""
    import psycopg2
    acesso = {chave: valor for chave, valor in (
        ('host', parametros['host']),
        ('port', parametros['port']),
        ('user', parametros['user']),
        ('password', parametros['password']),
        ('sslmode', parametros['sslmode']),
        ('dbname', banco)) if valor}
    try:
        return psycopg2.connect(**acesso)
    except psycopg2.OperationalError as erro:
        raise BackupError(f'Conexão com o PostgreSQL falhou (banco "{banco}"): {erro}')


def _criar_banco_postgres(parametros, banco_teste):
    """Cria o banco descartável da verificação (recria se sobrou de falha)."""
    import psycopg2
    try:
        conexao = _conectar_postgres(parametros, parametros['database'])
        try:
            conexao.autocommit = True  # CREATE/DATABASE não roda em transação
            with conexao.cursor() as cursor:
                cursor.execute('DROP DATABASE IF EXISTS ' + _nome_seguro(banco_teste))
                cursor.execute('CREATE DATABASE ' + _nome_seguro(banco_teste))
        finally:
            conexao.close()
    except psycopg2.errors.InsufficientPrivilege:
        usuario = parametros.get('user') or '<usuário>'
        raise BackupError(
            f'O usuário "{usuario}" não tem permissão de criar bancos — '
            'necessária uma única vez para o banco descartável da verificação. '
            'Libere com: sudo -u postgres psql -c '
            f'"ALTER USER {_nome_seguro(usuario)} WITH CREATEDB;"')


def _apagar_banco_postgres(parametros, banco_teste):
    """Apaga o banco descartável; sobra não é fatal, só avisada."""
    try:
        conexao = _conectar_postgres(parametros, parametros['database'])
        try:
            conexao.autocommit = True
            with conexao.cursor() as cursor:
                cursor.execute('DROP DATABASE IF EXISTS ' + _nome_seguro(banco_teste))
        finally:
            conexao.close()
    except Exception:
        click.echo(click.style(
            f'   ⚠️  Não consegui apagar o banco descartável "{banco_teste}" — '
            'apague à mão: DROP DATABASE ' + _nome_seguro(banco_teste) + ';',
            fg='yellow'))


def _restaurar_postgres(parametros, arquivo_gz, banco_teste):
    """Cria o banco descartável e restaura o dump com psql --ON_ERROR_STOP."""
    binario = os.environ.get('BACKUP_PSQL_BIN', 'psql')
    _criar_banco_postgres(parametros, banco_teste)

    # Credenciais via ambiente, como no pg_dump — nunca na linha de comando.
    env = os.environ.copy()
    env['PGHOST'] = str(parametros['host'])
    env['PGPORT'] = str(parametros['port'])
    env['PGDATABASE'] = banco_teste
    if parametros.get('user'):
        env['PGUSER'] = parametros['user']
    if parametros.get('password'):
        env['PGPASSWORD'] = parametros['password']
    if parametros.get('sslmode'):
        env['PGSSLMODE'] = parametros['sslmode']

    sql = os.path.splitext(arquivo_gz)[0] + '.sql'
    try:
        with gzip.open(arquivo_gz, 'rb') as gz, open(sql, 'wb') as bruto:
            shutil.copyfileobj(gz, bruto)
        with tempfile.TemporaryFile() as erros:
            try:
                processo = subprocess.run(
                    [binario, '--quiet', '--set=ON_ERROR_STOP=1', '--file=' + sql],
                    env=env, stderr=erros)
            except FileNotFoundError:
                raise BackupError(
                    f'Binário "{binario}" não encontrado. Instale o cliente '
                    'PostgreSQL (Debian/Ubuntu: sudo apt install '
                    'postgresql-client) ou aponte BACKUP_PSQL_BIN para ele.')
            if processo.returncode != 0:
                erros.seek(0)
                detalhe = erros.read().decode('utf-8', 'replace').strip()
                raise BackupError(
                    f'psql terminou com código {processo.returncode} '
                    f'restaurando em "{banco_teste}": {detalhe or "sem detalhes"}')
    finally:
        if os.path.exists(sql):
            os.remove(sql)


# ── Inventário de tabelas e linhas ────────────────────────────────────────

def _linhas_por_tabela_sqlite(caminho):
    """Mapa {tabela: linhas} de um arquivo SQLite (produção ou cópia)."""
    if not os.path.exists(caminho):
        raise BackupError(f'Banco SQLite não encontrado: {caminho}')
    conexao = sqlite3.connect(caminho)
    try:
        tabelas = [registro[0] for registro in conexao.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")]
        return {tabela: conexao.execute(
            'SELECT COUNT(*) FROM ' + _nome_seguro(tabela)).fetchone()[0]
            for tabela in tabelas}
    finally:
        conexao.close()


def _linhas_por_tabela_postgres(parametros, banco):
    """Mapa {tabela: linhas} do schema public de um banco no servidor."""
    conexao = _conectar_postgres(parametros, banco)
    try:
        with conexao.cursor() as cursor:
            cursor.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'")
            tabelas = [registro[0] for registro in cursor.fetchall()]
            linhas = {}
            for tabela in tabelas:
                cursor.execute('SELECT COUNT(*) FROM ' + _nome_seguro(tabela))
                linhas[tabela] = cursor.fetchone()[0]
        return linhas
    finally:
        conexao.close()


def _comparar(producao, copia, tolerancia):
    """Devolve (faltando, extras, desvios) entre produção e cópia restaurada."""
    faltando = sorted(set(producao) - set(copia))
    extras = sorted(set(copia) - set(producao))
    desvios = sorted((tabela, producao[tabela], copia[tabela])
                     for tabela in set(producao) & set(copia)
                     if abs(producao[tabela] - copia[tabela]) > tolerancia)
    return faltando, extras, desvios


def _resumo_essenciais(producao, copia):
    """Uma linha por tabela essencial: `users 5→5`. Ausente vira erro adiante."""
    return ' · '.join(
        f'{tabela} {producao.get(tabela, "AUSENTE")}→{copia.get(tabela, "AUSENTE")}'
        for tabela in TABELAS_ESSENCIAIS)


# ── Comando ───────────────────────────────────────────────────────────────

@click.command('verify-restore')
@click.option('--arquivo', 'arquivo', default=None,
              type=click.Path(dir_okay=False), metavar='CAMINHO',
              help='Backup específico a conferir (padrão: o mais recente, '
                   'local ou baixado da nuvem).')
@click.option('--dir', 'destino', default=None,
              type=click.Path(file_okay=False), metavar='CAMINHO',
              help='Pasta onde procurar os backups (padrão: BACKUP_DIR ou ./backups).')
@click.option('--tolerancia', default=0, type=int, metavar='N',
              help='Diferença máxima de linhas aceita por tabela (padrão 0).')
@with_appcontext
def verify_restore_command(arquivo, destino, tolerancia):
    """Restaura o backup mais recente num banco descartável e confere com a produção.

    Toda tabela da produção precisa existir na cópia e as contagens de linhas
    precisam bater (salvo --tolerancia). Termina com código 1 quando o backup
    não volta — feita para rodar no mesmo timer/cron do backup diário.

    Uso: flask --app run verify-restore
         flask --app run verify-restore --tolerancia 5
    """
    cfg = _configuracao(destino=destino)
    motor, dados = _interpretar_uri(current_app.config['SQLALCHEMY_DATABASE_URI'])

    click.echo(click.style(
        '🔎 Verificação de restauração iniciada...', fg='green', bold=True))
    try:
        caminho_backup, origem = _localizar_backup(cfg, arquivo)
    except BackupError as erro:
        click.echo(click.style(f'❌ Falha na verificação: {erro}', fg='red', bold=True))
        raise SystemExit(1)
    click.echo(f'   📦 Backup: {os.path.basename(caminho_backup)} — origem: {origem}')

    # Banco descartável no mesmo servidor, nome fixo e derivado — a próxima
    # execução recria por cima mesmo que uma anterior tenha mordo no meio.
    # (SQLite restaura num arquivo temporário; o nome só faz sentido no PG.)
    banco_teste = None
    pasta_temporaria = tempfile.mkdtemp(prefix='sigere-verify-')
    try:
        inicio = time.monotonic()
        try:
            if motor == 'sqlite':
                copia_restaurada = os.path.join(pasta_temporaria, 'restaurado.sqlite')
                _restaurar_sqlite(caminho_backup, copia_restaurada)
                duracao = time.monotonic() - inicio
                copia = _linhas_por_tabela_sqlite(copia_restaurada)
                producao = _linhas_por_tabela_sqlite(dados)
            else:
                banco_teste = (dados['database'] or 'sigere')[:50] + '_verificacao'
                _restaurar_postgres(dados, caminho_backup, banco_teste)
                duracao = time.monotonic() - inicio
                copia = _linhas_por_tabela_postgres(dados, banco_teste)
                producao = _linhas_por_tabela_postgres(dados, dados['database'])
        except BackupError as erro:
            click.echo(click.style(f'❌ Falha na verificação: {erro}',
                                   fg='red', bold=True))
            raise SystemExit(1)
    finally:
        shutil.rmtree(pasta_temporaria, ignore_errors=True)
        if banco_teste:
            _apagar_banco_postgres(dados, banco_teste)

    faltando, extras, desvios = _comparar(producao, copia, tolerancia)
    click.echo(f'   ⏱️  Restauração levou {duracao:.1f} s')
    click.echo(f'   🗃️  Tabelas: {len(producao)} na produção, '
               f'{len(copia)} na cópia restaurada')
    click.echo(f'   📌 Essenciais: {_resumo_essenciais(producao, copia)}')

    reprovacoes = []
    if faltando:
        reprovacoes.append(
            'tabelas da produção ausentes na cópia: ' + ', '.join(faltando))
    if extras:
        reprovacoes.append(
            'tabelas na cópia que não existem na produção (backup anterior a '
            'migration?): ' + ', '.join(extras))
    for tabela, antes, depois in desvios:
        reprovacoes.append(
            f'contagem de linhas divergiu em "{tabela}": '
            f'produção {antes}, cópia {depois}')

    if reprovacoes:
        for reprovacao in reprovacoes:
            click.echo(click.style(f'   ❌ {reprovacao}', fg='red'))
        if desvios:
            click.echo(click.style(
                '   💡 Com a produção no ar, as contagens mudam entre o backup '
                'e a conferência — rode junto do backup (timer/cron) ou passe '
                '--tolerancia N.', fg='yellow'))
        click.echo(click.style(
            '❌ Verificação REPROVADA — este backup não está garantido.',
            fg='red', bold=True))
        raise SystemExit(1)

    click.echo(click.style(
        f'✅ Backup restaurável: {len(copia)} tabelas e as contagens de linhas '
        f'conferem com a produção (tolerância {tolerancia})!',
        fg='green', bold=True))
