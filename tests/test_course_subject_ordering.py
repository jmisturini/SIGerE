"""Testes do filtro de ordenação das páginas de Cursos e Disciplinas."""
import os
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


class CourseSubjectOrderingTestCase(unittest.TestCase):
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

            # Nomes/códigos em ordens diferentes para distinguir as ordenações
            self.curso_zumba = Course(name='Zumba', code='CZ1', unity_id=self.unity.id)
            self.curso_alfa = Course(name='Alfabetização', code='CA2', unity_id=self.unity.id)
            self.curso_info = Course(name='Informática', code='CI3', unity_id=self.unity.id)
            db.session.add_all([self.curso_zumba, self.curso_alfa, self.curso_info])
            db.session.flush()

            # Zumba tem 2 disciplinas, Informática 1 e Alfabetização nenhuma
            self.disc_z1 = Subject(name='Zumba Prática', code='DZ1',
                                   course_id=self.curso_zumba.id, unity_id=self.unity.id)
            self.disc_z2 = Subject(name='Anatomia do Zumba', code='DA9',
                                   course_id=self.curso_zumba.id, unity_id=self.unity.id)
            self.disc_i1 = Subject(name='Banana da Informática', code='DB2',
                                   course_id=self.curso_info.id, unity_id=self.unity.id)
            # Disciplina sem curso (aparece por último na ordenação por curso)
            self.disc_sem = Subject(name='Estudo Livre', code='DC3', unity_id=self.unity.id)
            db.session.add_all([self.disc_z1, self.disc_z2, self.disc_i1, self.disc_sem])
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

    def _ordem_na_pagina(self, url, titulos):
        page = self.client.get(url).get_data(as_text=True)
        return [t for t in sorted(titulos, key=lambda t: page.find(t)) if page.find(t) != -1]

    # ---------- cursos ----------

    def test_cursos_padrao_nome_az(self):
        ordem = self._ordem_na_pagina('/admin/courses',
                                      ['Zumba', 'Alfabetização', 'Informática'])
        self.assertEqual(ordem, ['Alfabetização', 'Informática', 'Zumba'])

    def test_cursos_nome_za(self):
        ordem = self._ordem_na_pagina('/admin/courses?ordem=nome_desc',
                                      ['Zumba', 'Alfabetização', 'Informática'])
        self.assertEqual(ordem, ['Zumba', 'Informática', 'Alfabetização'])

    def test_cursos_por_codigo(self):
        ordem = self._ordem_na_pagina('/admin/courses?ordem=codigo',
                                      ['Zumba', 'Alfabetização', 'Informática'])
        # códigos: CA2, CI3, CZ1
        self.assertEqual(ordem, ['Alfabetização', 'Informática', 'Zumba'])

    def test_cursos_por_quantidade_de_disciplinas(self):
        ordem = self._ordem_na_pagina('/admin/courses?ordem=disciplinas',
                                      ['Zumba', 'Alfabetização', 'Informática'])
        # Zumba (2), Informática (1), Alfabetização (0)
        self.assertEqual(ordem, ['Zumba', 'Informática', 'Alfabetização'])

    def test_cursos_ordem_invalida_cai_no_padrao(self):
        ordem = self._ordem_na_pagina('/admin/courses?ordem=qualquer',
                                      ['Zumba', 'Alfabetização', 'Informática'])
        self.assertEqual(ordem, ['Alfabetização', 'Informática', 'Zumba'])

    def test_cursos_seletor_marcado_com_ordem_atual(self):
        page = self.client.get('/admin/courses?ordem=disciplinas').get_data(as_text=True)
        self.assertIn('value="disciplinas" selected', page)

    # ---------- disciplinas ----------

    def test_disciplinas_padrao_nome_az(self):
        ordem = self._ordem_na_pagina('/admin/subjects',
                                      ['Zumba Prática', 'Anatomia do Zumba',
                                       'Banana da Informática', 'Estudo Livre'])
        self.assertEqual(ordem, ['Anatomia do Zumba', 'Banana da Informática',
                                 'Estudo Livre', 'Zumba Prática'])

    def test_disciplinas_nome_za(self):
        ordem = self._ordem_na_pagina('/admin/subjects?ordem=nome_desc',
                                      ['Zumba Prática', 'Anatomia do Zumba',
                                       'Banana da Informática', 'Estudo Livre'])
        self.assertEqual(ordem, ['Zumba Prática', 'Estudo Livre',
                                 'Banana da Informática', 'Anatomia do Zumba'])

    def test_disciplinas_por_codigo(self):
        ordem = self._ordem_na_pagina('/admin/subjects?ordem=codigo',
                                      ['Zumba Prática', 'Anatomia do Zumba',
                                       'Banana da Informática', 'Estudo Livre'])
        # códigos: DA9, DB2, DC3, DZ1
        self.assertEqual(ordem, ['Anatomia do Zumba', 'Banana da Informática',
                                 'Estudo Livre', 'Zumba Prática'])

    def test_disciplinas_por_curso_sem_curso_por_ultimo(self):
        ordem = self._ordem_na_pagina('/admin/subjects?ordem=curso',
                                      ['Zumba Prática', 'Anatomia do Zumba',
                                       'Banana da Informática', 'Estudo Livre'])
        # Cursos em ordem alfabética (Informática, Zumba); sem curso por último
        self.assertEqual(ordem, ['Banana da Informática', 'Anatomia do Zumba',
                                 'Zumba Prática', 'Estudo Livre'])

    def test_disciplinas_ordem_invalida_cai_no_padrao(self):
        ordem = self._ordem_na_pagina('/admin/subjects?ordem=xyz',
                                      ['Zumba Prática', 'Anatomia do Zumba',
                                       'Banana da Informática', 'Estudo Livre'])
        self.assertEqual(ordem, ['Anatomia do Zumba', 'Banana da Informática',
                                 'Estudo Livre', 'Zumba Prática'])


if __name__ == '__main__':
    unittest.main()
