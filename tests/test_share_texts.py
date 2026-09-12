"""Testes do compartilhamento de reserva por e-mail/WhatsApp.

Cobre a montagem das mensagens amigáveis (app/services/share.py) e a
presença do botão/modal "Compartilhar" na página de detalhe da reserva.
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta
from types import SimpleNamespace

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role, RoomCategory,
                        Unity, User)
from app.services.share import (build_reservation_share_texts,
                                build_email_subject, format_reservation_date)

USERNAME = 'gestor.teste'
PASSWORD = 'SenhaForte123'


def _stub_reservation(**overrides):
    """Reserva fake para testar o gerador de textos sem banco de dados."""
    reservation = SimpleNamespace(
        title='Aula de Programação',
        date=date(2026, 9, 11),  # sexta-feira
        start_time=time(14, 0), end_time=time(16, 0),
        status='approved',
        description='Aula prática de Python.',
        user=SimpleNamespace(full_name='Maria Souza'),
        classroom=SimpleNamespace(code='L101', name='Lab de Informática'),
        unity=SimpleNamespace(name='São José'),
        course=SimpleNamespace(name='Análise e Desenvolvimento de Sistemas'),
        subject=SimpleNamespace(name='Programação Web'),
        teacher=SimpleNamespace(full_name='João da Silva'),
    )
    for key, value in overrides.items():
        setattr(reservation, key, value)
    return reservation


class ShareTextsTestCase(unittest.TestCase):
    def test_email_completo(self):
        texts = build_reservation_share_texts(_stub_reservation())
        body = texts['email']['body']
        self.assertIn('Segue os detalhes da reserva de sala', body)
        self.assertIn('Sala: L101 - Lab de Informática', body)
        self.assertIn('Curso: Análise e Desenvolvimento de Sistemas', body)
        self.assertIn('Disciplina: Programação Web', body)
        self.assertIn('Professor: João da Silva', body)
        self.assertIn('Data e hora: sexta-feira, 11/09/2026, das 14:00 às 16:00', body)
        self.assertIn('Descrição/Finalidade: Aula prática de Python.', body)
        self.assertIn('SIGerE', body)
        # Conteúdo enxuto: título, unidade, situação e solicitante ficam fora
        self.assertNotIn('Título:', body)
        self.assertNotIn('Unidade:', body)
        self.assertNotIn('Situação:', body)
        self.assertNotIn('Solicitada por:', body)
        self.assertNotIn('None', body)

    def test_assunto_do_email(self):
        subject = build_email_subject(_stub_reservation())
        self.assertEqual(subject, 'Reserva de sala: Aula de Programação — 11/09/2026 14:00')

    def test_whatsapp_usa_formatacao_do_canal(self):
        texts = build_reservation_share_texts(_stub_reservation())
        text = texts['whatsapp']['text']
        self.assertIn('📅 *Reserva de sala*', text)
        self.assertIn('*Sala:* L101 - Lab de Informática', text)
        self.assertIn('*Curso:* Análise e Desenvolvimento de Sistemas', text)
        self.assertIn('*Disciplina:* Programação Web', text)
        self.assertIn('*Professor:* João da Silva', text)
        self.assertIn('*Data e hora:* sexta-feira, 11/09/2026, das 14:00 às 16:00', text)
        self.assertIn('📝 Aula prática de Python.', text)
        self.assertNotIn('*Título:*', text)
        self.assertNotIn('*Situação:*', text)
        self.assertNotIn('None', text)

    def test_campos_vazios_ficam_fora_da_mensagem(self):
        stub = _stub_reservation(course=None, subject=None, teacher=None,
                                 description=None)
        texts = build_reservation_share_texts(stub)
        self.assertNotIn('Curso:', texts['email']['body'])
        self.assertNotIn('Disciplina:', texts['email']['body'])
        self.assertNotIn('Professor:', texts['email']['body'])
        self.assertNotIn('Descrição/Finalidade:', texts['email']['body'])
        self.assertNotIn('*Curso:*', texts['whatsapp']['text'])

    def test_formato_da_data_por_extenso(self):
        self.assertEqual(format_reservation_date(date(2026, 9, 11)),
                         'sexta-feira, 11/09/2026')
        self.assertEqual(format_reservation_date(date(2026, 9, 13)),
                         'domingo, 13/09/2026')


class ShareDetailPageTestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ShareDetailPageTestCase(unittest.TestCase):
    """O botão/modal de compartilhar aparece no detalhe de reservas ativas
    (aprovadas e pendentes) e fica ausente em passadas e canceladas — não faz
    sentido compartilhar registro histórico ou reserva que foi cancelada."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        ShareDetailPageTestConfig.SQLALCHEMY_DATABASE_URI = \
            'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(ShareDetailPageTestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.unity = Unity(name='Unidade Alpha', code='UC')
            db.session.add(self.unity)
            db.session.flush()

            perm = Permission(code='reservation:read_all', module='reservation',
                              action='read_all')
            db.session.add(perm)
            role = Role(name='leitor-teste', label='Leitor Teste', permissions=[perm])
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

            room = Classroom(name='Sala Alpha', code='SC',
                             unity_id=self.unity.id, category_id=category.id)
            db.session.add(room)
            db.session.flush()

            self.future_id = self._create_reservation(user, room, 'Aula de Teste',
                                                      date.today() + timedelta(days=1))
            self.past_id = self._create_reservation(user, room, 'Aula Passada',
                                                    date.today() - timedelta(days=1))
            self.cancelled_id = self._create_reservation(user, room, 'Aula Cancelada',
                                                         date.today() + timedelta(days=2),
                                                         status='cancelled')

        response = self.client.post('/login', data={'username': USERNAME,
                                                    'password': PASSWORD},
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

    def _create_reservation(self, user, room, title, when, status='approved'):
        reservation = Reservation(
            user_id=user.id, classroom_id=room.id, unity_id=self.unity.id,
            title=title, date=when, start_time=time(8, 0),
            end_time=time(9, 0), status=status,
        )
        db.session.add(reservation)
        db.session.commit()
        return reservation.id

    def test_detail_mostra_botao_e_mensagens(self):
        response = self.client.get(f'/reservations/{self.future_id}')
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('> Compartilhar', page)
        self.assertIn('id="shareModal"', page)
        self.assertIn('id="share-data"', page)
        # Assunto e corpo do e-mail viajam no JSON embutido no template
        self.assertIn('Reserva de sala: Aula de Teste', page)
        self.assertIn('Segue os detalhes da reserva de sala', page)
        self.assertIn('share-wa-text', page)

    def test_detail_passada_e_cancelada_nao_mostram_compartilhar(self):
        for reservation_id, title in ((self.past_id, 'Aula Passada'),
                                      (self.cancelled_id, 'Aula Cancelada')):
            response = self.client.get(f'/reservations/{reservation_id}')
            page = response.get_data(as_text=True)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('> Compartilhar', page, title)
            self.assertNotIn('id="shareModal"', page, title)
            self.assertNotIn('id="share-data"', page, title)


if __name__ == '__main__':
    unittest.main()
