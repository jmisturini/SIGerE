"""Testes da validação do título/assunto da reserva.

Títulos reais trazem números, ordinais e pontuação ("2º Concurso de
Integração", "Reunião de pais 1º semestre") — o antigo filtro "apenas
alfabético" os recusava. O filtro permissivo continua recusando símbolos
sem uso legítimo (ex.: <script>).
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role,
                        RoomCategory, Unity, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ReservationTitleTestCase(unittest.TestCase):
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

            perms = [Permission(code='reservation:create', module='reservation', action='create')]
            db.session.add_all(perms)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(
                email=EMAIL, full_name='Gestor Teste',
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
            db.session.commit()
            self.room_id = room.id

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

    def _data_proxima(self):
        # Primeiro dia futuro que não seja domingo (domingos são bloqueados).
        quando = date.today() + timedelta(days=1)
        if quando.weekday() == 6:
            quando += timedelta(days=1)
        return quando

    def _payload(self, title):
        return {
            'classroom': str(self.room_id),
            'course': '0', 'subject': '0', 'teacher': '0',
            'title': title,
            'description': '',
            'date': self._data_proxima().strftime('%Y-%m-%d'),
            'start_time': '10:00', 'end_time': '11:00',
        }

    def _reservas_titulo(self, titulo):
        with self.app.app_context():
            return [r.title for r in Reservation.query.filter_by(title=titulo).all()]

    def test_titulo_aceita_ordinal_e_numeros(self):
        response = self.client.post('/reservations/create',
                                    data=self._payload('2º Concurso de Integração'),
                                    follow_redirects=True)
        self.assertIn('Reserva agendada com sucesso', response.get_data(as_text=True))
        self.assertEqual(self._reservas_titulo('2º Concurso de Integração'),
                         ['2º Concurso de Integração'])

    def test_titulo_aceita_1a_ordinal_feminino(self):
        response = self.client.post('/reservations/create',
                                    data=self._payload('1ª Reunião de pais'),
                                    follow_redirects=True)
        self.assertIn('Reserva agendada com sucesso', response.get_data(as_text=True))

    def test_titulo_ainda_recusa_simbolos_sem_uso(self):
        response = self.client.post('/reservations/create',
                                    data=self._payload('<script>alert(1)</script>'),
                                    follow_redirects=True)
        self.assertIn('contém caracteres não permitidos', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Reservation.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
