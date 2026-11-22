"""Testes do comando `flask backup` (snapshot do banco + retenção + upload S3).

Cobre:
- geração de snapshot SQLite válido (integridade e conteúdo) com a CLI;
- retenção local de arquivos antigos (e preservação de estranhos à pasta);
- upload e retenção na nuvem com cliente S3 falso (sem rede, sem boto3);
- interpretação das DATABASE_URL SQLite e PostgreSQL.
"""
import gzip
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import create_app
from app import backup as modulo_backup
from app.config import Config
from app.extensions import db
from app.models import User


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


def _arquivo_antigo(pasta, nome, dias_atras):
    """Cria um arquivo de backup falso com mtime envelhecido."""
    caminho = os.path.join(pasta, nome)
    with open(caminho, 'wb') as fh:
        fh.write(b'x')
    passado = datetime.now() - timedelta(days=dias_atras)
    os.utime(caminho, (passado.timestamp(), passado.timestamp()))
    return caminho


class BackupCommandTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False

        self.pasta_backup = tempfile.mkdtemp(prefix='sigere-backup-test-')

        with self.app.app_context():
            db.create_all()
            user = User(email='gestor@escola.edu', full_name='Gestor Teste',
                        role='room', profile_type='employee',
                        force_password_change=False)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)
        for nome in os.listdir(self.pasta_backup):
            os.remove(os.path.join(self.pasta_backup, nome))
        os.rmdir(self.pasta_backup)

    def _rodar(self, *args):
        return self.app.test_cli_runner().invoke(args=['backup', *args])

    # ── Geração do snapshot ────────────────────────────────────────────────

    def test_backup_sqlite_gera_snapshot_valido(self):
        resultado = self._rodar('--no-upload', '--dir', self.pasta_backup)
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('Backup', resultado.output)

        arquivos = os.listdir(self.pasta_backup)
        self.assertEqual(len(arquivos), 1)
        self.assertRegex(arquivos[0], r'^sigere-\d{8}-\d{6}-sqlite\.sqlite\.gz$')

        caminho = os.path.join(self.pasta_backup, arquivos[0])
        snapshot = caminho[:-3] + '.aberto'
        with gzip.open(caminho, 'rb') as gz, open(snapshot, 'wb') as bruto:
            bruto.write(gz.read())
        conexao = sqlite3.connect(snapshot)
        try:
            self.assertEqual(
                conexao.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(
                conexao.execute('SELECT COUNT(*) FROM users').fetchone()[0], 1)
        finally:
            conexao.close()
            os.remove(snapshot)

    def test_backup_sem_bucket_avisa_que_ficou_local(self):
        with mock.patch.dict(os.environ, {'BACKUP_S3_BUCKET': ''}):
            resultado = self._rodar('--dir', self.pasta_backup)
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('apenas local', resultado.output)

    # ── Retenção local ─────────────────────────────────────────────────────

    def test_retencao_remove_apenas_backups_antigos(self):
        antigo = _arquivo_antigo(self.pasta_backup,
                                 'sigere-20200101-000000-sqlite.sqlite.gz', 30)
        recente = _arquivo_antigo(self.pasta_backup,
                                  'sigere-20990101-000000-sqlite.sqlite.gz', 1)
        estranho = os.path.join(self.pasta_backup, 'nao-e-backup.gz')
        with open(estranho, 'wb') as fh:
            fh.write(b'x')

        resultado = self._rodar('--no-upload', '--dir', self.pasta_backup)
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertFalse(os.path.exists(antigo))
        self.assertTrue(os.path.exists(recente))
        self.assertTrue(os.path.exists(estranho))
        self.assertIn('Retenção local: 1', resultado.output)

    # ── Upload e retenção na nuvem (cliente S3 falso) ──────────────────────

    def test_upload_e_retencao_nuvem_com_cliente_falso(self):
        antigo_nuvem = {
            'Key': 'sigere/sigere-20200101-000000-postgres.sql.gz',
            'LastModified': datetime.now(timezone.utc) - timedelta(days=30),
        }
        recente_nuvem = {
            'Key': 'sigere/sigere-20990101-000000-postgres.sql.gz',
            'LastModified': datetime.now(timezone.utc) - timedelta(days=1),
        }
        falso_cliente = mock.Mock()
        paginador = mock.Mock()
        paginador.paginate.return_value = [{'Contents': [antigo_nuvem, recente_nuvem]}]
        falso_cliente.get_paginator.return_value = paginador

        ambiente = {'BACKUP_S3_BUCKET': 'bucket-sigere',
                    'BACKUP_S3_PREFIX': 'sigere'}
        with mock.patch.dict(os.environ, ambiente), \
                mock.patch.object(modulo_backup, '_criar_cliente_s3',
                                  return_value=falso_cliente):
            resultado = self._rodar('--dir', self.pasta_backup)

        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('s3://bucket-sigere/sigere/', resultado.output)

        # O snapshot recém-gerado foi o objeto enviado…
        enviados = falso_cliente.upload_file.call_args_list
        self.assertEqual(len(enviados), 1)
        self.assertEqual(enviados[0].args[1], 'bucket-sigere')
        self.assertRegex(enviados[0].args[2], r'^sigere/sigere-\d{8}-\d{6}-sqlite\.')
        # …e só o objeto vencido saiu do bucket.
        excluidos = falso_cliente.delete_objects.call_args_list
        self.assertEqual(len(excluidos), 1)
        self.assertEqual(excluidos[0].kwargs['Delete']['Objects'],
                         [{'Key': antigo_nuvem['Key']}])

    def test_upload_sem_boto3_falha_com_mensagem_clara(self):
        ambiente = {'BACKUP_S3_BUCKET': 'bucket-sigere'}
        with mock.patch.dict(os.environ, ambiente), \
                mock.patch.dict('sys.modules', {'boto3': None}):
            resultado = self._rodar('--dir', self.pasta_backup)
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('boto3', resultado.output)
        # O arquivo local continua intacto — o upload falhou, o backup não.
        self.assertEqual(len(os.listdir(self.pasta_backup)), 1)

    # ── Interpretação da DATABASE_URL ──────────────────────────────────────

    def test_interpretar_uri_sqlite(self):
        motor, caminho = modulo_backup._interpretar_uri('sqlite:///reservation.db')
        self.assertEqual(motor, 'sqlite')
        self.assertEqual(caminho, 'reservation.db')

        motor, caminho = modulo_backup._interpretar_uri('sqlite:////var/lib/sigere/db.sqlite')
        self.assertEqual(motor, 'sqlite')
        self.assertEqual(caminho, '/var/lib/sigere/db.sqlite')

    def test_interpretar_uri_postgresql(self):
        motor, p = modulo_backup._interpretar_uri(
            'postgresql://sigere:senha%20forte@db.local:5433/sigeredb?sslmode=require')
        self.assertEqual(motor, 'postgresql')
        self.assertEqual(p['host'], 'db.local')
        self.assertEqual(p['port'], 5433)
        self.assertEqual(p['user'], 'sigere')
        self.assertEqual(p['password'], 'senha forte')
        self.assertEqual(p['database'], 'sigeredb')
        self.assertEqual(p['sslmode'], 'require')

    def test_interpretar_uri_nao_suportada(self):
        with self.assertRaises(modulo_backup.BackupError):
            modulo_backup._interpretar_uri('mysql://root@localhost/antigo')


if __name__ == '__main__':
    unittest.main()
