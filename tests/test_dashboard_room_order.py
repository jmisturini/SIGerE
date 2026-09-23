"""Ordenação das salas no painel (dashboard).

Os cards de cada seção ("Agenda de ...") devem sair em ordem crescente da
numeração do código da sala, e não na ordem em que as reservas foram criadas.
A comparação é natural: os trechos numéricos do código são comparados como
inteiros ("LI9" vem antes de "LI10").

A suíte sobe a aplicação real (create_app) com banco SQLite temporário,
seguindo o padrão de test_dynamic_categories.py.
"""
import os
import tempfile
import unittest
from datetime import date, time

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Classroom, Reservation, RoomCategory, Unity, User


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class DashboardRoomOrderTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            unity = Unity(name='Unidade Centro', code='CTR')
            db.session.add(unity)
            db.session.flush()
            self.unity_id = unity.id

            self.lab = RoomCategory(name='Laboratório de Informática', code='computer_lab')
            db.session.add(self.lab)
            db.session.flush()
            self.lab_id = self.lab.id

            # Cadastradas fora de ordem de propósito: o painel não pode
            # depender da ordem de inserção (nem do retorno do banco).
            self.rooms = {}
            for name, code in [('Lab 209', 'LI209'), ('Lab 104', 'LI104'),
                               ('Lab 202', 'LI202')]:
                room = Classroom(name=name, code=code, capacity=30,
                                 category_id=self.lab.id, unity_id=unity.id)
                db.session.add(room)
                self.rooms[code] = room
            db.session.flush()

            user = User(email='prof.teste@escola.edu',
                        full_name='Professor Teste', unity_id=unity.id,
                        force_password_change=False, is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.flush()
            self.user_id = user.id

            # Reserva das 00:00 às 23:59: sobrepõe qualquer período atual,
            # tornando o teste independente da hora em que ele roda. Mesmo
            # horário em todas as salas — antes, o desempate era imprevisível.
            for room in self.rooms.values():
                db.session.add(Reservation(user_id=user.id, classroom_id=room.id,
                                           title='Aula', date=date.today(),
                                           start_time=time(0, 0), end_time=time(23, 59),
                                           status='approved', unity_id=self.unity_id))
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self):
        return self.client.post('/login',
                                data={'email': 'prof.teste@escola.edu',
                                      'password': 'SenhaForte123'},
                                follow_redirects=False)

    def _dashboard_page(self):
        self._login()
        resp = self.client.get('/dashboard')
        self.assertEqual(resp.status_code, 200)
        return resp.data.decode('utf-8')

    def test_cards_em_ordem_crescente_de_numeracao(self):
        """As salas aparecem em ordem crescente de numeração, apesar de
        terem sido cadastradas como LI209, LI104, LI202."""
        page = self._dashboard_page()
        self.assertLess(page.index('LI104'), page.index('LI202'))
        self.assertLess(page.index('LI202'), page.index('LI209'))

    def test_ordem_natural_li9_antes_de_li10(self):
        """Numeração comparada como inteiro: LI9 vem antes de LI10 (a
        comparação de strings colocaria LI10 primeiro)."""
        with self.app.app_context():
            for code in ('LI10', 'LI9'):
                room = Classroom(name=f'Lab {code}', code=code, capacity=30,
                                 category_id=self.lab_id, unity_id=self.unity_id)
                db.session.add(room)
                db.session.flush()
                db.session.add(Reservation(user_id=self.user_id,
                                           classroom_id=room.id, title='Aula',
                                           date=date.today(), start_time=time(0, 0),
                                           end_time=time(23, 59),
                                           status='approved',
                                           unity_id=self.unity_id))
            db.session.commit()

        page = self._dashboard_page()
        self.assertLess(page.index('LI9</span>'), page.index('LI10</span>'))


if __name__ == '__main__':
    unittest.main()
