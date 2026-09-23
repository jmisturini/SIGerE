"""Atalhos de período do cronograma público (/cronograma) no celular.

No celular os três cartões empilham e, para chegar à Tarde/Noite, era preciso
rolar por todos os períodos anteriores. A página agora tem uma barra fixa de
atalhos (Manhã/Tarde/Noite, com contagem de aulas), rola automaticamente para
o período em curso no dia de hoje e marca o atalho do período em curso — sem
duplicar o selo "Agora" do cartão.
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.blueprints.public import _periodo_atual
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Reservation, RoomCategory, Unity, User)


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class CronogramaNavegacaoPeriodosTestCase(unittest.TestCase):
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
                # Aula em cada período: os três atalhos têm contagem > 0
                Reservation(user_id=user.id, classroom_id=room.id,
                            unity_id=self.unity.id, title='Aula da Manhã',
                            date=hoje, start_time=time(8, 0), end_time=time(9, 0),
                            status='approved'),
                Reservation(user_id=user.id, classroom_id=room.id,
                            unity_id=self.unity.id, title='Aula da Tarde',
                            date=hoje, start_time=time(14, 0), end_time=time(15, 0),
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

    def _pagina(self, query=''):
        return self.client.get(f'/cronograma{query}').get_data(as_text=True)

    def _trecho_nav(self, page):
        inicio = page.index('class="periodo-nav')
        return page[inicio:page.index('</nav>', inicio)]

    def test_atalhos_renderizam_na_ordem_dos_periodos(self):
        page = self._pagina()

        for chave in ('manha', 'tarde', 'noite'):
            self.assertIn(f'id="periodo-{chave}"', page)

        nav = self._trecho_nav(page)
        self.assertLess(nav.index('href="#periodo-manha"'),
                        nav.index('href="#periodo-tarde"'))
        self.assertLess(nav.index('href="#periodo-tarde"'),
                        nav.index('href="#periodo-noite"'))

    def test_contagem_de_aulas_nos_atalhos(self):
        nav = self._trecho_nav(self._pagina())
        # Uma aula por período: cada atalho anuncia 1
        self.assertEqual(nav.count('>1</span>'), 3)

    def test_selo_agora_do_cartao_nao_e_duplicado_pela_barra(self):
        page = self._pagina()
        self.assertEqual(page.count('>Agora<'), 1)
        self.assertNotIn('Agora', self._trecho_nav(page))
        # ...mas o atalho do período em curso recebe a marca própria
        self.assertIn('periodo-nav-pulso', self._trecho_nav(page))

    def test_rolagem_automatica_apenas_no_dia_de_hoje(self):
        page = self._pagina()
        self.assertIn(f'data-periodo-atual="{_periodo_atual()}"', page)

        amanha = (date.today() + timedelta(days=1)).isoformat()
        page_amanha = self._pagina(f'?data={amanha}')
        self.assertNotIn('data-periodo-atual', page_amanha)
        self.assertNotIn('periodo-nav-pulso', page_amanha)
        self.assertNotIn('periodo-nav-item ativo', page_amanha)

    def test_script_de_navegacao_e_incluido(self):
        self.assertIn('cronograma-periodos.js', self._pagina())


if __name__ == '__main__':
    unittest.main()
