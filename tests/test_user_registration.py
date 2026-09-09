"""Testes do cadastro de professores e funcionários (admin).

Cobre as regras pedidas:
- o nome de usuário é derivado automaticamente da parte anterior ao @ do
  e-mail informado (o campo de username não é mais digitado no cadastro);
- a matrícula/ID é obrigatória e não pode se repetir entre usuários.
"""
import os
import tempfile
import unittest

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, Unity, User

USERNAME = 'gestor.teste'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class UserRegistrationTestCase(unittest.TestCase):
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

            # Papel do gestor de teste: cadastrar e editar usuários
            perms = [Permission.query.filter_by(code=c).first()
                     for c in ('user:create', 'user:edit')]
            gestor_role = Role(name='gestor-users', label='Gestor de Usuários',
                               permissions=perms)
            db.session.add(gestor_role)
            db.session.flush()

            user = User(
                username=USERNAME, email='gestor@escola.edu', full_name='Gestor Teste',
                role='room', profile_type='employee', unity_id=self.unity.id,
                role_id=gestor_role.id, force_password_change=False,
                is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
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
        response = self.client.post('/login', data={'username': USERNAME, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _payload(self, **overrides):
        with self.app.app_context():
            role_id = Role.query.filter_by(name='teacher').first().id
        payload = {
            'full_name': 'Maria Souza',
            'email': 'maria.souza@escola.edu',
            'registration': 'MAT001',
            'department': 'Informática',
            'unity_id': str(self.unity_id),
            'role_id': str(role_id),
            'password': 'SenhaForte123',
            'is_active_user': 'y',
        }
        payload.update(overrides)
        return payload

    def _get_user_by_email(self, email):
        with self.app.app_context():
            user = db.session.query(User).filter_by(email=email).first()
            return user.username if user else None

    # ---------- Nome de usuário derivado do e-mail ----------

    def test_create_teacher_derives_username_from_email(self):
        response = self.client.post('/admin/users/create-teacher',
                                    data=self._payload(), follow_redirects=True)
        self.assertIn('Professor cadastrado com sucesso', response.get_data(as_text=True))
        self.assertEqual(self._get_user_by_email('maria.souza@escola.edu'), 'maria.souza')

    def test_create_employee_derives_username_from_email(self):
        response = self.client.post('/admin/users/create-employee',
                                    data=self._payload(full_name='João Lima',
                                                       email='joao.lima@escola.edu',
                                                       registration='FUN001'),
                                    follow_redirects=True)
        self.assertIn('Funcionário cadastrado com sucesso', response.get_data(as_text=True))
        self.assertEqual(self._get_user_by_email('joao.lima@escola.edu'), 'joao.lima')

    def test_duplicate_email_prefix_rejected(self):
        self.client.post('/admin/users/create-teacher', data=self._payload())
        response = self.client.post('/admin/users/create-teacher',
                                    data=self._payload(email='maria.souza@outro.com',
                                                       registration='MAT002'),
                                    follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Este nome de usuário já está em uso.', page)
        self.assertIsNone(self._get_user_by_email('maria.souza@outro.com'))

    # ---------- Matrícula obrigatória e única ----------

    def test_registration_required(self):
        response = self.client.post('/admin/users/create-teacher',
                                    data=self._payload(registration=''),
                                    follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Informe a matrícula/ID do professor.', page)
        self.assertIsNone(self._get_user_by_email('maria.souza@escola.edu'))

    def test_registration_duplicate_rejected(self):
        self.client.post('/admin/users/create-teacher', data=self._payload())
        response = self.client.post('/admin/users/create-teacher',
                                    data=self._payload(email='outra.pessoa@escola.edu',
                                                       full_name='Outra Pessoa'),
                                    follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Esta Matrícula já está em uso.', page)
        self.assertIsNone(self._get_user_by_email('outra.pessoa@escola.edu'))

    def test_edit_requires_registration(self):
        self.client.post('/admin/users/create-teacher', data=self._payload())
        with self.app.app_context():
            user = db.session.query(User).filter_by(email='maria.souza@escola.edu').first()
            user_id = user.id
        # Editando sem matrícula (campo vazio) deve ser recusado
        response = self.client.post(f'/admin/users/{user_id}/edit',
                                    data=self._payload(registration=''),
                                    follow_redirects=True)
        self.assertIn('Informe a matrícula/ID do professor.', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
