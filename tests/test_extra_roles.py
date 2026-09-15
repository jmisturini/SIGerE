"""Testes dos papéis adicionais (add-on) por usuário.

A permissão efetiva do usuário é a união do papel principal com os papéis
adicionais (user_roles): ex. Professor + Módulo Cozinha para professores de
gastronomia, sem duplicar o papel de Professor. Cobre a união no modelo, a
persistência no cadastro/edição de usuários e a remoção do papel extra.
"""
import os
import re
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


class ExtraRolesTestCase(unittest.TestCase):
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

            perms = [Permission.query.filter_by(code=c).first()
                     for c in ('user:create', 'user:edit')]
            gestor_role = Role(name='gestor-users', label='Gestor de Usuários',
                               permissions=perms)
            db.session.add(gestor_role)
            db.session.flush()

            user = User(
                email='gestor@escola.edu', full_name='Gestor Teste',
                role='room', profile_type='employee', unity_id=self.unity.id,
                role_id=gestor_role.id, force_password_change=False,
                is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)

            self.teacher_role_id = Role.query.filter_by(name='teacher').first().id
            self.kitchen_role_id = Role.query.filter_by(name='kitchen').first().id
            db.session.commit()

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

    def _payload(self, **overrides):
        with self.app.app_context():
            role_id = Role.query.filter_by(name='teacher').first().id
            kitchen_id = Role.query.filter_by(name='kitchen').first().id
        payload = {
            'full_name': 'Maria Souza',
            'email': 'maria.souza@escola.edu',
            'registration': 'MAT001',
            'department': 'Gastronomia',
            'unity_id': str(self.unity_id),
            'role_id': str(role_id),
            'extra_roles': [str(kitchen_id)],
            'password': 'SenhaForte123',
            'is_active_user': 'y',
        }
        payload.update(overrides)
        return payload

    def _codes(self, email):
        with self.app.app_context():
            user = db.session.query(User).filter_by(email=email).first()
            return {p.code for p in user.role_obj.permissions}, \
                   {r.name for r in user.extra_roles}

    def _kitchen_codes(self):
        with self.app.app_context():
            kitchen = Role.query.filter_by(name='kitchen').first()
            return {p.code for p in kitchen.permissions}

    # ---------- União no modelo ----------

    def test_uniao_papel_principal_com_adicional(self):
        """Professor + Módulo Cozinha: permissões efetivas = união dos dois."""
        with self.app.app_context():
            teacher = Role.query.filter_by(name='teacher').first()
            kitchen = Role.query.filter_by(name='kitchen').first()
            user = User(email='gastro@escola.edu',
                        full_name='Prof Gastronomia', role='room',
                        profile_type='teacher', role_id=teacher.id,
                        extra_roles=[kitchen], is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.commit()
            user_id = user.id

            efetivas = db.session.get(User, user_id).permissions
            self.assertTrue({'kitchen:read', 'kitchen:sheet_create',
                             'kitchen:shopping_export'} <= efetivas)
            self.assertTrue({'course:read', 'reservation:create',
                             'reservation:read_own'} <= efetivas)

    def test_sem_adicional_permissoes_so_do_principal(self):
        """Professor sem papel adicional não ganha nada da cozinha."""
        with self.app.app_context():
            teacher = Role.query.filter_by(name='teacher').first()
            user = User(email='regular@escola.edu',
                        full_name='Prof Regular', role='room',
                        profile_type='teacher', role_id=teacher.id,
                        is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.commit()
            user_id = user.id

            efetivas = db.session.get(User, user_id).permissions
            self.assertNotIn('kitchen:read', efetivas)
            self.assertIn('course:read', efetivas)

    def test_usuario_sem_papel_nao_tem_permissoes(self):
        with self.app.app_context():
            user = User(email='sempapel@escola.edu',
                        full_name='Sem Papel', role='viewer',
                        profile_type='employee', is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.commit()
            self.assertEqual(db.session.get(User, user.id).permissions, set())

    # ---------- Persistência nas telas de usuário ----------

    def test_cadastro_professor_com_modulo_cozinha(self):
        response = self.client.post('/admin/users/create-teacher',
                                    data=self._payload(), follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Professor cadastrado com sucesso', page)

        principais, extras = self._codes('maria.souza@escola.edu')
        self.assertEqual(extras, {'kitchen'})
        self.assertIn('course:read', principais)
        self.assertNotIn('kitchen:read', principais)

    def test_edicao_pre_seleciona_papel_adicional(self):
        """GET da edição renderiza o papel adicional como selecionado."""
        self.client.post('/admin/users/create-teacher', data=self._payload())
        with self.app.app_context():
            user = db.session.query(User).filter_by(email='maria.souza@escola.edu').first()
            user_id = user.id

        response = self.client.get(f'/admin/users/{user_id}/edit')
        page = response.get_data(as_text=True)
        opcao = re.compile(
            r'<option[^>]*(value="%s"[^>]*selected|selected[^>]*value="%s")'
            % (self.kitchen_role_id, self.kitchen_role_id))
        self.assertIsNotNone(opcao.search(page))

    def test_edicao_remove_papel_adicional(self):
        self.client.post('/admin/users/create-teacher', data=self._payload())
        with self.app.app_context():
            user = db.session.query(User).filter_by(email='maria.souza@escola.edu').first()
            user_id = user.id

        # Mesmo payload sem extra_roles: a edição deve limpar o papel adicional
        payload = self._payload(email='maria.souza@escola.edu', password='')
        payload.pop('extra_roles')
        response = self.client.post(f'/admin/users/{user_id}/edit',
                                    data=payload, follow_redirects=True)
        self.assertIn('Usuário atualizado com sucesso', response.get_data(as_text=True))

        with self.app.app_context():
            user = db.session.get(User, user_id)
            self.assertEqual([r.name for r in user.extra_roles], [])
