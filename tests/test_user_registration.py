"""Testes do cadastro de professores e funcionários (admin).

Cobre as regras pedidas:
- o e-mail é o identificador de login do usuário (não existe username);
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

EMAIL = 'gestor@escola.edu'
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
                email=EMAIL, full_name='Gestor Teste',
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
        response = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
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
            return db.session.query(User).filter_by(email=email).first()

    # ---------- Login pelo e-mail cadastrado ----------

    def test_create_teacher_then_login_with_email(self):
        response = self.client.post('/admin/users/create-teacher',
                                    data=self._payload(), follow_redirects=True)
        self.assertIn('Professor cadastrado com sucesso', response.get_data(as_text=True))
        self.assertIsNotNone(self._get_user_by_email('maria.souza@escola.edu'))
        # O e-mail cadastrado é o login do novo usuário (senha inicial).
        self.client.get('/logout')
        login = self.client.post('/login',
                                 data={'email': 'maria.souza@escola.edu',
                                       'password': 'SenhaForte123'},
                                 follow_redirects=True)
        self.assertIn('Bem-vindo', login.get_data(as_text=True))

    def test_create_employee_then_login_with_email(self):
        response = self.client.post('/admin/users/create-employee',
                                    data=self._payload(full_name='João Lima',
                                                       email='joao.lima@escola.edu',
                                                       registration='FUN001'),
                                    follow_redirects=True)
        self.assertIn('Funcionário cadastrado com sucesso', response.get_data(as_text=True))
        self.assertIsNotNone(self._get_user_by_email('joao.lima@escola.edu'))
        self.client.get('/logout')
        login = self.client.post('/login',
                                 data={'email': 'joao.lima@escola.edu',
                                       'password': 'SenhaForte123'},
                                 follow_redirects=True)
        self.assertIn('Bem-vindo', login.get_data(as_text=True))

    def test_login_rejects_wrong_email(self):
        self.client.get('/logout')
        login = self.client.post('/login',
                                 data={'email': 'inexistente@escola.edu',
                                       'password': PASSWORD},
                                 follow_redirects=True)
        self.assertIn('E-mail ou senha inválidos.', login.get_data(as_text=True))

    def test_duplicate_email_rejected(self):
        self.client.post('/admin/users/create-teacher', data=self._payload())
        response = self.client.post('/admin/users/create-teacher',
                                    data=self._payload(registration='MAT002'),
                                    follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Este e-mail já está cadastrado.', page)
        with self.app.app_context():
            self.assertEqual(
                db.session.query(User).filter_by(email='maria.souza@escola.edu').count(), 1)

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

    def test_edit_page_header_in_portuguese(self):
        # O cabeçalho do cartão não deve vazar o valor interno em inglês de
        # profile_type ("Editar Teacher"/"Editar Employee").
        self.client.post('/admin/users/create-teacher', data=self._payload())
        self.client.post('/admin/users/create-employee',
                         data=self._payload(email='joao.pereira@escola.edu',
                                            full_name='João Pereira', registration='FUN001',
                                            sector='Manutenção', function='Técnico'))
        with self.app.app_context():
            teacher = db.session.query(User).filter_by(email='maria.souza@escola.edu').first()
            employee = db.session.query(User).filter_by(email='joao.pereira@escola.edu').first()
            teacher_id, employee_id = teacher.id, employee.id
        teacher_page = self.client.get(f'/admin/users/{teacher_id}/edit').get_data(as_text=True)
        employee_page = self.client.get(f'/admin/users/{employee_id}/edit').get_data(as_text=True)
        self.assertIn('Editar Professor', teacher_page)
        self.assertNotIn('Editar Teacher', teacher_page)
        self.assertIn('Editar Funcionário', employee_page)
        self.assertNotIn('Editar Employee', employee_page)


if __name__ == '__main__':
    unittest.main()
