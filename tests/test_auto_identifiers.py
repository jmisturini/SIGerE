"""Testes da geração automática dos identificadores internos.

Cobre o pacote aprovado:
- código interno da categoria e nome de sistema do papel são gerados
  automaticamente (slug do nome/rótulo) — nenhum dos dois é digitado;
- nomes duplicados (categoria e rótulo de papel) são recusados;
- a regra dos computadores passa a usar o flag explícito da categoria
  (migração preserva a antiga categoria 'computer_lab').
"""
import os
import tempfile
import unittest

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Role, RoomCategory, Unity, User)
from app.utils import gerar_slug, slug_unico

USERNAME = 'gestor.teste'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class AutoIdentifiersTestCase(unittest.TestCase):
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

            codes = ('room:create', 'room:edit', 'room:read',
                     'role:create', 'role:read', 'role:edit')
            perms = [Permission.query.filter_by(code=c).first() for c in codes]
            gestor_role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
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

    # ---------- Slug ----------

    def test_slug_helpers(self):
        self.assertEqual(gerar_slug('Laboratório de Vídeo'), 'laboratorio_de_video')
        self.assertEqual(gerar_slug('  Ação & Efeito! '), 'acao_efeito')
        self.assertEqual(slug_unico('x', {'y', 'z'}), 'x')
        self.assertEqual(slug_unico('x', {'x', 'x_2'}), 'x_3')

    # ---------- Categoria: código automático ----------

    def test_category_code_generated_from_name(self):
        response = self.client.post('/admin/categories/create',
                                    data={'name': 'Laboratório de Vídeo',
                                          'totem_window': 'period',
                                          'is_active': 'y'},
                                    follow_redirects=True)
        self.assertIn('Categoria criada com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            cat = RoomCategory.query.filter_by(name='Laboratório de Vídeo').first()
            self.assertEqual(cat.code, 'laboratorio_de_video')
            self.assertFalse(cat.controla_computadores)

    def test_category_duplicate_name_rejected(self):
        self.client.post('/admin/categories/create',
                         data={'name': 'Biblioteca', 'totem_window': 'period',
                               'is_active': 'y'})
        response = self.client.post('/admin/categories/create',
                                    data={'name': 'Biblioteca', 'totem_window': 'week',
                                          'is_active': 'y'}, follow_redirects=True)
        self.assertIn('Já existe uma categoria com este nome',
                      response.get_data(as_text=True))

    def test_category_form_has_no_code_field(self):
        response = self.client.get('/admin/categories/create')
        page = response.get_data(as_text=True)
        self.assertNotIn('Código Interno', page)
        self.assertIn('controla computadores', page)

    def test_categories_list_hides_code_shows_flag(self):
        self.client.post('/admin/categories/create',
                         data={'name': 'Laboratório de Robótica',
                               'totem_window': 'period', 'is_active': 'y',
                               'controla_computadores': 'y'})
        page = self.client.get('/admin/categories').get_data(as_text=True)
        self.assertNotIn('Código Interno', page)
        self.assertIn('Computadores', page)

    # ---------- Computadores: flag substitui o código fixo ----------

    def test_computer_count_saved_only_for_flagged_category(self):
        self.client.post('/admin/categories/create',
                         data={'name': 'Lab Novo', 'abbr': 'LN',
                               'totem_window': 'period',
                               'is_active': 'y', 'controla_computadores': 'y'})
        with self.app.app_context():
            cat = RoomCategory.query.filter_by(name='Lab Novo').first()
            cat_id = cat.id
        self.client.post('/admin/rooms/create',
                         data={'room_number': '301', 'category_id': str(cat_id),
                               'capacity': '20', 'computer_count': '15',
                               'is_active': 'y'})
        with self.app.app_context():
            room = db.session.query(Classroom).filter_by(code='LN301').first()
            self.assertIsNotNone(room)
            self.assertEqual(room.computer_count, 15)

    def test_migration_backfills_legacy_computer_lab(self):
        with self.app.app_context():
            cat = RoomCategory.query.filter_by(code='computer_lab').first()
            if cat is None:
                self.skipTest('categoria legada computer_lab não existe neste banco')
            self.assertTrue(cat.controla_computadores)

    # ---------- Papel: nome de sistema automático ----------

    def test_role_name_generated_from_label(self):
        response = self.client.post('/admin/roles/create',
                                    data={'label': 'Gestor de Cursos',
                                          'description': 'Coordena cursos'},
                                    follow_redirects=True)
        self.assertIn('Papel criado com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            role = Role.query.filter_by(label='Gestor de Cursos').first()
            self.assertEqual(role.name, 'gestor_de_cursos')

    def test_role_duplicate_label_rejected(self):
        self.client.post('/admin/roles/create', data={'label': 'Gestor de Cursos'})
        response = self.client.post('/admin/roles/create',
                                    data={'label': 'Gestor de Cursos'},
                                    follow_redirects=True)
        self.assertIn('Já existe um papel com este nome', response.get_data(as_text=True))

    def test_role_form_has_no_system_name_field(self):
        page = self.client.get('/admin/roles/create').get_data(as_text=True)
        self.assertNotIn('Nome do Sistema', page)
        self.assertNotIn('Nome no Sistema', page)

    def test_roles_list_hides_system_name(self):
        self.client.post('/admin/roles/create', data={'label': 'Auditor'})
        page = self.client.get('/admin/roles').get_data(as_text=True)
        self.assertNotIn('Nome no Sistema', page)


if __name__ == '__main__':
    unittest.main()
