"""Testes do cadastro de professores e funcionários (admin).

Cobre as regras pedidas:
- o e-mail é o identificador de login do usuário (não existe username);
- a matrícula/ID é obrigatória e não pode se repetir entre usuários.
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
        # Na edição o seletor de perfil fica desabilitado (tipo imutável).
        seletor = re.search(r'<select[^>]*name="profile_type"[^>]*>', teacher_page).group(0)
        self.assertIn('disabled', seletor)

    # ---------- Formulário unificado: mapeamento perfil → papel legado ----------

    def test_mapeamento_papel_legado_por_perfil(self):
        # ROLE_POR_PERFIL: professor nasce com role 'room' e funcionário com
        # 'viewer' — o mapa é único (app.models) e aplica-se em qualquer URL.
        self.client.post('/admin/users/create-teacher', data=self._payload())
        self.client.post('/admin/users/create-employee',
                         data=self._payload(email='joao.lima@escola.edu',
                                            full_name='João Lima', registration='FUN002',
                                            sector='Secretaria', function='Auxiliar'))
        with self.app.app_context():
            teacher = db.session.query(User).filter_by(email='maria.souza@escola.edu').first()
            employee = db.session.query(User).filter_by(email='joao.lima@escola.edu').first()
            self.assertEqual((teacher.profile_type, teacher.role), ('teacher', 'room'))
            self.assertEqual((employee.profile_type, employee.role), ('employee', 'viewer'))

    def test_formulario_dinamico_permite_trocar_perfil(self):
        # O formulário é único: um POST feito na URL de professor com o
        # seletor trocado para "Funcionário" cadastra um funcionário (e vice-versa).
        response = self.client.post('/admin/users/create-teacher',
                                    data=self._payload(profile_type='employee',
                                                       full_name='João Lima',
                                                       email='joao.lima@escola.edu',
                                                       registration='FUN003',
                                                       department=None,
                                                       sector='Portaria',
                                                       function='Vigilante'),
                                    follow_redirects=True)
        self.assertIn('Funcionário cadastrado com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            user = db.session.query(User).filter_by(email='joao.lima@escola.edu').first()
            self.assertEqual(user.profile_type, 'employee')
            self.assertEqual(user.role, 'viewer')
            self.assertEqual(user.sector, 'Portaria')
            self.assertIsNone(user.department)

    def test_funcionario_tambem_professor(self):
        self.client.post('/admin/users/create-employee',
                         data=self._payload(email='joao.lima@escola.edu',
                                            full_name='João Lima', registration='FUN004',
                                            sector='Cozinha', function='Professor prático',
                                            is_teacher='y'))
        with self.app.app_context():
            user = db.session.query(User).filter_by(email='joao.lima@escola.edu').first()
            self.assertTrue(user.is_teacher)
            self.assertEqual(user.profile_type, 'employee')

    def test_formulario_unico_renderiza_nas_duas_urls(self):
        # As duas URLs de criação renderizam o MESMO formulário dinâmico,
        # mudando apenas o perfil pré-selecionado.
        for url, selecionado in (('/admin/users/create-teacher', 'teacher'),
                                 ('/admin/users/create-employee', 'employee')):
            page = self.client.get(url).get_data(as_text=True)
            self.assertIn('name="profile_type"', page)
            self.assertIn('campos-professor', page)
            self.assertIn('campos-funcionario', page)
            opcao = re.compile(
                r'<option[^>]*value="%s"[^>]*selected|<option[^>]*selected[^>]*value="%s"'
                % (selecionado, selecionado))
            self.assertIsNotNone(opcao.search(page), url)

    def test_entrada_unica_cadastro_usuario(self):
        # O botão "Cadastrar Usuário" abre /admin/users/create sem tipo
        # pré-selecionado: a escolha acontece no próprio formulário.
        page = self.client.get('/admin/users/create').get_data(as_text=True)
        self.assertIn('Cadastrar Novo Usuário', page)
        self.assertIn('Selecione o tipo de perfil', page)
        for tipo in ('teacher', 'employee'):
            opcao = re.compile(
                r'<option[^>]*value="%s"[^>]*selected|<option[^>]*selected[^>]*value="%s"'
                % (tipo, tipo))
            self.assertIsNone(opcao.search(page), tipo)
        # O seletor vem HABILITADO na criação (um `disabled="None"` renderizado
        # travaria a escolha do tipo no navegador).
        seletor = re.search(r'<select[^>]*name="profile_type"[^>]*>', page).group(0)
        self.assertNotIn('disabled', seletor)

    def test_entrada_unica_cadastra_professor(self):
        # A URL única serve para os dois perfis — aqui o tipo "Professor" é
        # escolhido no formulário (como o navegador envia após a escolha).
        response = self.client.post('/admin/users/create',
                                    data=self._payload(profile_type='teacher'),
                                    follow_redirects=True)
        self.assertIn('Professor cadastrado com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            user = db.session.query(User).filter_by(email='maria.souza@escola.edu').first()
            self.assertEqual(user.profile_type, 'teacher')
            self.assertEqual(user.role, 'room')

    def test_entrada_unica_exige_tipo(self):
        # Payload sem profile_type (o padrão da URL neutra): a validação pede
        # a escolha do tipo e nenhum usuário é criado.
        response = self.client.post('/admin/users/create', data=self._payload())
        self.assertIn('Selecione o tipo de perfil', response.get_data(as_text=True))
        self.assertIsNone(self._get_user_by_email('maria.souza@escola.edu'))

    def test_setor_e_funcao_aceitam_siglas_e_abreviacoes(self):
        # Valores reais como "T.I" e "Assist. Suporte em TI" têm pontos — o
        # antigo filtro "apenas alfabético" os recusava na criação e na edição.
        self.client.post('/admin/users/create',
                         data=self._payload(profile_type='employee',
                                            email='gabriel.homem@escola.edu',
                                            full_name='Gabriel Homem',
                                            registration='FUN010',
                                            sector='T.I',
                                            function='Assist. Suporte em TI'),
                         follow_redirects=True)
        with self.app.app_context():
            user = db.session.query(User).filter_by(email='gabriel.homem@escola.edu').first()
            user_id = user.id
            self.assertEqual(user.sector, 'T.I')
            self.assertEqual(user.function, 'Assist. Suporte em TI')
        # Edição mantendo os mesmos valores (antes falhava sem alterar nada)
        payload = self._payload(profile_type='employee',
                                email='gabriel.homem@escola.edu',
                                full_name='Gabriel Homem', registration='FUN010',
                                sector='T.I', function='Assist. Suporte em TI',
                                password='')
        response = self.client.post(f'/admin/users/{user_id}/edit',
                                    data=payload, follow_redirects=True)
        self.assertIn('Usuário atualizado com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            user = db.session.get(User, user_id)
            self.assertEqual((user.sector, user.function), ('T.I', 'Assist. Suporte em TI'))

    def test_edicao_nao_altera_perfil_mesmo_com_post_forjado(self):
        # O seletor de perfil vem desabilitado na edição: um POST tentando
        # trocar profile_type não pode mudar o perfil persistido.
        self.client.post('/admin/users/create-teacher', data=self._payload())
        with self.app.app_context():
            user_id = db.session.query(User).filter_by(email='maria.souza@escola.edu').first().id
        self.client.post(f'/admin/users/{user_id}/edit',
                         data=self._payload(profile_type='employee', sector='Zeladoria',
                                            function='Auxiliar'),
                         follow_redirects=True)
        with self.app.app_context():
            user = db.session.get(User, user_id)
            self.assertEqual(user.profile_type, 'teacher')
            self.assertEqual(user.role, 'room')
            self.assertIsNone(user.sector)


if __name__ == '__main__':
    unittest.main()
