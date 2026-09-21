"""Testes do botão mostrar/esconder inativos nas páginas de Cursos e
Disciplinas — mesmo comportamento da listagem de usuários.

Por padrão as listagens exibem apenas os registros ativos; o botão do
cabeçalho (ou ?inativos=1) revela também os desativados, e o estado é
preservado ao reordenar.
"""
import os
import re
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Course, Permission, Role, Subject, Unity, User

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class CourseSubjectInactiveFilterTestCase(unittest.TestCase):
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

            perm = Permission(code='course:read', module='course', action='read')
            db.session.add(perm)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=[perm])
            db.session.add(role)
            db.session.flush()

            user = User(email=EMAIL, full_name='Gestor Teste', role='room',
                        profile_type='employee', unity_id=self.unity.id,
                        role_id=role.id, force_password_change=False,
                        is_active_user=True)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()

            self.curso_ativo = Course(name='Informática', code='CI1',
                                      unity_id=self.unity.id)
            self.curso_inativo = Course(name='Zumba', code='CZ2',
                                        unity_id=self.unity.id, is_active=False)
            db.session.add_all([self.curso_ativo, self.curso_inativo])
            db.session.flush()

            self.disc_ativa = Subject(name='Banana da Informática', code='DB1',
                                      course_id=self.curso_ativo.id,
                                      unity_id=self.unity.id)
            self.disc_inativa = Subject(name='Anatomia do Zumba', code='DA2',
                                        unity_id=self.unity.id, is_active=False)
            db.session.add_all([self.disc_ativa, self.disc_inativa])
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

    def _pagina(self, url):
        return self.client.get(url).get_data(as_text=True)

    # ---------- cursos ----------

    def test_cursos_ocultam_inativos_por_padrao(self):
        page = self._pagina('/admin/courses')
        self.assertIn('Informática', page)
        self.assertNotIn('Zumba', page)
        self.assertIn('Mostrar inativos', page)
        self.assertNotIn('Esconder inativos', page)

    def test_cursos_exibem_inativos_com_parametro(self):
        page = self._pagina('/admin/courses?inativos=1')
        self.assertIn('Informática', page)
        self.assertIn('Zumba', page)
        self.assertIn('Esconder inativos', page)

    def test_cursos_alternar_preserva_a_ordenacao(self):
        # O botão de alternar mantém a ordenação escolhida na URL — o href
        # só troca o valor de inativos (a ordem dos parâmetros é do url_for).
        href = re.search(r'href="(/admin/courses\?[^"]+)"',
                         self._pagina('/admin/courses?inativos=1&ordem=nome_desc')).group(1)
        self.assertIn('inativos=0', href)
        self.assertIn('ordem=nome_desc', href)
        href = re.search(r'href="(/admin/courses\?[^"]+)"',
                         self._pagina('/admin/courses?ordem=nome_desc')).group(1)
        self.assertIn('inativos=1', href)
        self.assertIn('ordem=nome_desc', href)

    def test_cursos_formulario_de_ordem_preserva_estado(self):
        page = self._pagina('/admin/courses?inativos=1')
        self.assertIn('name="inativos" value="1"', page)
        page = self._pagina('/admin/courses')
        self.assertIn('name="inativos" value="0"', page)

    def test_cursos_ordenacao_com_inativos_visiveis(self):
        page = self._pagina('/admin/courses?inativos=1&ordem=nome')
        corpo = page[page.find('<tbody>'):]
        self.assertLess(corpo.find('Informática'), corpo.find('Zumba'))

    # ---------- disciplinas ----------

    def test_disciplinas_ocultam_inativas_por_padrao(self):
        page = self._pagina('/admin/subjects')
        self.assertIn('Banana da Informática', page)
        self.assertNotIn('Anatomia do Zumba', page)
        self.assertIn('Mostrar inativos', page)
        self.assertNotIn('Esconder inativos', page)

    def test_disciplinas_exibem_inativas_com_parametro(self):
        page = self._pagina('/admin/subjects?inativos=1')
        self.assertIn('Banana da Informática', page)
        self.assertIn('Anatomia do Zumba', page)
        self.assertIn('Esconder inativos', page)

    def test_disciplinas_formulario_de_ordem_preserva_estado(self):
        page = self._pagina('/admin/subjects?inativos=1')
        self.assertIn('name="inativos" value="1"', page)
        page = self._pagina('/admin/subjects')
        self.assertIn('name="inativos" value="0"', page)

    def test_disciplinas_ordenacao_com_inativas_visiveis(self):
        page = self._pagina('/admin/subjects?inativos=1&ordem=nome')
        corpo = page[page.find('<tbody>'):]
        self.assertLess(corpo.find('Anatomia do Zumba'), corpo.find('Banana da Informática'))


if __name__ == '__main__':
    unittest.main()
