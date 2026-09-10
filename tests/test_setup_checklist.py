"""Testes do checklist de configuração inicial do painel.

No login do super-admin, o painel exibe um checklist com os passos de
implantação (unidade, categorias, sala, professor, funcionário, curso e
disciplina, feriados). Cada passo confere dados reais do banco e some
sozinho quando tudo está cadastrado — gestores comuns não o veem.
"""
import os
import tempfile
import unittest
from datetime import date

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Holiday, Permission, Role,
                        RoomCategory, Subject, Unity, User)

USERNAME = 'super.teste'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SetupChecklistTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            curinga = Permission(code='*', module='system', action='all')
            db.session.add(curinga)
            db.session.flush()
            role = Role(name='super_teste', label='Super Teste', permissions=[curinga])
            db.session.add(role)
            db.session.flush()

            user = User(
                username=USERNAME, email='super@escola.edu', full_name='Super Teste',
                role='admin', profile_type='employee', role_id=role.id,
                force_password_change=False, is_active_user=True,
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

    def test_checklist_shows_all_steps_pending_on_empty_system(self):
        page = self.client.get('/admin/').get_data(as_text=True)
        self.assertIn('Configuração inicial', page)
        self.assertIn('0 de 7 concluídos', page)
        for passo in ('Cadastrar Unidade', 'Cadastrar Categorias de Sala',
                      'Cadastrar Sala', 'Cadastrar Professor',
                      'Cadastrar Funcionário', 'Cadastrar Curso e Disciplina',
                      'Importar os feriados'):
            self.assertIn(passo, page)
        # Nenhum passo concluído: sem riscado
        self.assertNotIn('text-decoration-line-through', page)

    def test_checklist_marks_completed_steps(self):
        with self.app.app_context():
            unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(unity)
            db.session.flush()
            category = RoomCategory(name='Sala de Aula', code='sala')
            db.session.add(category)
            db.session.flush()
            db.session.add(Classroom(name='Sala 1', code='S1', capacity=30,
                                     unity_id=unity.id, category_id=category.id))
            db.session.commit()

        page = self.client.get('/admin/').get_data(as_text=True)
        self.assertIn('3 de 7 concluídos', page)
        self.assertIn('text-decoration-line-through', page)
        # Os 4 passos restantes seguem com botão de cadastro
        self.assertIn('Cadastrar Professor', page)
        self.assertIn('Importar os feriados', page)

    def test_checklist_hidden_when_setup_complete(self):
        with self.app.app_context():
            unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(unity)
            db.session.flush()
            category = RoomCategory(name='Sala de Aula', code='sala')
            db.session.add(category)
            db.session.flush()
            db.session.add(Classroom(name='Sala 1', code='S1', capacity=30,
                                     unity_id=unity.id, category_id=category.id))
            teacher = User(username='prof.x', email='p@x.edu', full_name='Prof X',
                           role='viewer', profile_type='teacher', unity_id=unity.id)
            teacher.set_password('SenhaForte123')
            employee = User(username='func.x', email='f@x.edu', full_name='Func X',
                            role='viewer', profile_type='employee', unity_id=unity.id)
            employee.set_password('SenhaForte123')
            db.session.add_all([teacher, employee])
            db.session.add(Course(name='Curso X', code='CX', unity_id=unity.id))
            db.session.add(Subject(name='Disciplina X', code='DX', unity_id=unity.id))
            db.session.add(Holiday(name='Feriado X', date=date(2026, 12, 25),
                                   unity_id=unity.id))
            db.session.commit()

        page = self.client.get('/admin/').get_data(as_text=True)
        self.assertNotIn('Configuração inicial', page)  # completo: card some

    def test_checklist_hidden_for_regular_manager(self):
        with self.app.app_context():
            perm = Permission.query.filter_by(code='system:dashboard').first()
            if perm is None:
                perm = Permission(code='system:dashboard', module='system',
                                  action='dashboard')
                db.session.add(perm)
                db.session.flush()
            role = Role(name='gestor-comum', label='Gestor Comum', permissions=[perm])
            db.session.add(role)
            db.session.flush()
            user = User(username='gestor.comum', email='g@escola.edu',
                        full_name='Gestor Comum', role='room',
                        profile_type='employee', role_id=role.id,
                        force_password_change=False, is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.commit()

        self.client.get('/logout')
        self.client.post('/login', data={'username': 'gestor.comum',
                                         'password': 'SenhaForte123'},
                         follow_redirects=True)
        page = self.client.get('/admin/').get_data(as_text=True)
        self.assertNotIn('Configuração inicial', page)


if __name__ == '__main__':
    unittest.main()
