"""Funcionário que também leciona nas listas de pagamento e na busca pública.

O cadastro "Também cadastrar como Professor" (is_teacher) designa o
funcionário para reservas — e ele recebe Hora Extra e Vale-Alimentação como
qualquer professor. Regressão: os filtros usavam apenas
profile_type == 'teacher' e escondiam essas contas nos formulários de
pagamento (payments.py) e na busca pública de professores (public.py) —
o cronograma já as listava (padrão união profile_type | is_teacher).
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
FUNC_PROF = 'Funcionario Professor'
PROF_PURO = 'Professor Puro'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class FuncionarioProfessorPagamentosTestCase(unittest.TestCase):
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

            codigos = ['payment:read', 'payment:create', 'meal:read', 'meal:create']
            perms = [Permission(code=c, module=c.split(':')[0], action=c.split(':')[1])
                     for c in codigos]
            db.session.add_all(perms)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            gestor = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)

            # professor puro (profile_type='teacher')
            professor = User(
                email='professor@escola.edu', full_name=PROF_PURO,
                role='room', profile_type='teacher', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            professor.set_password(PASSWORD)
            # funcionário que também leciona (o caso da regressão)
            func_prof = User(
                email='funcprof@escola.edu', full_name=FUNC_PROF,
                role='room', profile_type='employee', unities=[self.unity],
                force_password_change=False, is_active_user=True,
                is_teacher=True,
            )
            func_prof.set_password(PASSWORD)
            db.session.add_all([professor, func_prof])
            db.session.commit()
            self.func_prof_id = func_prof.id

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

    def test_hora_extra_listagem_e_formulario(self):
        listagem = self.client.get('/payments/overtime/list')
        self.assertEqual(listagem.status_code, 200)
        page = listagem.get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        self.assertIn(FUNC_PROF, page)

        formulario = self.client.get('/payments/overtime/create')
        self.assertEqual(formulario.status_code, 200)
        page = formulario.get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        self.assertIn(FUNC_PROF, page)

    def test_vale_alimentacao_lista_funcionario_professor(self):
        response = self.client.get('/payments/meal-allowance')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        self.assertIn(FUNC_PROF, page)

    def test_busca_publica_encontra_funcionario_professor(self):
        response = self.client.get('/search?type=teacher&q=Funcionario')
        self.assertEqual(response.status_code, 200)
        self.assertIn(FUNC_PROF, response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
