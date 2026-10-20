"""Testes do cadastro de Tipos de Curso no Painel Admin.

Catálogo que alimenta o campo "Tipo de Curso" (obrigatório) do lançamento de
Hora Extra: CRUD com permissões course_type:read/create/edit/toggle, nome
único (case-insensitive), toggle ativo/inativo e o tipo inativo saindo do
dropdown do formulário de Hora Extra.
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import CourseType, Permission, Role, Unity, User

EMAIL = 'admin@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class CourseTypesAdminTestCase(unittest.TestCase):
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

            perms = [Permission(code=f'course_type:{action}', module='course_type',
                                action=action)
                     for action in ('read', 'create', 'edit', 'toggle')]
            # O hub /admin/ exige uma permissão de PERMS_PAINEL — sem ela nem a
            # página do painel abre (o card é testado com o hub acessível).
            perms.append(Permission(code='system:dashboard', module='system',
                                    action='dashboard'))
            db.session.add_all(perms)
            role = Role(name='admin-teste', label='Admin Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(
                email=EMAIL, full_name='Admin Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
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

    def _criar(self, name='Técnico', **extra):
        return self.client.post('/admin/course-types/create',
                                data={'name': name, **extra},
                                follow_redirects=True)

    def test_listagem_e_criacao(self):
        response = self._criar('Técnico')
        self.assertIn('criado com sucesso', response.get_data(as_text=True))
        page = self.client.get('/admin/course-types').get_data(as_text=True)
        self.assertIn('Técnico', page)

    def test_nome_duplicado_recusado(self):
        self._criar('Técnico')
        # Case-insensitive: 'técnico' também é duplicado
        response = self._criar('técnico')
        self.assertIn('Já existe um tipo de curso', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(CourseType.query.count(), 1)

    def test_nome_vazio_recusado(self):
        response = self._criar('')
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(CourseType.query.count(), 0)

    def test_editar_tipo(self):
        self._criar('Técnico')
        with self.app.app_context():
            tipo_id = CourseType.query.one().id
        response = self.client.post(f'/admin/course-types/{tipo_id}/edit',
                                    data={'name': 'Aprendizagem', 'is_active': 'on'},
                                    follow_redirects=True)
        self.assertIn('atualizado com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(CourseType.query.one().name, 'Aprendizagem')

    def test_toggle_ativa_e_desativa(self):
        self._criar('Técnico', is_active='on')
        with self.app.app_context():
            tipo_id = CourseType.query.one().id
        self.client.post(f'/admin/course-types/{tipo_id}/toggle')
        with self.app.app_context():
            self.assertFalse(db.session.get(CourseType, tipo_id).is_active)
        self.client.post(f'/admin/course-types/{tipo_id}/toggle')
        with self.app.app_context():
            self.assertTrue(db.session.get(CourseType, tipo_id).is_active)

    def test_tipo_inativo_sai_do_form_de_hora_extra(self):
        self._criar('Técnico', is_active='on')
        self._criar('FIC')  # sem is_active → inativo
        from app.blueprints.payments import _course_type_choices
        with self.app.app_context():
            nomes = [nome for _, nome in _course_type_choices()]
        self.assertEqual(nomes, ['Técnico'])

    def test_sem_permissao_vira_403(self):
        with self.app.app_context():
            role = Role.query.filter_by(name='admin-teste').first()
            role.permissions = []
            db.session.commit()
        for metodo, url in (('get', '/admin/course-types'),
                            ('post', '/admin/course-types/create'),
                            ('get', '/admin/course-types/1/edit'),
                            ('post', '/admin/course-types/1/toggle')):
            resposta = getattr(self.client, metodo)(url)
            self.assertEqual(resposta.status_code, 403, url)

    def test_dashboard_exibe_card_somente_com_permissao(self):
        page = self.client.get('/admin/').get_data(as_text=True)
        self.assertIn('Tipos de Curso', page)

        with self.app.app_context():
            role = Role.query.filter_by(name='admin-teste').first()
            # remove só as permissões de tipos: o hub continua acessível
            # (system:dashboard), mas o card do template some
            role.permissions = [p for p in role.permissions
                                if not p.code.startswith('course_type')]
            db.session.commit()
        page = self.client.get('/admin/').get_data(as_text=True)
        self.assertNotIn('Acesso Negado', page)  # o hub segue acessível
        self.assertNotIn('Tipos de Curso', page)  # o card some sem a permissão


if __name__ == '__main__':
    unittest.main()
