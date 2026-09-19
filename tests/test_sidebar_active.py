"""Testes do destaque (classe active) do menu lateral.

A aba correspondente à página visitada deve ficar sinalizada — ex.: Unidades
não pode deixar o destaque no Painel Admin.
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, Unity, User

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SidebarActiveTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(self.unity)
            db.session.flush()

            codigos = ('unity:read', 'system:dashboard', 'user:read')
            perms = [Permission(code=c, module=c.split(':')[0], action=c.split(':')[1])
                     for c in codigos]
            db.session.add_all(perms)
            role = Role(name='gestor', label='Gestor', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(email=EMAIL, full_name='Gestor Teste', role='room',
                        profile_type='employee', unity_id=self.unity.id,
                        role_id=role.id, force_password_change=False,
                        is_active_user=True)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()

        response = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _navlink(self, page, titulo):
        """Classe do link de navegação cujo title seja `titulo`.

        O Painel Admin vive na topbar (classe topbar-painel); os demais
        itens, na sidebar (classe nav-link).
        """
        import re
        m = re.search(r'<a class="(?:nav-link|topbar-painel) ([^"]*)" title="' + titulo + '"', page)
        return m.group(1) if m else None

    def test_unidades_vive_dentro_do_painel_admin(self):
        """Sem item próprio na sidebar, Unidades destaca o Painel Admin."""
        page = self.client.get('/admin/unities').get_data(as_text=True)
        self.assertIsNone(self._navlink(page, 'Unidades'))
        self.assertEqual(self._navlink(page, 'Painel Admin'), 'active')

    def test_painel_admin_ativo_na_pagina_de_usuarios(self):
        page = self.client.get('/admin/users').get_data(as_text=True)
        self.assertEqual(self._navlink(page, 'Painel Admin'), 'active')

    def test_painel_admin_ativo_no_dashboard(self):
        page = self.client.get('/admin/').get_data(as_text=True)
        self.assertEqual(self._navlink(page, 'Painel Admin'), 'active')
        # O dashboard é o hub: card de Unidades visível para quem tem unity:read.
        self.assertIn('Unidades', page)

    def test_dashboard_acessivel_sem_system_dashboard(self):
        """Quem só tem unity:read acessa o Painel Admin (hub) e vê o card
        de Unidades — mas nada de que não tenha permissão."""
        with self.app.app_context():
            user = User.query.filter_by(email=EMAIL).first()
            user.role_obj.permissions = [Permission.query.filter_by(code='unity:read').first()]
            db.session.commit()
        self.client.get('/logout')
        self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                         follow_redirects=True)
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('Unidades', page)
        self.assertNotIn('Tokens da API', page)


if __name__ == '__main__':
    unittest.main()
