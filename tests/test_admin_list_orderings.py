"""Testes do filtro de ordenação das listagens administrativas
(usuários, salas, categorias de sala e papéis)."""
import os
import tempfile
import unittest
from datetime import date

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Role, RoomCategory, Unity, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class AdminListOrderingsTestCase(unittest.TestCase):
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

            codigos = ('user:read', 'room:read', 'role:read')
            perms = [Permission(code=c, module=c.split(':')[0], action=c.split(':')[1])
                     for c in codigos]
            db.session.add_all(perms)
            role_gestor = Role(name='gestor', label='Gestor', permissions=perms)
            role_zulu = Role(name='zulu', label='Papel Z')
            role_alfa = Role(name='alfa', label='Papel A')
            db.session.add_all([role_gestor, role_zulu, role_alfa])
            db.session.flush()

            gestor = User(email=EMAIL, full_name='Gestor Teste', role='room',
                          profile_type='employee', unity_id=self.unity.id,
                          role_id=role_gestor.id, registration='500',
                          force_password_change=False, is_active_user=True)
            gestor.set_password(PASSWORD)
            usuario_zulu = User(email='zulu@escola.edu', full_name='Zulu', role='admin',
                                profile_type='employee', unity_id=self.unity.id,
                                role_id=role_alfa.id, registration='700',
                                force_password_change=False, is_active_user=True)
            usuario_zulu.set_password(PASSWORD)
            ativo = User(email='ativo@escola.edu', full_name='Ativo Silva', role='room',
                         profile_type='employee', unity_id=self.unity.id,
                         role_id=role_zulu.id, registration='600',
                         force_password_change=False, is_active_user=True)
            ativo.set_password(PASSWORD)
            inativo = User(email='inativo@escola.edu', full_name='Inativo Costa', role='room',
                           profile_type='employee', unity_id=self.unity.id,
                           role_id=role_zulu.id, force_password_change=False,
                           is_active_user=False)
            inativo.set_password(PASSWORD)
            db.session.add_all([gestor, usuario_zulu, ativo, inativo])
            db.session.flush()

            # Salas: código, nome e capacidade em ordens diferentes
            category = RoomCategory(name='Sala de Aula', code='sala_aula', abbr='SA')
            db.session.add(category)
            db.session.flush()
            self.sala_a = Classroom(name='Auditório', code='S1', capacity=10,
                                    building='Prédio B', floor='2',
                                    unity_id=self.unity.id, category_id=category.id)
            self.sala_z = Classroom(name='Zumba Hall', code='S2', capacity=100,
                                    building='Prédio A', floor='1',
                                    unity_id=self.unity.id, category_id=category.id)
            db.session.add_all([self.sala_a, self.sala_z])
            db.session.flush()

            # Categorias com nomes invertidos aos códigos
            self.cat_zumba = RoomCategory(name='Zumba', code='cat_zumba', abbr='ZB')
            self.cat_alfa = RoomCategory(name='Alfabeto', code='cat_alfa', abbr='AL')
            db.session.add_all([self.cat_zumba, self.cat_alfa])
            db.session.commit()

            self.ids = {'sala_a': self.sala_a.id, 'sala_z': self.sala_z.id}

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
        # considera apenas o corpo da tabela (o topbar repete o nome do
        # usuário logado antes dela)
        corpo = page[page.find('<tbody>'):]
        return [t for t in sorted(titulos, key=lambda t: corpo.find(t)) if corpo.find(t) != -1]

    # ---------- usuários ----------

    def test_usuarios_padrao_por_papel_depois_nome(self):
        # papéis em ordem alfabética (alfa, gestor, zulu); dentro do papel, nome
        ordem = self._ordem_na_pagina('/admin/users',
                                      ['Zulu', 'Gestor Teste', 'Ativo Silva'])
        self.assertEqual(ordem, ['Zulu', 'Ativo Silva', 'Gestor Teste'])

    def test_usuarios_por_nome(self):
        ordem = self._ordem_na_pagina('/admin/users?ordem=nome&inativos=1',
                                      ['Gestor Teste', 'Ativo Silva', 'Inativo Costa', 'Zulu'])
        self.assertEqual(ordem, ['Ativo Silva', 'Gestor Teste', 'Inativo Costa', 'Zulu'])

    def test_usuarios_por_nome_desc(self):
        ordem = self._ordem_na_pagina('/admin/users?ordem=nome_desc&inativos=1',
                                      ['Gestor Teste', 'Ativo Silva', 'Inativo Costa', 'Zulu'])
        self.assertEqual(ordem, ['Zulu', 'Inativo Costa', 'Gestor Teste', 'Ativo Silva'])

    def test_usuarios_por_matricula_vazia_por_ultimo(self):
        with self.app.app_context():
            sem_matricula = db.session.query(User).filter_by(full_name='Zulu').first()
            sem_matricula.registration = None
            db.session.commit()
        ordem = self._ordem_na_pagina('/admin/users?ordem=matricula&inativos=1',
                                      ['Zulu', 'Ativo Silva', 'Inativo Costa', 'Gestor Teste'])
        # matrículas 500, 600 e a vazia (Zulu) por último
        self.assertEqual(ordem, ['Gestor Teste', 'Ativo Silva', 'Inativo Costa', 'Zulu'])

    def test_usuarios_por_status_ativas_primeiro(self):
        ordem = self._ordem_na_pagina('/admin/users?ordem=status&inativos=1',
                                      ['Gestor Teste', 'Ativo Silva', 'Inativo Costa', 'Zulu'])
        self.assertNotEqual(ordem[0], 'Inativo Costa')
        self.assertEqual(ordem[-1], 'Inativo Costa')

    # ---------- salas ----------

    def test_salas_padrao_por_codigo(self):
        ordem = self._ordem_na_pagina('/admin/rooms', ['Auditório', 'Zumba Hall'])
        self.assertEqual(ordem, ['Auditório', 'Zumba Hall'])

    def test_salas_por_nome(self):
        ordem = self._ordem_na_pagina('/admin/rooms?ordem=nome', ['Auditório', 'Zumba Hall'])
        self.assertEqual(ordem, ['Auditório', 'Zumba Hall'])

    def test_salas_por_nome_desc(self):
        ordem = self._ordem_na_pagina('/admin/rooms?ordem=nome_desc', ['Auditório', 'Zumba Hall'])
        self.assertEqual(ordem, ['Zumba Hall', 'Auditório'])

    def test_salas_por_capacidade(self):
        ordem = self._ordem_na_pagina('/admin/rooms?ordem=capacidade', ['Auditório', 'Zumba Hall'])
        self.assertEqual(ordem, ['Zumba Hall', 'Auditório'])

    def test_salas_por_predio(self):
        ordem = self._ordem_na_pagina('/admin/rooms?ordem=predio', ['Auditório', 'Zumba Hall'])
        # Prédio A (Zumba Hall) antes do Prédio B (Auditório)
        self.assertEqual(ordem, ['Zumba Hall', 'Auditório'])

    # ---------- categorias ----------

    def test_categorias_padrao_nome_az(self):
        ordem = self._ordem_na_pagina('/admin/categories', ['Zumba', 'Alfabeto'])
        self.assertEqual(ordem, ['Alfabeto', 'Zumba'])

    def test_categorias_nome_za(self):
        ordem = self._ordem_na_pagina('/admin/categories?ordem=nome_desc',
                                      ['Zumba', 'Alfabeto'])
        self.assertEqual(ordem, ['Zumba', 'Alfabeto'])

    # ---------- papéis ----------

    def test_papeis_padrao_nome_az(self):
        ordem = self._ordem_na_pagina('/admin/roles', ['Papel Z', 'Papel A'])
        self.assertEqual(ordem, ['Papel A', 'Papel Z'])

    def test_papeis_nome_za(self):
        ordem = self._ordem_na_pagina('/admin/roles?ordem=nome_desc',
                                      ['Papel Z', 'Papel A'])
        self.assertEqual(ordem, ['Papel Z', 'Papel A'])


if __name__ == '__main__':
    unittest.main()
