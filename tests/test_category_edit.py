"""Regressão: editar cadastro mantendo o próprio valor único.

Ao construir o formulário de edição com Form(obj=registro) — sem o kwarg
obj_id —, o atributo _obj_id ficava None e a validação de unicidade
encontrava o próprio registro, rejeitando qualquer edição com "Já existe
...". O caso relatado foi na edição de categorias de sala
(app/blueprints/admin.py::edit_category); HolidayForm e RoleForm tinham o
mesmo defeito e são cobertos aqui no nível de formulário, que é onde ele
vive.

A suíte sobe a aplicação real (create_app) com banco SQLite temporário,
seguindo o padrão de test_change_password.py.
"""
import os
import tempfile
import unittest
from datetime import date

from app import create_app
from app.config import Config
from app.extensions import db
from app.forms import HolidayForm, RoleForm
from app.models import Holiday, Permission, Role, RoomCategory, Unity, User


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


USERNAME = 'gestor.teste'
PASSWORD = 'SenhaForte123'


class CategoryEditTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(unity)
            db.session.commit()
            self.unity_id = unity.id

            self.cat = RoomCategory(name='Sala de Aula', code='sala_aula', abbr='SA')
            self.outra = RoomCategory(name='Biblioteca', code='library')
            db.session.add_all([self.cat, self.outra])
            db.session.commit()
            self.cat_id = self.cat.id

            perms = [Permission.query.filter_by(code=c).first()
                     for c in ('room:create', 'room:edit', 'room:read')]
            perms = [p for p in perms if p]
            if not perms:
                perms = [Permission(code=c, module='room', action=c.split(':')[1])
                         for c in ('room:create', 'room:edit', 'room:read')]
                db.session.add_all(perms)
                db.session.flush()
            gestor_role = Role(name='gestor-salas', label='Gestor de Salas',
                               permissions=perms)
            db.session.add(gestor_role)
            db.session.flush()

            user = User(
                username=USERNAME, email='gestor@escola.edu', full_name='Gestor Teste',
                role='room', profile_type='employee', unity_id=unity.id,
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
        response = self.client.post('/login',
                                    data={'username': USERNAME, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    # ---------- Categoria de sala (caso relatado) ----------

    def test_editar_mantendo_o_nome(self):
        """Editar a categoria sem mudar o nome não pode acusar duplicidade."""
        response = self.client.post(f'/admin/categories/{self.cat_id}/edit',
                                    data={'name': 'Sala de Aula',
                                          'totem_window': 'period',
                                          'is_active': 'y'},
                                    follow_redirects=True)
        self.assertIn('Categoria atualizada', response.get_data(as_text=True))

    def test_renomear_para_nome_de_outra_categoria(self):
        """Renomear para o nome de outra categoria continua bloqueado."""
        response = self.client.post(f'/admin/categories/{self.cat_id}/edit',
                                    data={'name': 'Biblioteca',
                                          'totem_window': 'period',
                                          'is_active': 'y'})
        self.assertIn('Já existe uma categoria com este nome',
                      response.get_data(as_text=True))

    # ---------- Mesma correção em Feriado e Papel ----------

    def test_feriado_editar_mantendo_a_data(self):
        # A validação de unicidade consulta current_unity_id(), que exige
        # contexto de requisição.
        with self.app.test_request_context():
            hol = Holiday(name='Recesso', date=date(2030, 12, 20))
            db.session.add(hol)
            db.session.commit()
            form = HolidayForm(formdata=None, obj=hol)
            self.assertTrue(form.validate(), form.errors)

    def test_papel_editar_mantendo_o_rotulo(self):
        with self.app.app_context():
            role = Role.query.filter_by(name='gestor-salas').first()
            form = RoleForm(formdata=None, obj=role)
            form.permissions.data = []
            self.assertTrue(form.validate(), form.errors)


if __name__ == '__main__':
    unittest.main()
