"""Testes do atalho de reservas pendentes (aprovação).

Quem tem reservation:approve E reservation:read_all recebe, no Painel e no
hub de Salas e Reservas, um atalho direto para a listagem filtrada em
status=pendente — com a contagem no Painel. Sem as permissões (ou sem
pendências), o atalho não nasce.
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

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class AtalhoPendentesTestCase(unittest.TestCase):
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

            categoria = RoomCategory(name='Sala de Aula', code='sala_aula',
                                     is_active=True)
            db.session.add(categoria)
            db.session.flush()

            self.sala = Classroom(code='SA1', name='Sala de Aula 1',
                                  capacity=30, category_id=categoria.id,
                                  unity_id=self.unity.id, is_active=True)
            db.session.add(self.sala)
            db.session.flush()
            self.sala_id = self.sala.id
            self.unity_id = self.unity.id

            codigos = ('system:dashboard', 'reservation:read_all',
                       'reservation:read_own', 'reservation:approve')
            perms = [Permission(code=c, module=c.split(':')[0], action=c.split(':')[1])
                     for c in codigos]
            db.session.add_all(perms)
            role = Role(name='gestor', label='Gestor', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(email=EMAIL, full_name='Gestor Teste', role='room',
                        profile_type='employee', unities=[self.unity],
                        role_id=role.id, force_password_change=False,
                        is_active_user=True)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id

        self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                         follow_redirects=True)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _reserva(self, titulo, quando, status='pending'):
        with self.app.app_context():
            user = User.query.filter_by(email=EMAIL).first()
            db.session.add(Reservation(
                user_id=user.id, classroom_id=self.sala_id, unity_id=self.unity_id,
                title=titulo, date=quando, start_time=time(14, 0),
                end_time=time(15, 0), status=status))
            db.session.commit()

    # --- Painel ---

    def test_painel_mostra_atalho_com_contagem(self):
        """Aprovador vê o atalho com o número de pendências atuais; pendência
        passada e reserva aprovada não entram na contagem."""
        hoje = date.today()
        self._reserva('Pendente 1', hoje + timedelta(days=1))
        self._reserva('Pendente 2', hoje + timedelta(days=2))
        self._reserva('Pendente passada', hoje - timedelta(days=1))
        self._reserva('Aprovada', hoje + timedelta(days=1), status='approved')

        page = self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn('painel-pendentes', page)
        self.assertIn('2 reservas aguardando aprovação', page)
        self.assertIn('status=pending', page)

    def test_painel_sem_pendencias_nao_mostra_atalho(self):
        """Nada pendente: nenhuma linha de atalho no Painel."""
        self._reserva('Aprovada', date.today(), status='approved')
        page = self.client.get('/dashboard').get_data(as_text=True)
        self.assertNotIn('painel-pendentes', page)

    def test_sem_permissao_de_aprovacao_nao_ha_atalho(self):
        """Quem vê a listagem mas não aprova: nem Painel nem hub trazem o
        atalho — a contagem nem é consultada."""
        with self.app.app_context():
            user = User.query.filter_by(email=EMAIL).first()
            user.role_obj.permissions = [
                Permission.query.filter_by(code='reservation:read_all').first()]
            db.session.commit()
        self._reserva('Pendente', date.today() + timedelta(days=1))

        page = self.client.get('/dashboard').get_data(as_text=True)
        self.assertNotIn('painel-pendentes', page)
        hub = self.client.get('/salas-e-reservas').get_data(as_text=True)
        self.assertNotIn('Reservas pendentes', hub)

    # --- Hub Salas e Reservas ---

    def test_hub_tem_card_de_pendentes(self):
        """O hub de Salas e Reservas lista o card do aprovador, apontando
        para a listagem já filtrada."""
        hub = self.client.get('/salas-e-reservas').get_data(as_text=True)
        self.assertIn('Reservas pendentes', hub)
        self.assertIn('status=pending', hub)

    def test_listagem_filtrada_abre_em_200(self):
        """O destino do atalho responde para quem tem read_all."""
        resposta = self.client.get('/reservations/all?status=pending')
        self.assertEqual(resposta.status_code, 200)


if __name__ == '__main__':
    unittest.main()
