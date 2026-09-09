"""Testes do cadastro de salas (admin).

Cobre o pedido: o nome da sala é OPCIONAL (posicionado após o número da sala
e a categoria no formulário) e, quando não informado, a sala é identificada
pelo código gerado (abreviação da categoria + número).
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Classroom, Permission, Role, RoomCategory, Unity, User

USERNAME = 'gestor.teste'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class RoomFormTestCase(unittest.TestCase):
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

            self.category = RoomCategory(name='Sala de Aula', code='sala_aula',
                                         abbr='SA', is_active=True)
            db.session.add(self.category)
            db.session.commit()
            self.category_id = self.category.id

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

    def _payload(self, **overrides):
        payload = {
            'room_number': '212',
            'category_id': str(self.category_id),
            'name': '',
            'building': '',
            'floor': '',
            'capacity': '30',
            'computer_count': '0',
            'description': '',
            'is_active': 'y',
        }
        payload.update(overrides)
        return payload

    def _room(self, code):
        with self.app.app_context():
            room = db.session.query(Classroom).filter_by(code=code).first()
            return (room.name, room.room_number) if room else None

    def test_form_field_order_and_optional_label(self):
        response = self.client.get('/admin/rooms/create')
        page = response.get_data(as_text=True)
        self.assertIn('Nome da Sala (opcional)', page)
        self.assertLess(page.index('id="room_number"'), page.index('id="category_id"'))
        self.assertLess(page.index('id="category_id"'), page.index('id="name"'))

    def test_create_without_name_uses_generated_code_as_name(self):
        response = self.client.post('/admin/rooms/create',
                                    data=self._payload(), follow_redirects=True)
        self.assertIn('Sala SA212 criada', response.get_data(as_text=True))
        self.assertEqual(self._room('SA212'), ('SA212', '212'))

    def test_create_with_name_keeps_name(self):
        response = self.client.post('/admin/rooms/create',
                                    data=self._payload(name='Sala dos Professores'),
                                    follow_redirects=True)
        self.assertIn('Sala SA212 criada', response.get_data(as_text=True))
        self.assertEqual(self._room('SA212'), ('Sala dos Professores', '212'))

    def test_edit_clearing_name_falls_back_to_code(self):
        self.client.post('/admin/rooms/create', data=self._payload(name='Sala dos Professores'))
        room_id = None
        with self.app.app_context():
            room = db.session.query(Classroom).filter_by(code='SA212').first()
            room_id = room.id
        response = self.client.post(f'/admin/rooms/{room_id}/edit',
                                    data=self._payload(name=''), follow_redirects=True)
        self.assertIn('Sala atualizada', response.get_data(as_text=True))
        self.assertEqual(self._room('SA212'), ('SA212', '212'))


if __name__ == '__main__':
    unittest.main()
