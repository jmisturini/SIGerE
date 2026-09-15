"""Testes da tela de novidades (changelog) e do versionamento da aplicação.

Cobre:
- a rota /changelog é pública e lista as versões (atual em destaque);
- a home do sistema exibe o badge "Novidades" com a versão atual;
- o rodapé das páginas traz o link da versão (via context processor).
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User
from app.version import APP_VERSION, RELEASES


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ChangelogTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            user = User(email='gestor@escola.edu', full_name='Gestor Teste',
                        role='room', profile_type='employee',
                        force_password_change=False, is_active_user=True)
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

    def test_changelog_publico_lista_versoes(self):
        response = self.client.get('/changelog')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('Novidades', page)
        # A versão atual e todo o histórico aparecem na tela
        self.assertIn(f'v{APP_VERSION}', page)
        self.assertIn('versão atual', page)
        for rel in RELEASES:
            self.assertIn(rel['titulo'], page)

    def test_home_exibe_badge_de_novidades_com_versao(self):
        self.client.post('/login', data={'email': 'gestor@escola.edu',
                                         'password': 'SenhaForte123'},
                         follow_redirects=True)
        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('Novidades', page)
        self.assertIn(f'v{APP_VERSION}', page)
        self.assertIn('/changelog', page)

    def test_rodape_exibe_versao_na_tela_de_login(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn(f'v{APP_VERSION}', page)
        self.assertIn('/changelog', page)


if __name__ == '__main__':
    unittest.main()
