"""Testes do destaque do período atual na página pública /cronograma.

No dia de hoje, o cartão do período em curso (Manhã/Tarde/Noite, mesmos
cortes do totem) recebe destaque visual e o selo "Agora"; consultando outro
dia, nenhum cartão é destacado.
"""
import os
import re
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.blueprints.public import _periodo_atual
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role, RoomCategory,
                        Unity, User)

ROTULOS = {'manha': 'Manhã', 'tarde': 'Tarde', 'noite': 'Noite'}


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class CronogramaPeriodoAtualTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.unity = Unity(name='Unidade Teste', code='UT', is_active=True)
            db.session.add(self.unity)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()

            room = Classroom(name='Sala 1', code='S1', capacity=30,
                             unity_id=self.unity.id, category_id=category.id)
            db.session.add(room)
            db.session.flush()

            user = User(email='prof@escola.edu', full_name='Professor Teste',
                        role='room', profile_type='teacher',
                        unity_id=self.unity.id, force_password_change=False,
                        is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.flush()

            hoje = date.today()
            db.session.add_all([
                # Uma aula de manhã e outra à noite: dois períodos com conteúdo
                Reservation(user_id=user.id, classroom_id=room.id,
                            unity_id=self.unity.id, title='Aula da Manhã',
                            date=hoje, start_time=time(8, 0), end_time=time(9, 0),
                            status='approved'),
                Reservation(user_id=user.id, classroom_id=room.id,
                            unity_id=self.unity.id, title='Aula da Noite',
                            date=hoje, start_time=time(19, 0), end_time=time(20, 0),
                            status='approved'),
            ])
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_periodo_atual_destacado_no_dia(self):
        page = self.client.get('/cronograma').get_data(as_text=True)

        # O selo "Agora" aparece exatamente uma vez
        self.assertEqual(page.count('>Agora<'), 1)

        # O cartão destacado é o do período em que o relógio está agora
        esperado = _periodo_atual()
        cards = [m.start() for m in re.finditer(r'<div class="card w-100', page)]
        destaque = re.search(r'<div class="card w-100 border-primary', page).start()
        self.assertEqual(cards.index(destaque),
                         ['manha', 'tarde', 'noite'].index(esperado))
        # ...e o rótulo do período destacado é o esperado
        proximo_cartao = cards[cards.index(destaque) + 1] if cards.index(destaque) + 1 < len(cards) else len(page)
        self.assertIn(ROTULOS[esperado], page[destaque:proximo_cartao])

    def test_sem_destaque_em_outro_dia(self):
        amanha = (date.today() + timedelta(days=1)).isoformat()
        page = self.client.get(f'/cronograma?data={amanha}').get_data(as_text=True)
        self.assertNotIn('card w-100 border-primary', page)
        self.assertNotIn('>Agora<', page)


if __name__ == '__main__':
    unittest.main()
