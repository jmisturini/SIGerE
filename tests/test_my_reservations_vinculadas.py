"""Testes de Minhas Reservas com reservas vinculadas (professor designado).

Além das reservas criadas pelo usuário, a listagem passa a mostrar as reservas
em que ele é o professor designado (teacher_id) — badge "Designada a você" na
nova coluna Origem, sem duplicar quando ele é criador e professor da mesma
reserva. O designado ganha acesso de LEITURA aos detalhes (e à série), mas
não pode editar nem cancelar reservas criadas por terceiros.
"""
import os
import tempfile
import unittest
from datetime import date, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Permission, Reservation, Role,
                        RoomCategory, Unity, User)

GESTOR_EMAIL = 'gestor@escola.edu'
PROF_EMAIL = 'professor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class MyReservationsVinculadasTestCase(unittest.TestCase):
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

            perm_create = Permission(code='reservation:create', module='reservation',
                                     action='create')
            perm_read_own = Permission(code='reservation:read_own', module='reservation',
                                       action='read_own')
            perm_cancel_own = Permission(code='reservation:cancel_own', module='reservation',
                                         action='cancel_own')
            db.session.add_all([perm_create, perm_read_own, perm_cancel_own])
            db.session.flush()

            # Gestor: cria reservas para professores, sem fluxo de aprovação
            papel_gestor = Role(name='gestor-teste', label='Gestor Teste',
                                permissions=[perm_create, perm_read_own])
            db.session.add(papel_gestor)
            # Professor: lê as próprias e cancela as próprias (não as de terceiros)
            papel_professor = Role(name='teacher', label='Professor',
                                   permissions=[perm_create, perm_read_own,
                                                perm_cancel_own])
            db.session.add(papel_professor)
            db.session.flush()

            gestor = User(
                email=GESTOR_EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=papel_gestor.id, force_password_change=False,
                is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)
            db.session.flush()

            professor = User(
                email=PROF_EMAIL, full_name='Professor Silva',
                role='room', profile_type='teacher', unities=[self.unity],
                role_id=papel_professor.id, force_password_change=False,
                is_active_user=True,
            )
            professor.set_password(PASSWORD)
            db.session.add(professor)
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
            self.room_id = room.id
            self.course_id = course.id
            self.professor_id = professor.id

        self._login(GESTOR_EMAIL)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email):
        # /login ignora o formulário com sessão ativa: desloga para trocar
        # de usuário (o setUp já loga como gestor).
        self.client.get('/logout')
        response = self.client.post('/login',
                                    data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _dia_futuro(self, dias_a_frente=1):
        d = date.today() + timedelta(days=dias_a_frente)
        while d.weekday() == 6:
            d += timedelta(days=1)
        return d

    def _payload(self, dia, titulo, start='09:00', end='10:00'):
        return {
            'classroom': str(self.room_id),
            'course': str(self.course_id),
            'subject': '0', 'teacher': str(self.professor_id),
            'title': titulo, 'description': '',
            'date': dia.strftime('%Y-%m-%d'),
            'start_time': start, 'end_time': end,
        }

    def _criar_como_gestor(self, dia, titulo):
        """Gestor cria reserva designando o professor; devolve o id."""
        response = self.client.post('/reservations/create',
                                    data=self._payload(dia, titulo),
                                    follow_redirects=True)
        self.assertIn('agendada com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            reserva = Reservation.query.filter_by(title=titulo).first()
            return reserva.id

    def test_reserva_designada_aparece_na_listagem(self):
        """Reserva criada pelo gestor designando o professor aparece em Minhas
        Reservas dele com o badge 'Designada a você'."""
        dia = self._dia_futuro()
        self._criar_como_gestor(dia, 'Aula Designada')

        self._login(PROF_EMAIL)
        response = self.client.get('/reservations/my')
        pagina = response.get_data(as_text=True)
        self.assertIn('Aula Designada', pagina)
        self.assertIn('Designada a você', pagina)
        self.assertNotIn('Criada por você', pagina)

    def test_criador_e_professor_nao_duplica(self):
        """Reserva criada pelo próprio professor (ele como docente) aparece
        uma única vez, com badge 'Criada por você'."""
        dia = self._dia_futuro()
        self._login(PROF_EMAIL)
        self.client.post('/reservations/create',
                         data=self._payload(dia, 'Aula do Próprio'),
                         follow_redirects=True)
        response = self.client.get('/reservations/my')
        pagina = response.get_data(as_text=True)
        self.assertEqual(pagina.count('Aula do Próprio'), 1)
        self.assertIn('Criada por você', pagina)

    def test_listagem_mistura_criadas_e_designadas(self):
        dia1, dia2 = self._dia_futuro(1), self._dia_futuro(2)
        self._criar_como_gestor(dia1, 'Designada Um')
        self._criar_como_gestor(dia2, 'Designada Dois')

        self._login(PROF_EMAIL)
        self.client.post('/reservations/create',
                         data=self._payload(dia1, 'Minha Propria',
                                            start='11:00', end='12:00'),
                         follow_redirects=True)
        response = self.client.get('/reservations/my')
        pagina = response.get_data(as_text=True)
        self.assertIn('Designada Um', pagina)
        self.assertIn('Designada Dois', pagina)
        self.assertIn('Minha Propria', pagina)
        self.assertIn('Criada por você', pagina)
        self.assertIn('Designada a você', pagina)

    def test_filtro_de_status_atinge_designadas(self):
        dia = self._dia_futuro()
        self._criar_como_gestor(dia, 'Aprovada Filtro')

        self._login(PROF_EMAIL)
        response = self.client.get('/reservations/my?status=approved')
        self.assertIn('Aprovada Filtro', response.get_data(as_text=True))
        response = self.client.get('/reservations/my?status=pending')
        self.assertNotIn('Aprovada Filtro', response.get_data(as_text=True))

    def test_designado_visualiza_detalhes(self):
        dia = self._dia_futuro()
        reserva_id = self._criar_como_gestor(dia, 'Aula com Detalhe')

        self._login(PROF_EMAIL)
        response = self.client.get(f'/reservations/{reserva_id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Aula com Detalhe', response.get_data(as_text=True))

    def test_designado_nao_cancela_reserva_de_terceiro(self):
        dia = self._dia_futuro()
        reserva_id = self._criar_como_gestor(dia, 'Aula Alheia')

        self._login(PROF_EMAIL)
        response = self.client.post(f'/reservations/{reserva_id}/cancel')
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            reserva = db.session.get(Reservation, reserva_id)
            self.assertEqual(reserva.status, 'approved')

    def test_designado_nao_edita_reserva_de_terceiro(self):
        dia = self._dia_futuro()
        reserva_id = self._criar_como_gestor(dia, 'Aula Alheia Edit')

        self._login(PROF_EMAIL)
        response = self.client.post(f'/reservations/{reserva_id}/edit',
                                    data=self._payload(dia, 'Tentativa de Edição'))
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            reserva = db.session.get(Reservation, reserva_id)
            self.assertEqual(reserva.title, 'Aula Alheia Edit')


if __name__ == '__main__':
    unittest.main()
