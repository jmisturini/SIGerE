"""Testes do comando `flask verify-restore` (restaurar e conferir o backup).

Cobre o caminho SQLite (o mesmo do CI, sem rede nem servidor externo):
- restauração do snapshot mais recente da pasta com estrutura e linhas batendo;
- reprovação com desvio de linhas acima da tolerância (e aprovação com ela);
- reprovação com backup truncado (sem tabelas);
- erro claro quando o arquivo indicado não existe.

O caminho PostgreSQL segue o mesmo fluxo com psql/psycopg2 e é exercitado
pelos testes de interpretação de URI do módulo de backup.
"""
import gzip
import os
import sqlite3
import tempfile
import unittest

from app import create_app
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


if __name__ == '__main__':
    unittest.main()
