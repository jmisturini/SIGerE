"""Redirecionamento após cadastrar reserva.

Ao submeter o formulário de cadastro (botão "Cadastrar Reserva"), o usuário
deve ser levado aos detalhes da reserva recém-criada — não à listagem
"Minhas Reservas".
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta
from urllib.parse import urlparse

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Permission, Reservation, Role,
                        RoomCategory, Unity, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ReservaRedirecionaDetalhesTestCase(unittest.TestCase):
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

            perms = [Permission(code='reservation:create', module='reservation', action='create'),
                     Permission(code='reservation:read_own', module='reservation', action='read_own')]
            db.session.add_all(perms)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
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

            course = Course(name='Curso Teste', code='CT',
                            unity_id=self.unity.id, is_active=True)
            db.session.add(course)
            db.session.commit()
            self.unity_id = self.unity.id
            self.user_id = user.id
            self.room_id = room.id
            self.course_id = course.id

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

    def _payload(self, title='Aula de Redirecionamento'):
        # Primeiro dia futuro que não seja domingo (domingos são bloqueados).
        quando = date.today() + timedelta(days=1)
        if quando.weekday() == 6:
            quando += timedelta(days=1)
        return {
            'classroom': str(self.room_id),
            'course': str(self.course_id),
            'subject': '0', 'teacher': '0',
            'title': title,
            'description': '',
            'date': quando.strftime('%Y-%m-%d'),
            'start_time': '10:00', 'end_time': '11:00',
        }

    def test_cadastro_redireciona_para_detalhes_da_reserva(self):
        response = self.client.post('/reservations/create', data=self._payload())
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            reserva = Reservation.query.filter_by(
                title='Aula de Redirecionamento').first()
            self.assertIsNotNone(reserva)
            caminho_esperado = f'/reservations/{reserva.id}'

        self.assertEqual(urlparse(response.headers['Location']).path,
                         caminho_esperado)

        detalhes = self.client.get(caminho_esperado)
        self.assertEqual(detalhes.status_code, 200)
        pagina = detalhes.get_data(as_text=True)
        self.assertIn('Aula de Redirecionamento', pagina)
        self.assertIn('Reserva agendada com sucesso', pagina)

    def test_cadastro_limite_diario_tambem_vai_para_detalhes(self):
        """Reserva que nasce PENDENTE (professor no limite diário) segue
        para os detalhes, com os avisos de pendência no topo da página."""
        quando = date.today() + timedelta(days=1)
        if quando.weekday() == 6:
            quando += timedelta(days=1)

        with self.app.app_context():
            professor = User(
                email='professor@escola.edu', full_name='Professor Silva',
                role='room', profile_type='teacher', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            professor.set_password(PASSWORD)
            db.session.add(professor)
            db.session.flush()
            # Dois lançamentos ativos no dia levam a reserva nova ao limite
            # diário — em horários que não conflitem com a nova (10:00-11:00).
            db.session.add_all([
                Reservation(user_id=self.user_id, classroom_id=self.room_id,
                            teacher_id=professor.id, title='Aula 1',
                            date=quando, start_time=time(8, 0),
                            end_time=time(9, 0), status='approved',
                            unity_id=self.unity_id),
                Reservation(user_id=self.user_id, classroom_id=self.room_id,
                            teacher_id=professor.id, title='Aula 2',
                            date=quando, start_time=time(9, 0),
                            end_time=time(9, 50), status='approved',
                            unity_id=self.unity_id),
            ])
            db.session.commit()
            professor_id = professor.id

        response = self.client.post(
            '/reservations/create',
            data={**self._payload('Aula Pendente'), 'teacher': str(professor_id)})
        self.assertEqual(response.status_code, 302)

        with self.app.app_context():
            reserva = Reservation.query.filter_by(
                title='Aula Pendente').first()
            self.assertIsNotNone(reserva)
            self.assertEqual(reserva.status, 'pending')
            caminho_esperado = f'/reservations/{reserva.id}'

        self.assertEqual(urlparse(response.headers['Location']).path,
                         caminho_esperado)


if __name__ == '__main__':
    unittest.main()
