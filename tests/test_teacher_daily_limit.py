"""Testes da regra de carga docente (limite diário de reservas do professor).

Mais de 2 reservas ativas (aprovadas/pendentes) do mesmo docente no mesmo dia:
a reserva nasce/atualiza como PENDENTE e os membros dos grupos selecionados
especificamente para o aviso de sobrecarga (config.overload_groups) recebem
uma Notification imediata (evento 'teacher_daily_limit'). Sem seleção ou sem
configuração, ninguém recebe — a pendência independe do aviso. Reservas
canceladas não contam; o limite vale por dia. Repetições (única e em lote)
também nascem pendentes na sobrecarga. A notificação é idempotente: editar a
reserva não duplica avisos.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Notification, NotificationGroup,
                        Permission, Reservation, Role, RoomCategory, Unity,
                        UnityNotificationConfig, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class TeacherDailyLimitTestCase(unittest.TestCase):
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

            gestor = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)
            db.session.flush()

            professor = User(
                email='professor@escola.edu', full_name='Professor Silva',
                role='room', profile_type='teacher', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            professor.set_password(PASSWORD)
            db.session.add(professor)
            db.session.flush()

            coordenador = User(
                email='coordenacao@escola.edu', full_name='Coordenação Geral',
                role='room', profile_type='employee', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            coordenador.set_password(PASSWORD)
            db.session.add(coordenador)
            db.session.flush()

            diretor = User(
                email='diretor@escola.edu', full_name='Direção Teste',
                role='room', profile_type='employee', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            diretor.set_password(PASSWORD)
            db.session.add(diretor)
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
            db.session.flush()

            grupo = NotificationGroup(name='Coordenação', unity_id=self.unity.id,
                                      members=[coordenador])
            grupo_fora = NotificationGroup(name='Somente Próximas', unity_id=self.unity.id,
                                           members=[diretor])
            db.session.add_all([grupo, grupo_fora])
            # Seleção dedicada: só 'grupo' recebe o aviso de sobrecarga;
            # 'grupo_fora' fica restrito aos avisos de reserva próxima.
            db.session.add(UnityNotificationConfig(
                unity_id=self.unity.id, is_enabled=True,
                groups=[grupo_fora], overload_groups=[grupo]))
            db.session.commit()
            self.room_id = room.id
            self.course_id = course.id
            self.teacher_id = professor.id
            self.unity_id = self.unity.id

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

    def _dias_futuros(self, n):
        """Primeiros n dias futuros que não sejam domingo (domingo é bloqueado)."""
        dias = []
        d = date.today() + timedelta(days=1)
        while len(dias) < n:
            if d.weekday() != 6:
                dias.append(d)
            d += timedelta(days=1)
        return dias

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

    def _criar(self, dia, start, end):
        """Cria uma reserva pelo formulário e devolve (resposta, status, id)."""
        response = self.client.post('/reservations/create',
                                    data=self._payload(dia, start, end),
                                    follow_redirects=True)
        inicio = datetime.strptime(start, '%H:%M').time()
        with self.app.app_context():
            reserva = Reservation.query.filter_by(
                date=dia, start_time=inicio).order_by(Reservation.id.desc()).first()
            status = reserva.status if reserva else None
            reserva_id = reserva.id if reserva else None
        return response, status, reserva_id

    def _avisos(self, reserva_id):
        with self.app.app_context():
            return Notification.query.filter_by(
                event_type='teacher_daily_limit',
                reservation_id=reserva_id).all()

    def test_terceira_reserva_do_dia_fica_pendente_e_notifica(self):
        dia = self._dias_futuros(1)[0]
        _, status1, _ = self._criar(dia, '09:00', '10:00')
        _, status2, _ = self._criar(dia, '10:00', '11:00')
        self.assertEqual((status1, status2), ('approved', 'approved'))

        response, status3, reserva_id = self._criar(dia, '11:00', '12:00')
        self.assertEqual(status3, 'pending')
        self.assertIn('PENDENTE', response.get_data(as_text=True))

        avisos = self._avisos(reserva_id)
        self.assertEqual(len(avisos), 1)  # grupo tem um membro (Coordenação)
        aviso = avisos[0]
        self.assertIn('Professor Silva', aviso.body)
        self.assertIn('3 reservas', aviso.body)
        self.assertIn(dia.strftime('%d/%m/%Y'), aviso.body)
        self.assertTrue(aviso.url.startswith('/calendar/'))

    def test_segunda_reserva_do_dia_aprovada_sem_notificacao(self):
        dia = self._dias_futuros(1)[0]
        _, status1, id1 = self._criar(dia, '09:00', '10:00')
        _, status2, id2 = self._criar(dia, '10:00', '11:00')
        self.assertEqual((status1, status2), ('approved', 'approved'))
        self.assertEqual(self._avisos(id1), [])
        self.assertEqual(self._avisos(id2), [])

    def test_limite_vale_por_dia(self):
        dia1, dia2 = self._dias_futuros(2)
        self._criar(dia1, '09:00', '10:00')
        self._criar(dia1, '10:00', '11:00')
        # Terceira reserva do professor, mas em outro dia: nasce aprovada.
        _, status3, id3 = self._criar(dia2, '09:00', '10:00')
        self.assertEqual(status3, 'approved')
        self.assertEqual(self._avisos(id3), [])

    def test_reserva_cancelada_nao_conta_no_limite(self):
        dia = self._dias_futuros(1)[0]
        _, _, id1 = self._criar(dia, '09:00', '10:00')
        self._criar(dia, '10:00', '11:00')
        with self.app.app_context():
            reserva = db.session.get(Reservation, id1)
            reserva.status = 'cancelled'
            db.session.commit()
        # Com a primeira cancelada, restam 2 ativas: a terceira é aprovada.
        _, status3, id3 = self._criar(dia, '11:00', '12:00')
        self.assertEqual(status3, 'approved')
        self.assertEqual(self._avisos(id3), [])

    def test_selecao_dedicada_de_grupos(self):
        """Só o grupo com a seleção de sobrecarga recebe; o grupo restrito aos
        avisos de reserva próxima não é avisado."""
        dia = self._dias_futuros(1)[0]
        self._criar(dia, '09:00', '10:00')
        self._criar(dia, '10:00', '11:00')
        _, status3, reserva_id = self._criar(dia, '11:00', '12:00')
        self.assertEqual(status3, 'pending')
        with self.app.app_context():
            avisos = Notification.query.filter_by(
                event_type='teacher_daily_limit',
                reservation_id=reserva_id).all()
            destinatarios = sorted(n.user.full_name for n in avisos)
        self.assertEqual(destinatarios, ['Coordenação Geral'])

    def test_sem_selecao_ninguem_recebe(self):
        dia = self._dias_futuros(1)[0]
        self._criar(dia, '09:00', '10:00')
        self._criar(dia, '10:00', '11:00')
        with self.app.app_context():
            config = UnityNotificationConfig.query.filter_by(
                unity_id=self.unity_id).first()
            config.overload_groups = []
            db.session.commit()
        _, status3, reserva_id = self._criar(dia, '11:00', '12:00')
        # A regra pende a reserva mesmo sem destinatários.
        self.assertEqual(status3, 'pending')
        self.assertEqual(self._avisos(reserva_id), [])

    def test_sem_configuracao_ninguem_recebe(self):
        dia = self._dias_futuros(1)[0]
        self._criar(dia, '09:00', '10:00')
        self._criar(dia, '10:00', '11:00')
        with self.app.app_context():
            db.session.query(UnityNotificationConfig).delete()
            db.session.commit()
        _, status3, reserva_id = self._criar(dia, '11:00', '12:00')
        self.assertEqual(status3, 'pending')
        self.assertEqual(self._avisos(reserva_id), [])

    def test_edicao_nao_duplica_notificacao(self):
        dia = self._dias_futuros(1)[0]
        self._criar(dia, '09:00', '10:00')
        self._criar(dia, '10:00', '11:00')
        _, _, reserva_id = self._criar(dia, '11:00', '12:00')
        self.assertEqual(len(self._avisos(reserva_id)), 1)

        response = self.client.post(f'/reservations/{reserva_id}/edit',
                                    data=self._payload(dia, '11:00', '12:00'),
                                    follow_redirects=True)
        self.assertIn('Reserva atualizada', response.get_data(as_text=True))
        self.assertEqual(len(self._avisos(reserva_id)), 1)

    def _preencher_dia(self, dia):
        """Duas reservas aprovadas do professor no dia (07:00–09:00), deixando
        a janela 09:00–10:00 livre para a repetição estourar o limite."""
        self._criar(dia, '07:00', '08:00')
        self._criar(dia, '08:00', '09:00')

    def test_repeticao_unica_com_sobrecarga_fica_pendente(self):
        dia1, dia2 = self._dias_futuros(2)
        _, status_a, id_a = self._criar(dia1, '09:00', '10:00')
        self.assertEqual(status_a, 'approved')
        self._preencher_dia(dia2)

        response = self.client.post(f'/reservations/{id_a}/repeat_schedule',
                                    data={'new_date': dia2.strftime('%Y-%m-%d'),
                                          'end_date': '', 'same_day': 'false',
                                          'skip_weekend': 'false'},
                                    follow_redirects=True)
        self.assertIn('PENDENTE', response.get_data(as_text=True))
        inicio = datetime.strptime('09:00', '%H:%M').time()
        with self.app.app_context():
            repetida = Reservation.query.filter_by(
                date=dia2, start_time=inicio).first()
            self.assertIsNotNone(repetida)
            self.assertEqual(repetida.status, 'pending')
            self.assertEqual(len(self._avisos(repetida.id)), 1)

    def test_repeticao_em_lote_com_sobrecarga_fica_pendente(self):
        dia1, dia2 = self._dias_futuros(2)
        _, status_a, id_a = self._criar(dia1, '09:00', '10:00')
        self.assertEqual(status_a, 'approved')
        self._preencher_dia(dia2)

        response = self.client.post(f'/reservations/{id_a}/repeat_schedule_all',
                                    data={'start_date': dia2.strftime('%Y-%m-%d'),
                                          'end_date': dia2.strftime('%Y-%m-%d'),
                                          'same_day': 'false', 'skip_weekend': 'false'},
                                    follow_redirects=True)
        self.assertIn('PENDENTES', response.get_data(as_text=True))
        inicio = datetime.strptime('09:00', '%H:%M').time()
        with self.app.app_context():
            repetidas = Reservation.query.filter_by(
                date=dia2, start_time=inicio).all()
            self.assertEqual(len(repetidas), 1)
            self.assertEqual(repetidas[0].status, 'pending')
            self.assertEqual(len(self._avisos(repetidas[0].id)), 1)


if __name__ == '__main__':
    unittest.main()
