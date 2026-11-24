"""Testes do comando `flask verify-restore` (restaurar e conferir o backup).

Cobre o caminho SQLite (o mesmo do CI, sem rede nem servidor externo):
- restauração do snapshot mais recente da pasta com estrutura e linhas batendo;
- reprovação com desvio de linhas acima da tolerância (e aprovação com ela);
- reprovação com backup truncado (sem tabelas);
- erro claro quando o arquivo indicado não existe;
- preferência pela cópia da nuvem quando BACKUP_S3_BUCKET está definido
  (cliente S3 falso, sem rede) e envolvimento de falhas do boto em
  BackupError.

O caminho PostgreSQL segue o mesmo fluxo com psql/psycopg2 e é exercitado
pelos testes de interpretação de URI do módulo de backup.
"""
import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from app import create_app
from app import restore_verify as modulo_verificar
from app.config import Config
from app.extensions import db
from app.models import User


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class VerifyRestoreTestCase(unittest.TestCase):
    def setUp(self):
        # Ambiente pode exportar BACKUP_S3_BUCKET — os testes locais não podem
        # chamar S3 de verdade; os de nuvem definem o próprio patch por cima.
        ambiente = mock.patch.dict(os.environ, {'BACKUP_S3_BUCKET': '',
                                                'BACKUP_S3_ENDPOINT': '',
                                                'BACKUP_S3_REGION': ''})
        ambiente.start()
        self.addCleanup(ambiente.stop)

        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False

        self.pasta_backup = tempfile.mkdtemp(prefix='sigere-verify-test-')

        with self.app.app_context():
            db.create_all()
            user = User(email='gestor@escola.edu', full_name='Gestor Teste',
                        role='room', profile_type='employee',
                        force_password_change=False)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.commit()

        # Backup inicial da suíte: é ele que as verificações restauram.
        resultado = self.app.test_cli_runner().invoke(
            args=['backup', '--no-upload', '--dir', self.pasta_backup])
        assert resultado.exit_code == 0, resultado.output

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
        return self.app.test_cli_runner().invoke(
            args=['verify-restore', '--dir', self.pasta_backup, *args])

    # ── Caminho feliz ─────────────────────────────────────────────────────

    def test_confere_backup_recente(self):
        resultado = self._rodar()
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('Verificação de restauração', resultado.output)
        self.assertIn('pasta local', resultado.output)
        self.assertIn('Restauração levou', resultado.output)
        self.assertIn('users 1→1', resultado.output)
        self.assertIn('reservations 0→0', resultado.output)
        self.assertIn('Backup restaurável', resultado.output)

    # ── Desvio de linhas ──────────────────────────────────────────────────

    def test_reprova_desvio_e_passa_com_tolerancia(self):
        with self.app.app_context():
            extra = User(email='novo@escola.edu', full_name='Chegada Depois',
                         role='room', profile_type='employee',
                         force_password_change=False)
            extra.set_password('SenhaForte123')
            db.session.add(extra)
            db.session.commit()

        resultado = self._rodar()
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('divergiu em "users"', resultado.output)
        self.assertIn('produção 2, cópia 1', resultado.output)
        self.assertIn('--tolerancia', resultado.output)

        resultado = self._rodar('--tolerancia', '1')
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('Backup restaurável', resultado.output)

    # ── Backup truncado (sem tabelas) ─────────────────────────────────────

    def test_reprova_backup_sem_tabelas(self):
        vazio = os.path.join(self.pasta_backup,
                             'sigere-20990101-000000-sqlite.sqlite.gz')
        fd, branco = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            conexao = sqlite3.connect(branco)
            conexao.close()  # banco criado, zero tabelas
            with open(branco, 'rb') as bruto, gzip.open(vazio, 'wb') as gz:
                gz.write(bruto.read())

            resultado = self._rodar('--arquivo', vazio)
            self.assertNotEqual(resultado.exit_code, 0)
            self.assertIn('ausentes na cópia', resultado.output)
            self.assertIn('users', resultado.output)
            self.assertIn('REPROVADA', resultado.output)
        finally:
            os.remove(branco)

    # ── Erro de operador ──────────────────────────────────────────────────

    def test_arquivo_ausente_erro_claro(self):
        resultado = self._rodar('--arquivo',
                                os.path.join(self.pasta_backup, 'nao-existe.gz'))
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('não encontrado', resultado.output)

    def test_essencial_ausente_dos_dois_lados_reprova(self):
        # `faltando` pega essencial que está na produção e sumiu da cópia;
        # sumida dos DOIS lados (backup de banco vazio/errado) só o
        # _essenciais_ausentes pega — e reprova.
        self.assertEqual(
            modulo_verificar._essenciais_ausentes(
                {'unities': 3, 'classrooms': 17}, {'unities': 3}),
            ['users', 'reservations'])
        # Todas as essenciais presentes nos dois lados: nada a reportar
        # (zero linhas é informativo, não reprova).
        vazias = {'users': 0, 'unities': 0, 'classrooms': 0, 'reservations': 0}
        self.assertEqual(
            modulo_verificar._essenciais_ausentes(vazias, dict(vazias)), [])

    def test_comparar_classifica_faltando_extras_e_desvios(self):
        producao = {'users': 5, 'reservations': 10, 'antiga': 1}
        copia = {'users': 5, 'reservations': 8, 'nova': 2}

        faltando, extras, desvios = modulo_verificar._comparar(
            producao, copia, tolerancia=0)
        self.assertEqual(faltando, ['antiga'])
        self.assertEqual(extras, ['nova'])
        self.assertEqual(desvios, [('reservations', 10, 8)])
        # Tolerância 2 absolve o desvio de 2 linhas.
        _, _, desvios = modulo_verificar._comparar(
            producao, copia, tolerancia=2)
        self.assertEqual(desvios, [])

    def test_mais_recente_local_escolhe_pelo_carimbo(self):
        # O mais novo pelo carimbo do nome vence, mesmo com mtime invertido;
        # arquivos estranhos à pasta não entram na disputa.
        pasta = tempfile.mkdtemp(prefix='sigere-recente-')
        self.addCleanup(shutil.rmtree, pasta, ignore_errors=True)
        antigo = os.path.join(pasta, 'sigere-20260101-000000-sqlite.sqlite.gz')
        recente = os.path.join(pasta, 'sigere-20261118-032000-sqlite.sqlite.gz')
        estranho = os.path.join(pasta, 'sigere-leia-me.txt')
        for caminho in (antigo, recente, estranho):
            with open(caminho, 'wb') as fh:
                fh.write(b'x')
            mais_velho = datetime.now().timestamp() - 3600
            os.utime(antigo, (mais_velho, mais_velho))

        encontrado = modulo_verificar._mais_recente_local(pasta)
        self.assertEqual(os.path.basename(encontrado),
                         'sigere-20261118-032000-sqlite.sqlite.gz')
        # Pasta inexistente → None.
        self.assertIsNone(modulo_verificar._mais_recente_local(
            os.path.join(pasta, 'vazio-que-nao-existe')))

    def test_reprova_backup_corrompido_erro_claro(self):
        # Arquivo que não é gzip: descompressão falha — e o operador recebe
        # mensagem apresentável, não traceback cru.
        corrompido = os.path.join(self.pasta_backup,
                                  'sigere-20990101-000000-sqlite.sqlite.gz')
        with open(corrompido, 'wb') as fh:
            fh.write(b'isso definitivamente nao e gzip')
        resultado = self._rodar('--arquivo', corrompido)
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('corrompido ou ilegível', resultado.output)
        self.assertNotIn('Traceback', resultado.output)

    # ── Nuvem ─────────────────────────────────────────────────────────────

    def test_verifica_a_copia_da_nuvem_com_bucket(self):
        # "Outra produção" com 2 usuários, cujo snapshot representa o objeto
        # no bucket: é a cópia da nuvem que deve ser restaurada, mesmo com um
        # backup recente disponível na pasta local.
        fd, outro_db = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        pasta_nuvem = tempfile.mkdtemp(prefix='sigere-verify-cloud-')
        try:
            class OutraConfig(Config):
                SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
                TESTING = True
                WTF_CSRF_ENABLED = False
                RATELIMIT_ENABLED = False
                SQLALCHEMY_DATABASE_URI = 'sqlite:///' + outro_db.replace('\\', '/')
            outra_app = create_app(OutraConfig)
            with outra_app.app_context():
                db.create_all()
                for indice in (1, 2):
                    professor = User(email=f'p{indice}@escola.edu',
                                     full_name=f'Professor {indice}',
                                     role='room', profile_type='employee',
                                     force_password_change=False)
                    professor.set_password('SenhaForte123')
                    db.session.add(professor)
                db.session.commit()
            resultado_backup = outra_app.test_cli_runner().invoke(
                args=['backup', '--no-upload', '--dir', pasta_nuvem])
            self.assertEqual(resultado_backup.exit_code, 0, resultado_backup.output)
            with outra_app.app_context():
                db.session.remove()
                db.engine.dispose()

            objeto = os.listdir(pasta_nuvem)[0]
            falso_cliente = mock.Mock()
            paginador = mock.Mock()
            paginador.paginate.return_value = [{
                'Contents': [{'Key': f'sigere/{objeto}',
                              'LastModified': datetime.now(timezone.utc)
                              - timedelta(minutes=5)}]}]
            falso_cliente.get_paginator.return_value = paginador
            falso_cliente.download_file.side_effect = (
                lambda bucket, chave, destino: shutil.copyfile(
                    os.path.join(pasta_nuvem, objeto), destino))

            ambiente = {'BACKUP_S3_BUCKET': 'bucket-sigere',
                        'BACKUP_S3_PREFIX': 'sigere'}
            with mock.patch.dict(os.environ, ambiente), \
                    mock.patch.object(modulo_verificar, '_criar_cliente_s3',
                                      return_value=falso_cliente):
                resultado = self._rodar()

            # A origem tem de ser a nuvem e o conteúdo conferido é o dela:
            # produção com 1 usuário contra a cópia com 2 → reprovação.
            self.assertIn('origem: nuvem', resultado.output)
            self.assertNotEqual(resultado.exit_code, 0)
            self.assertIn('produção 1, cópia 2', resultado.output)
            # O download vai para pasta temporária própria — a pasta de
            # backups retidos continua só com o snapshot original.
            self.assertEqual(len(os.listdir(self.pasta_backup)), 1)
        finally:
            shutil.rmtree(pasta_nuvem, ignore_errors=True)
            os.remove(outro_db)

    def test_falha_da_nuvem_vira_mensagem_apresentavel(self):
        ambiente = {'BACKUP_S3_BUCKET': 'bucket-sigere',
                    'BACKUP_S3_PREFIX': 'sigere'}
        falso_cliente = mock.Mock()
        falso_cliente.get_paginator.side_effect = RuntimeError('rede caiu')
        with mock.patch.dict(os.environ, ambiente), \
                mock.patch.object(modulo_verificar, '_criar_cliente_s3',
                                  return_value=falso_cliente):
            resultado = self._rodar()
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('Falha na verificação', resultado.output)
        self.assertIn('Falha ao consultar/baixar o backup na nuvem', resultado.output)
        self.assertNotIn('Traceback', resultado.output)

    def test_falha_inesperada_na_verificacao_vira_mensagem(self):
        # Bug do comando ou ambiente fora do previsto (ex.: driver ausente):
        # mensagem rotulada para o operador + código 1 — não traceback cru
        # sem rótulo.
        with mock.patch.object(modulo_verificar, '_restaurar_sqlite',
                               side_effect=ImportError('psycopg2 ausente')):
            resultado = self._rodar()
        self.assertNotEqual(resultado.exit_code, 0)
        self.assertIn('Falha inesperada na verificação', resultado.output)
        self.assertIn('psycopg2 ausente', resultado.output)

    def test_driver_psycopg2_ausente_vira_mensagem_apresentavel(self):
        # OCR (#243): driver ausente é condição de ambiente PREVISÍVEL —
        # tem de virar BackupError com instrução de instalação (mesmo
        # tratamento do psql ausente e do boto3), não "falha inesperada"
        # com traceback.
        with mock.patch.dict(sys.modules, {'psycopg2': None}):
            with self.app.app_context():
                with self.assertRaises(modulo_verificar.BackupError) as saida:
                    modulo_verificar._conectar_postgres(
                        {'host': 'localhost', 'port': '5432', 'user': 'u',
                         'password': 'p', 'sslmode': 'disable',
                         'database': 'sigere'}, 'banco_teste')
        self.assertIn('psycopg2-binary', str(saida.exception))

    def test_mais_recente_nuvem_usa_o_carimbo_do_nome(self):
        # Objeto antigo re-enviado hoje (LastModified fresco) não deve ganhar
        # do backup realmente mais novo, identificado pelo carimbo do nome —
        # o mesmo critério da retenção na nuvem.
        paginador = mock.Mock()
        paginador.paginate.return_value = [{
            'Contents': [
                {'Key': 'sigere/sigere-20260101-000000-postgres.sql.gz',
                 'LastModified': datetime.now(timezone.utc)},
                {'Key': 'sigere/sigere-20261118-000000-postgres.sql.gz',
                 'LastModified': datetime.now(timezone.utc) - timedelta(days=1)},
            ]}]
        falso_cliente = mock.Mock()
        falso_cliente.get_paginator.return_value = paginador

        chave = modulo_verificar._mais_recente_nuvem(
            {'bucket': 'bucket-sigere', 'prefixo': 'sigere'}, falso_cliente)
        self.assertEqual(chave, 'sigere/sigere-20261118-000000-postgres.sql.gz')

    def test_mais_recente_nuvem_ignora_subpastas(self):
        # Cópia em subpasta com carimbo mais novo não disputa a restauração —
        # só filhos diretos do prefixo.
        paginador = mock.Mock()
        paginador.paginate.return_value = [{
            'Contents': [
                {'Key': 'sigere/sub/sigere-20261201-000000-postgres.sql.gz',
                 'LastModified': datetime.now(timezone.utc)},
                {'Key': 'sigere/sigere-20261118-000000-postgres.sql.gz',
                 'LastModified': datetime.now(timezone.utc) - timedelta(days=1)},
            ]}]
        falso_cliente = mock.Mock()
        falso_cliente.get_paginator.return_value = paginador

        chave = modulo_verificar._mais_recente_nuvem(
            {'bucket': 'bucket-sigere', 'prefixo': 'sigere'}, falso_cliente)
        self.assertEqual(chave, 'sigere/sigere-20261118-000000-postgres.sql.gz')

    def test_tolerancia_negativa_e_rejeitada(self):
        resultado = self._rodar('--tolerancia', '-1')
        self.assertNotEqual(resultado.exit_code, 0)


if __name__ == '__main__':
    unittest.main()
