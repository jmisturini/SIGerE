"""Testes das reservas passadas como registro histórico.

Cobre o comportamento pedido: reserva com data anterior a hoje serve como
registro e não pode ser alterada — os botões Repetir/Cancelar/Editar/Excluir
não aparecem no detalhe, e as rotas recusam cancelamento e exclusão mesmo de
administradores (a edição já era bloqueada).
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role, RoomCategory,
                        Unity, User)

USERNAME = 'admin.teste'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ReservationsPastTestCase(unittest.TestCase):
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

            codes = ('reservation:read_all', 'reservation:read_own', 'reservation:create',
                     'reservation:edit_all', 'reservation:delete_all',
                     'reservation:cancel_own', 'reservation:cancel_all',
                     'reservation:approve')
            perms = [Permission(code=code, module='reservation', action=code.split(':')[1])
                     for code in codes]
            db.session.add_all(perms)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(
                username=USERNAME, email='gestor@escola.edu', full_name='Gestor Teste',
                role='room', profile_type='employee', unity_id=self.unity.id,
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()

            room = Classroom(name='Sala 1', code='S1', capacity=30,
                             unity_id=self.unity.id, category_id=category.id)
            db.session.add(room)
            db.session.flush()

            ontem = date.today() - timedelta(days=1)
            amanha = date.today() + timedelta(days=1)
            self.past_id = self._create_reservation(user, room, 'Reserva Passada', ontem)
            self.future_id = self._create_reservation(user, room, 'Reserva Futura', amanha)

        self._login()

    def _create_reservation(self, user, room, title, when):
        reservation = Reservation(
            user_id=user.id, classroom_id=room.id, unity_id=self.unity.id,
            title=title, date=when, start_time=time(8, 0),
            end_time=time(9, 0), status='approved',
        )
        db.session.add(reservation)
        db.session.commit()
        return reservation.id

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

    def _reservation_status(self, reservation_id):
        with self.app.app_context():
            reservation = db.session.get(Reservation, reservation_id)
            db.session.refresh(reservation)
            return reservation.status

    def test_detail_past_hides_action_buttons(self):
        response = self.client.get(f'/reservations/{self.past_id}')
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('registro histórico (somente leitura)', page)
        self.assertNotIn('> Repetir', page)
        self.assertNotIn('Cancelar Reserva', page)
        self.assertNotIn('> Editar', page)
        self.assertNotIn('> Excluir', page)

    def test_detail_future_shows_action_buttons(self):
        response = self.client.get(f'/reservations/{self.future_id}')
        page = response.get_data(as_text=True)
        self.assertIn('> Repetir', page)
        self.assertIn('Cancelar Reserva', page)
        self.assertIn('> Editar', page)
        self.assertIn('> Excluir', page)

    def test_cancel_past_blocked_even_for_admin(self):
        response = self.client.post(f'/reservations/{self.past_id}/cancel',
                                    follow_redirects=True)
        self.assertIn('Não é possível cancelar uma reserva passada',
                      response.get_data(as_text=True))
        self.assertEqual(self._reservation_status(self.past_id), 'approved')

    def test_delete_past_blocked(self):
        response = self.client.post(f'/reservations/{self.past_id}/delete',
                                    follow_redirects=True)
        self.assertIn('Reservas passadas servem como registro e não podem ser excluídas',
                      response.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Reservation, self.past_id))

    def test_delete_future_allowed(self):
        response = self.client.post(f'/reservations/{self.future_id}/delete',
                                    follow_redirects=True)
        self.assertIn('Reserva excluída permanentemente', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(db.session.get(Reservation, self.future_id))

    def test_edit_past_still_blocked(self):
        response = self.client.get(f'/reservations/{self.past_id}/edit',
                                   follow_redirects=True)
        self.assertIn('Reservas passadas não podem ser editadas',
                      response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
