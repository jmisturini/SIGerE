"""Botão + de Reservar e faixa de dias não reserváveis na Disponibilidade.

Nas visões de semana e mês, cada dia reservável ganha um atalho + (canto
oposto ao número) que leva à página de criação de reserva com a sala e a
data do dia clicado já preenchidas (?classroom_id=&date=). Domingos e
feriados da unidade (mesmo escopo do check_holiday) ganham uma faixa e não
têm atalho — sábado segue reservável e mantém o +. Quem não tem
reservation:create não vê atalho algum.
"""
import os
import tempfile
import unittest
import calendar
from datetime import date, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Holiday, Permission, Role, RoomCategory,
                        Unity, User)

GESTOR_EMAIL = 'gestor@escola.edu'
LEITOR_EMAIL = 'leitor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class AvailabilityBotaoReservarTestCase(unittest.TestCase):
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

            perm_create = Permission(code='reservation:create', module='reservation', action='create')
            perm_read_all = Permission(code='reservation:read_all', module='reservation', action='read_all')
            db.session.add_all([perm_create, perm_read_all])
            role_gestor = Role(name='gestor-teste', label='Gestor Teste',
                               permissions=[perm_create, perm_read_all])
            role_leitor = Role(name='leitor-teste', label='Leitor Teste',
                               permissions=[perm_read_all])
            db.session.add_all([role_gestor, role_leitor])
            db.session.flush()

            gestor = User(email=GESTOR_EMAIL, full_name='Gestor Teste',
                          role='room', profile_type='employee',
                          unities=[self.unity], role_id=role_gestor.id,
                          force_password_change=False, is_active_user=True)
            leitor = User(email=LEITOR_EMAIL, full_name='Leitor Teste',
                          role='room', profile_type='employee',
                          unities=[self.unity], role_id=role_leitor.id,
                          force_password_change=False, is_active_user=True)
            for u in (gestor, leitor):
                u.set_password(PASSWORD)
            db.session.add_all([gestor, leitor])
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            self.room = Classroom(name='Sala 1', code='S1', capacity=30,
                                  unity_id=self.unity.id, category_id=category.id)
            db.session.add(self.room)
            db.session.commit()
            self.room_id = self.room.id
            self.unity_id = self.unity.id

        self._login_as(GESTOR_EMAIL)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login_as(self, email):
        self.client.get('/logout')
        response = self.client.post('/login', data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    @staticmethod
    def _dias_uteis_mes(ano, mes):
        ultimo = calendar.monthrange(ano, mes)[1]
        return [d for d in range(1, ultimo + 1)
                if date(ano, mes, d).weekday() < 5]

    def test_mes_vem_atalhos_nos_dias_uteis_e_faixa_nos_domingos(self):
        hoje = date.today()
        ano, mes = hoje.year, hoje.month
        ultimo = calendar.monthrange(ano, mes)[1]
        domingos = [d for d in range(1, ultimo + 1)
                    if date(ano, mes, d).weekday() == 6]
        sabados = [d for d in range(1, ultimo + 1)
                   if date(ano, mes, d).weekday() == 5]
        uteis = self._dias_uteis_mes(ano, mes)

        response = self.client.get(
            f'/classrooms/{self.room_id}/availability'
            f'?view=month&year={ano}&month={mes}&day={hoje.day}')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        # Um atalho + por dia útil (sábado inclui; domingo não)
        self.assertEqual(page.count('class="day-add"'), len(uteis) + len(sabados))
        # Faixa de domingo em cada domingo (a contagem desconta o seletor CSS)
        self.assertEqual(page.count('faixa-dia faixa-domingo'), len(domingos))
        # Primeiro dia útil tem o atalho com a data certa (& vem escapado)
        d = uteis[0]
        self.assertIn(
            f'href="/reservations/create?classroom_id={self.room_id}'
            f'&amp;date={ano}-%02d-{d:02d}"' % mes,
            page)
        # Domingo sem atalho; sábado com atalho
        self.assertNotIn(f'&amp;date={ano}-%02d-{domingos[0]:02d}"' % mes, page)
        self.assertIn(f'&amp;date={ano}-%02d-{sabados[0]:02d}"' % mes, page)

    def test_semana_atalhos_nos_reservaveis_e_faixa_no_domingo(self):
        hoje = date.today()
        semana_inicio = hoje - timedelta(days=(hoje.weekday() + 1) % 7)
        dias = [semana_inicio + timedelta(days=i) for i in range(7)]
        reservaveis = [d for d in dias if d.weekday() != 6]

        response = self.client.get(
            f'/classrooms/{self.room_id}/availability?view=week')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertEqual(page.count('class="day-add"'), len(reservaveis))
        self.assertIn('faixa-dia faixa-domingo', page)
        # domingo sem atalho, sábado com
        domingo = semana_inicio
        sabado = next(d for d in dias if d.weekday() == 5)
        self.assertNotIn(f'&amp;date={domingo.isoformat()}"', page)
        self.assertIn(f'&amp;date={sabado.isoformat()}"', page)

    def test_feriado_da_unidade_ganha_faixa_e_perde_o_mais(self):
        hoje = date.today()
        ano, mes = hoje.year, hoje.month
        data_feriado = date(ano, mes, self._dias_uteis_mes(ano, mes)[3])

        with self.app.app_context():
            outra = Unity(name='Outra Unidade', code='OU')
            db.session.add(outra)
            db.session.flush()
            db.session.add(Holiday(name='Feriado de Outra Unidade',
                                   date=data_feriado, is_active=True,
                                   unity_id=outra.id))
            db.session.add(Holiday(name='Feriado Teste', date=data_feriado,
                                   is_active=True, unity_id=self.unity_id))
            db.session.commit()

        response = self.client.get(
            f'/classrooms/{self.room_id}/availability'
            f'?view=month&year={ano}&month={mes}&day={hoje.day}')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('faixa-dia faixa-feriado', page)
        self.assertIn('Feriado Teste', page)
        # feriado de outra unidade não aparece
        self.assertNotIn('Feriado de Outra Unidade', page)
        # sem atalho no feriado
        self.assertNotIn(f'&amp;date={data_feriado.isoformat()}"', page)
        # a contagem de atalhos cai um dia útil
        uteis = self._dias_uteis_mes(ano, mes)
        sabados = [d for d in range(1, calendar.monthrange(ano, mes)[1] + 1)
                   if date(ano, mes, d).weekday() == 5]
        self.assertEqual(page.count('class="day-add"'),
                         len(uteis) + len(sabados) - 1)

    def test_criacao_recebe_a_data_do_atalho(self):
        """O destino do atalho preenche a data (e a sala) do formulário;
        date inválido é ignorado sem quebrar a página."""
        response = self.client.get(
            f'/reservations/create?classroom_id={self.room_id}&date=2026-11-20')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('value="2026-11-20"', page)

        response = self.client.get(
            f'/reservations/create?classroom_id={self.room_id}&date=lixo')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('value="2026-11-20"', response.get_data(as_text=True))

    def test_sem_permissao_nao_ve_atalho(self):
        self._login_as(LEITOR_EMAIL)
        response = self.client.get(
            f'/classrooms/{self.room_id}/availability?view=month')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        # o CSS .day-add fica na página; o que não pode aparecer é o link
        self.assertNotIn('class="day-add"', page)


if __name__ == '__main__':
    unittest.main()
