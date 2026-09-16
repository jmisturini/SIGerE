"""Testes do retorno às listagens após ações (ativar/desativar, excluir etc.).

Antes, toda ação inline redirecionava para a listagem "limpa": quem estava
na página 3 (ou com filtros aplicados) voltava para o topo da lista. Agora
o redirect preserva a query string de origem (referrer validado por host)
e rola até a linha afetada via âncora (#user-<id>).
"""
import os
import tempfile
import unittest

from app import create_app
from app.commands import _seed_permissions
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


class RedirectBackTestCase(unittest.TestCase):
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
            db.session.commit()
            self.unity_id = self.unity.id
            _seed_permissions()
            db.session.commit()

            codes = ('user:read', 'user:toggle', 'user:create')
            perms = [Permission.query.filter_by(code=c).first() for c in codes]
            role = Role(name='gestor-users', label='Gestor de Usuários',
                        permissions=[p for p in perms if p])
            db.session.add(role)
            db.session.flush()

            gestor = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unity_id=self.unity.id,
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)

            # 30 usuários para encher duas páginas (25 por página)
            for i in range(30):
                u = User(
                    email=f'prof{i:02d}@escola.edu', full_name=f'Professor {i:02d}',
                    role='viewer', profile_type='teacher', unity_id=self.unity.id,
                    force_password_change=False, is_active_user=True,
                )
                u.set_password(PASSWORD)
                db.session.add(u)
            db.session.commit()

            self.alvo_id = User.query.filter_by(email='prof07@escola.edu').first().id

        self._login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self):
        response = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    # ---------- toggle de usuário preserva página e filtros ----------

    def test_toggle_user_volta_para_pagina_e_filtros_de_origem(self):
        referrer = 'http://localhost/admin/users?name=prof&type=teacher&page=2'
        response = self.client.post(f'/admin/users/{self.alvo_id}/toggle',
                                    headers={'Referer': referrer})
        location = response.headers.get('Location', '')
        self.assertIn('/admin/users?name=prof&type=teacher&page=2', location)
        self.assertIn(f'#user-{self.alvo_id}', location)

    def test_toggle_user_sem_referrer_cai_na_listagem(self):
        response = self.client.post(f'/admin/users/{self.alvo_id}/toggle')
        self.assertEqual('/admin/users', response.headers.get('Location'))

    def test_toggle_user_com_referrer_externo_cai_na_listagem(self):
        # Referrer de outra origem não é seguido (open redirect)
        response = self.client.post(f'/admin/users/{self.alvo_id}/toggle',
                                    headers={'Referer': 'http://malicioso.com/admin/users?page=5'})
        self.assertEqual('/admin/users', response.headers.get('Location'))

    # ---------- criação volta para a listagem filtrada de origem ----------

    def test_create_user_preserva_filtros_do_formulario(self):
        payload = {
            'full_name': 'Maria Souza', 'email': 'maria.souza@escola.edu',
            'registration': 'MAT001', 'department': 'Gastronomia',
            'unity_id': '', 'role_id': '', 'password': 'SenhaForte123',
            'is_active_user': 'y', 'extra_roles': [],
        }
        with self.app.app_context():
            payload['unity_id'] = str(self.unity_id)
            payload['role_id'] = str(Role.query.filter_by(name='teacher').first().id)

        # O form (sem action) posta para a própria URL com a query de origem
        response = self.client.post('/admin/users/create-teacher?page=2&type=teacher',
                                    data=payload)
        location = response.headers.get('Location', '')
        self.assertIn('/admin/users?', location)
        self.assertIn('page=2', location)
        self.assertIn('type=teacher', location)

    # ---------- âncoras nas linhas ----------

    def test_linhas_da_listagem_tem_ancoras(self):
        page = self.client.get('/admin/users').get_data(as_text=True)
        self.assertIn('id="user-', page)

    def test_paginacao_preserva_filtros_nos_links(self):
        page = self.client.get('/admin/users?name=prof&type=teacher').get_data(as_text=True)
        # O macro de paginação reconstrói os links mantendo name/type
        self.assertIn('name=prof&amp;type=teacher', page)
