"""Testes da área de unidade ativa no topbar.

- O nome completo da unidade ativa aparece à esquerda do topbar;
- O botão "Trocar" (dropdown de unidades) só aparece para quem tem
  permissão de alternar unidade ('*' ou 'unity:switch');
- A troca pela dropdown altera a unidade ativa da sessão.
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, Unity, User

ADMIN_EMAIL = 'admin@escola.edu'
COMUM_EMAIL = 'comum@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class UnityAreaTopbarTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.unity_alfa = Unity(name='Unidade Alfa', code='UA')
            self.unity_beta = Unity(name='Unidade Beta', code='UB')
            db.session.add_all([self.unity_alfa, self.unity_beta])
            db.session.flush()

            permissao_total = Permission(code='*', module='system', action='all')
            db.session.add(permissao_total)
            role_admin = Role(name='super', label='Super', permissions=[permissao_total])
            role_comum = Role(name='comum', label='Comum')
            db.session.add_all([role_admin, role_comum])
            db.session.flush()

            self.admin = User(email=ADMIN_EMAIL, full_name='Admin Global', role='room',
                              profile_type='employee', role_id=role_admin.id,
                              force_password_change=False, is_active_user=True)
            self.comum = User(email=COMUM_EMAIL, full_name='Comum Teste', role='room',
                              profile_type='employee', unity_id=self.unity_alfa.id,
                              role_id=role_comum.id, force_password_change=False,
                              is_active_user=True)
            for u in (self.admin, self.comum):
                u.set_password(PASSWORD)
            db.session.add_all([self.admin, self.comum])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email):
        response = self.client.post('/login', data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_admin_ve_unidade_e_botao_trocar(self):
        self._login(ADMIN_EMAIL)
        page = self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn('unity-area', page)
        self.assertIn('Unidade Alfa', page)     # nome completo, sem truncar
        self.assertIn('Trocar', page)
        self.assertIn('Unidade Beta', page)     # ambas as unidades na dropdown

    def test_comum_ve_unidade_mas_nao_o_botao_trocar(self):
        self._login(COMUM_EMAIL)
        page = self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn('Unidade Alfa', page)     # unidade fixa do usuário
        self.assertNotIn('>Trocar<', page)
        self.assertNotIn('Unidade Beta', page)  # sem seletor, sem listar outras

    def test_troca_de_unidade_pela_dropdown(self):
        self._login(ADMIN_EMAIL)
        with self.app.app_context():
            beta_id = db.session.query(Unity).filter_by(code='UB').first().id
        response = self.client.post('/unity/switch', data={'unity_id': beta_id},
                                    follow_redirects=True)
        # as aspas viram entidades HTML na renderização do flash
        self.assertIn('Unidade ativa alterada para', response.get_data(as_text=True))
        page = self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn('unity-area', page)
        self.assertIn('Unidade Beta', page)


if __name__ == '__main__':
    unittest.main()
