"""Testes da regra de cancelamento automático de pendências.

Reserva pendente de aprovação cujo horário agendado chega a menos de 1 hora
(ou já passou) é cancelada pelo comando autocancel-pendentes — aprovação
tardia não teria mais função. O criador recebe o mesmo aviso dos
cancelamentos manuais, com o motivo automático no corpo. Reservas aprovadas,
já canceladas e pendências ainda fora da janela ficam intactas; rodar de
novo é idempotente e o dry-run não grava nada.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Notification, Reservation,
                        Role, RoomCategory, Unity, User,
                        EVENT_RESERVATION_CANCELLED)

EMAIL = 'criador@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class AutocancelPendentesTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False

        with self.app.app_context():
            db.create_all()
            self.unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(self.unity)
            db.session.flush()

            role = Role(name='professor', label='Professor', permissions=[])
            db.session.add(role)
            db.session.flush()

            self.criador = User(
                email=EMAIL, full_name='Criador Teste',
                role='room', profile_type='teacher', unities=[self.unity],
                role_id=role.id, force_password_change=False,
                is_active_user=True,
            )
            self.criador.set_password(PASSWORD)
            db.session.add(self.criador)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()

            self.room = Classroom(name='Sala 1', code='S1', capacity=30,
                                  unity_id=self.unity.id,
                                  category_id=category.id)
            db.session.add(self.room)
            db.session.commit()
            self.criador_id = self.criador.id
            self.unity_id = self.unity.id
            self.room_id = self.room.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _criar(self, titulo, inicio, status='pending'):
        """Reserva com início em datetime; devolve o id."""
        with self.app.app_context():
            reservation = Reservation(
                user_id=self.criador_id, classroom_id=self.room_id,
                unity_id=self.unity_id, title=titulo, date=inicio.date(),
                start_time=inicio.time(),
                end_time=(inicio + timedelta(hours=1)).time(),
                status=status,
            )
            db.session.add(reservation)
            db.session.commit()
            return reservation.id

    def _status(self, reservation_id):
        with self.app.app_context():
            return db.session.get(Reservation, reservation_id).status

    def _avisos(self, reservation_id):
        with self.app.app_context():
            return Notification.query.filter_by(
                reservation_id=reservation_id,
                event_type=EVENT_RESERVATION_CANCELLED).all()

    def test_pendente_30_min_antes_e_cancelada_com_aviso(self):
        agora = datetime.now()
        rid = self._criar('Pendente Iminente', agora + timedelta(minutes=30))

        from app.services.scheduling import autocancelar_pendentes
        with self.app.app_context():
            stats = autocancelar_pendentes(agora=agora)

        self.assertEqual(stats['canceladas'], 1)
        self.assertEqual(self._status(rid), 'cancelled')
        avisos = self._avisos(rid)
        self.assertEqual(len(avisos), 1)
        self.assertIn('Cancelada automaticamente', avisos[0].body)
        self.assertIn('1 hora antes', avisos[0].body)

    def test_pendente_2h_antes_permanece(self):
        agora = datetime.now()
        rid = self._criar('Pendente Distante', agora + timedelta(hours=2))

        from app.services.scheduling import autocancelar_pendentes
        with self.app.app_context():
            stats = autocancelar_pendentes(agora=agora)

        self.assertEqual(stats['canceladas'], 0)
        self.assertEqual(self._status(rid), 'pending')
        self.assertEqual(self._avisos(rid), [])

    def test_aprovada_e_cancelada_nao_sao_afetadas(self):
        agora = datetime.now()
        rid_aprovada = self._criar('Aprovada Iminente',
                                   agora + timedelta(minutes=30),
                                   status='approved')
        rid_cancelada = self._criar('Já Cancelada',
                                    agora + timedelta(minutes=30),
                                    status='cancelled')

        from app.services.scheduling import autocancelar_pendentes
        with self.app.app_context():
            autocancelar_pendentes(agora=agora)

        self.assertEqual(self._status(rid_aprovada), 'approved')
        self.assertEqual(self._status(rid_cancelada), 'cancelled')
        self.assertEqual(self._avisos(rid_aprovada), [])

    def test_pendente_com_inicio_passado_e_cancelada(self):
        """Início já passou (timer parado/fim de semana): pendência vencida
        nunca mais será aprovada — sai da fila como cancelada."""
        agora = datetime.now()
        rid = self._criar('Pendente Passada', agora - timedelta(days=1))

        from app.services.scheduling import autocancelar_pendentes
        with self.app.app_context():
            stats = autocancelar_pendentes(agora=agora)

        self.assertEqual(stats['canceladas'], 1)
        self.assertEqual(self._status(rid), 'cancelled')

    def test_dry_run_nao_grava(self):
        agora = datetime.now()
        rid = self._criar('Pendente Dry Run', agora + timedelta(minutes=30))

        from app.services.scheduling import autocancelar_pendentes
        with self.app.app_context():
            stats = autocancelar_pendentes(agora=agora, dry_run=True)

        self.assertEqual(stats['canceladas'], 1)
        self.assertEqual(self._status(rid), 'pending')
        self.assertEqual(self._avisos(rid), [])

    def test_idempotente(self):
        agora = datetime.now()
        self._criar('Pendente Unica', agora + timedelta(minutes=30))

        from app.services.scheduling import autocancelar_pendentes
        with self.app.app_context():
            primeira = autocancelar_pendentes(agora=agora)
            segunda = autocancelar_pendentes(agora=agora)

        self.assertEqual(primeira['canceladas'], 1)
        self.assertEqual(segunda['canceladas'], 0)

    def test_criador_inativo_cancela_sem_aviso(self):
        agora = datetime.now()
        rid = self._criar('Pendente de Inativo', agora + timedelta(minutes=30))
        with self.app.app_context():
            criador = db.session.get(User, self.criador_id)
            criador.is_active_user = False
            db.session.commit()

        from app.services.scheduling import autocancelar_pendentes
        with self.app.app_context():
            stats = autocancelar_pendentes(agora=agora)

        self.assertEqual(stats['canceladas'], 1)
        self.assertEqual(stats['avisos'], 0)
        self.assertEqual(self._status(rid), 'cancelled')
        self.assertEqual(self._avisos(rid), [])


if __name__ == '__main__':
    unittest.main()
