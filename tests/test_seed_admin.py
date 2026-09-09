"""Testes do comando `flask seed-admin`.

O comando cria APENAS a conta do administrador (permissões/papéis + usuário
'admin'), solicitando a senha no terminal — sem dados de demonstração.
"""
import os
import tempfile
import unittest

from werkzeug.security import check_password_hash

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SeedAdminCommandTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_seed_admin_prompts_password_and_creates_account(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['seed-admin'],
                               input='SenhaForte123\nSenhaForte123\n')
        self.assertEqual(result.exit_code, 0)
        self.assertIn('Administrador criado com sucesso', result.output)
        self.assertNotIn('demonstra', result.output.lower())  # sem dados de demonstração
        with self.app.app_context():
            admin = db.session.query(User).filter_by(username='admin').first()
            self.assertIsNotNone(admin)
            self.assertTrue(check_password_hash(admin.password_hash, 'SenhaForte123'))
            self.assertTrue(admin.role_obj and admin.role_obj.name == 'super_admin')

    def test_seed_admin_rejects_short_password(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['seed-admin'],
                               input='curta\ncurta\nSenhaForte123\nSenhaForte123\n')
        self.assertEqual(result.exit_code, 0)
        self.assertIn('pelo menos 8 caracteres', result.output)
        with self.app.app_context():
            admin = db.session.query(User).filter_by(username='admin').first()
            self.assertTrue(check_password_hash(admin.password_hash, 'SenhaForte123'))

    def test_seed_admin_skips_when_account_exists(self):
        runner = self.app.test_cli_runner()
        primeira = runner.invoke(args=['seed-admin'], input='SenhaForte123\nSenhaForte123\n')
        self.assertEqual(primeira.exit_code, 0)
        segunda = runner.invoke(args=['seed-admin'])
        self.assertEqual(segunda.exit_code, 0)
        self.assertIn('já existe', segunda.output)
        with self.app.app_context():
            admin = db.session.query(User).filter_by(username='admin').first()
            self.assertTrue(check_password_hash(admin.password_hash, 'SenhaForte123'))


if __name__ == '__main__':
    unittest.main()
