"""Testes do fluxo de aprovação de professor (reservation:create_pending).

Quem tem a permissão reservation:create_pending — concedida por padrão ao
papel Professor — cria reservas que nascem PENDENTES, mesmo sem conflito de
sala/docente ou sobrecarga: aguardam aprovação de quem tem reservation:approve.
Quem não tem a permissão segue criando aprovadas (comportamento antigo). A
regra vale também para as repetições (única e em lote); as pendências por
conflito de docente e carga diária continuam valendo para todos.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Permission, Reservation, Role,
                        RoomCategory, Unity, User)

PROF_EMAIL = 'professor@escola.edu'
FUNC_EMAIL = 'funcionario@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class TeacherPendingCreationTestCase(unittest.TestCase):
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

            # Permissões compartilhadas (código é único no banco)
            perm_create = Permission(code='reservation:create', module='reservation',
                                     action='create')
            perm_pending = Permission(code='reservation:create_pending', module='reservation',
                                      action='create_pending')
            perm_read_own = Permission(code='reservation:read_own', module='reservation',
                                       action='read_own')
            perm_cancel_own = Permission(code='reservation:cancel_own', module='reservation',
                                         action='cancel_own')
            db.session.add_all([perm_create, perm_pending, perm_read_own, perm_cancel_own])

            # Papel Professor: cria com fluxo de aprovação (nasce pendente)
            papel_professor = Role(name='teacher', label='Professor',
                                   permissions=[perm_create, perm_pending,
                                                perm_read_own, perm_cancel_own])
            db.session.add(papel_professor)

            # Papel Assistente: cria sem fluxo de aprovação (nasce aprovada)
            papel_func = Role(name='employee', label='Assistente',
                              permissions=[perm_create, perm_read_own])
            db.session.add(papel_func)
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

            funcionario = User(
                email=FUNC_EMAIL, full_name='Funcionario Teste',
                role='viewer', profile_type='employee', unities=[self.unity],
                role_id=papel_func.id, force_password_change=False,
                is_active_user=True,
            )
            funcionario.set_password(PASSWORD)
            db.session.add(funcionario)
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
            self.teacher_id = professor.id

        self._login(PROF_EMAIL)

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
        # de usuário (o setUp já loga como professor).
        self.client.get('/logout')
        response = self.client.post('/login',
                                    data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _dia_futuro(self, dias_a_frente=1):
        """Dia futuro que não seja domingo (domingo é bloqueado)."""
        d = date.today() + timedelta(days=dias_a_frente)
        while d.weekday() == 6:
            d += timedelta(days=1)
        return d

    def _dia_posterior(self, dia):
        """Dia seguinte a `dia`, também sem domingo — calculado a partir de
        `dia` (e não de hoje) para nunca coincidir com ele: rodando num
        sábado, hoje+1 e hoje+2 caem na mesma segunda-feira."""
        d = dia + timedelta(days=1)
        while d.weekday() == 6:
            d += timedelta(days=1)
        return d

    def _payload(self, dia, start, end):
        return {
            'classroom': str(self.room_id),
            'course': str(self.course_id),
            'subject': '0', 'teacher': str(self.teacher_id),
            'title': 'Aula de teste',
            'description': '',
            'date': dia.strftime('%Y-%m-%d'),
            'start_time': start, 'end_time': end,
        }

    def _status_reserva(self, dia, start):
        inicio = datetime.strptime(start, '%H:%M').time()
        with self.app.app_context():
            reserva = Reservation.query.filter_by(
                date=dia, start_time=inicio).order_by(Reservation.id.desc()).first()
            return reserva.status if reserva else None

    def test_professor_cria_pendente(self):
        """Criador com reservation:create_pending: reserva nasce PENDENTE
        mesmo sem conflito, com aviso de aguardando aprovação."""
        dia = self._dia_futuro()
        response = self.client.post('/reservations/create',
                                    data=self._payload(dia, '09:00', '10:00'),
                                    follow_redirects=True)
        pagina = response.get_data(as_text=True)
        self.assertEqual(self._status_reserva(dia, '09:00'), 'pending')
        self.assertIn('aguardando aprovação', pagina)

    def test_funcionario_sem_permissao_cria_aprovada(self):
        """Sem reservation:create_pending, a reserva nasce aprovada como antes."""
        self._login(FUNC_EMAIL)
        dia = self._dia_futuro()
        response = self.client.post('/reservations/create',
                                    data=self._payload(dia, '09:00', '10:00'),
                                    follow_redirects=True)
        pagina = response.get_data(as_text=True)
        self.assertEqual(self._status_reserva(dia, '09:00'), 'approved')
        self.assertIn('agendada com sucesso', pagina)

    def test_professor_repeticao_unica_nasce_pendente(self):
        dia1 = self._dia_futuro()
        dia2 = self._dia_posterior(dia1)
        self.client.post('/reservations/create',
                         data=self._payload(dia1, '09:00', '10:00'),
                         follow_redirects=True)
        with self.app.app_context():
            origem = Reservation.query.filter_by(date=dia1).first()
            origem_id = origem.id

        response = self.client.post(f'/reservations/{origem_id}/repeat_schedule',
                                    data={'new_date': dia2.strftime('%Y-%m-%d'),
                                          'end_date': '', 'same_day': 'false',
                                          'skip_weekend': 'false'},
                                    follow_redirects=True)
        self.assertIn('aguardando aprovação', response.get_data(as_text=True))
        self.assertEqual(self._status_reserva(dia2, '09:00'), 'pending')

    def test_professor_repeticao_em_lote_nasce_pendente(self):
        dia1 = self._dia_futuro()
        dia2 = self._dia_posterior(dia1)
        self.client.post('/reservations/create',
                         data=self._payload(dia1, '09:00', '10:00'),
                         follow_redirects=True)
        with self.app.app_context():
            origem = Reservation.query.filter_by(date=dia1).first()
            origem_id = origem.id

        response = self.client.post(f'/reservations/{origem_id}/repeat_schedule_all',
                                    data={'start_date': dia2.strftime('%Y-%m-%d'),
                                          'end_date': dia2.strftime('%Y-%m-%d'),
                                          'same_day': 'false', 'skip_weekend': 'false'},
                                    follow_redirects=True)
        pagina = response.get_data(as_text=True)
        self.assertIn('criadas como PENDENTES', pagina)
        self.assertEqual(self._status_reserva(dia2, '09:00'), 'pending')

    def test_conflito_docente_mantem_aviso_especifico(self):
        """Conflito de horário do docente segue com a página de aviso própria
        (e a reserva pendente, como já era)."""
        dia = self._dia_futuro()
        self.client.post('/reservations/create',
                         data=self._payload(dia, '09:00', '10:00'),
                         follow_redirects=True)
        response = self.client.post('/reservations/create',
                                    data=self._payload(dia, '09:30', '10:30'),
                                    follow_redirects=True)
        pagina = response.get_data(as_text=True)
        self.assertIn('conflito de professor', pagina)
        self.assertEqual(self._status_reserva(dia, '09:30'), 'pending')

    def _reserva_aprovada(self, dia, start, end, description=None):
        """Cria como professor (nasce pendente) e aprova direto no banco,
        simulando a aprovação de quem tem reservation:approve."""
        self.client.post('/reservations/create',
                         data=self._payload(dia, start, end),
                         follow_redirects=True)
        with self.app.app_context():
            reserva = Reservation.query.filter_by(date=dia).first()
            reserva.status = 'approved'
            reserva.description = description
            db.session.commit()
            return reserva.id

    def test_professor_edita_sem_mudanca_mantem_aprovada(self):
        """Reenviar a edição sem alterar nada não devolve a reserva aprovada
        à fila — nem descrição vazia ('' no POST) vs. None (banco) conta como
        mudança."""
        dia = self._dia_futuro()
        reserva_id = self._reserva_aprovada(dia, '09:00', '10:00',
                                            description=None)
        response = self.client.post(f'/reservations/{reserva_id}/edit',
                                    data=self._payload(dia, '09:00', '10:00'),
                                    follow_redirects=True)
        pagina = response.get_data(as_text=True)
        self.assertIn('Reserva atualizada com sucesso', pagina)
        self.assertNotIn('PENDENTE', pagina)
        self.assertEqual(self._status_reserva(dia, '09:00'), 'approved')

    def test_professor_edita_mudando_dados_volta_a_pendente(self):
        """Edição que muda dados segue exigindo nova aprovação no fluxo de
        professor."""
        dia = self._dia_futuro()
        reserva_id = self._reserva_aprovada(dia, '09:00', '10:00')
        response = self.client.post(f'/reservations/{reserva_id}/edit',
                                    data=self._payload(dia, '11:00', '12:00'),
                                    follow_redirects=True)
        pagina = response.get_data(as_text=True)
        self.assertIn('aguardando nova aprovação', pagina)
        self.assertEqual(self._status_reserva(dia, '11:00'), 'pending')


if __name__ == '__main__':
    unittest.main()
