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
    def _reservaveis_mes(ano, mes, desde):
        """Dias do mês com atalho + : de `desde` (hoje) em diante, exceto
        domingos (sábado conta — segue reservável)."""
        ultimo = calendar.monthrange(ano, mes)[1]
        return [d for d in range(desde, ultimo + 1)
                if date(ano, mes, d).weekday() != 6]

    def test_mes_vem_atalhos_nos_dias_uteis_e_faixa_nos_domingos(self):
        hoje = date.today()
        ano, mes = hoje.year, hoje.month
        ultimo = calendar.monthrange(ano, mes)[1]
        domingos = [d for d in range(1, ultimo + 1)
                    if date(ano, mes, d).weekday() == 6]
        reservaveis = self._reservaveis_mes(ano, mes, hoje.day)

        response = self.client.get(
            f'/classrooms/{self.room_id}/availability'
            f'?view=month&year={ano}&month={mes}&day={hoje.day}')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        # Um atalho + por dia reservável a partir de hoje (dias passados não
        # têm atalho; a contagem desconta o seletor CSS da faixa)
        self.assertEqual(page.count('class="day-add"'), len(reservaveis))
        # Faixa de domingo em cada domingo do mês, inclusive os passados
        self.assertEqual(page.count('faixa-dia faixa-domingo'), len(domingos))
        if not reservaveis:
            # mês acabando num domingo: nada mais a conferir de atalhos
            return
        # Primeiro dia reservável tem o atalho com a data certa (& vem escapado)
        d = reservaveis[0]
        self.assertIn(
            f'href="/reservations/create?classroom_id={self.room_id}'
            f'&amp;date={ano}-%02d-{d:02d}"' % mes,
            page)
        # Dia passado sem atalho
        if hoje.day > 1:
            passado = (f'&amp;date={ano}-%02d-{hoje.day - 1:02d}"' % mes)
            self.assertNotIn(passado, page)
        # Domingo sempre sem atalho
        self.assertNotIn(f'&amp;date={ano}-%02d-{domingos[0]:02d}"' % mes, page)
        # Sábado futuro com atalho
        sabado = next((d for d in reservaveis if date(ano, mes, d).weekday() == 5),
                      None)
        if sabado:
            self.assertIn(f'&amp;date={ano}-%02d-{sabado:02d}"' % mes, page)

    def test_semana_atalhos_nos_reservaveis_e_faixa_no_domingo(self):
        hoje = date.today()
        semana_inicio = hoje - timedelta(days=(hoje.weekday() + 1) % 7)
        dias = [semana_inicio + timedelta(days=i) for i in range(7)]
        reservaveis = [d for d in dias if d >= hoje and d.weekday() != 6]

        response = self.client.get(
            f'/classrooms/{self.room_id}/availability?view=week')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertEqual(page.count('class="day-add"'), len(reservaveis))
        self.assertIn('faixa-dia faixa-domingo', page)
        # domingo e dia passado sem atalho, sábado futuro com
        domingo = semana_inicio
        passados = [d for d in dias if d < hoje and d.weekday() != 6]
        sabado = next((d for d in dias if d.weekday() == 5), None)
        self.assertNotIn(f'&amp;date={domingo.isoformat()}"', page)
        if passados:
            self.assertNotIn(f'&amp;date={passados[0].isoformat()}"', page)
        if sabado is not None and sabado >= hoje:
            self.assertIn(f'&amp;date={sabado.isoformat()}"', page)

    def test_feriado_da_unidade_ganha_faixa_e_perde_o_mais(self):
        # Ancora no mês seguinte (year/month na query): todos os dias são
        # futuros, então todo dia não-domingo tem atalho e a subtração do
        # feriado nunca fica vaga — mesmo se hoje for o último domingo do mês.
        hoje = date.today()
        ano_mes, mes_alvo = ((hoje.year + 1, 1) if hoje.month == 12
                             else (hoje.year, hoje.month + 1))
        ultimo = calendar.monthrange(ano_mes, mes_alvo)[1]
        reservaveis = [d for d in range(1, ultimo + 1)
                       if date(ano_mes, mes_alvo, d).weekday() != 6]
        dia_alvo = reservaveis[0]
        data_feriado = date(ano_mes, mes_alvo, dia_alvo)

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
            f'?view=month&year={ano_mes}&month={mes_alvo}&day={dia_alvo}')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('faixa-dia faixa-feriado', page)
        self.assertIn('Feriado Teste', page)
        # feriado de outra unidade não aparece
        self.assertNotIn('Feriado de Outra Unidade', page)
        # sem atalho no feriado; a contagem de atalhos cai um dia reservável
        self.assertNotIn(f'&amp;date={data_feriado.isoformat()}"', page)
        self.assertEqual(page.count('class="day-add"'), len(reservaveis) - 1)

    def test_sala_inativa_nao_tem_atalho(self):
        """Sala inativa continua com página de disponibilidade, mas sem
        atalho — o formulário de criação lista só salas ativas. O mesmo
        vale para o botão Reservar da página de detalhes."""
        with self.app.app_context():
            room = db.session.get(Classroom, self.room_id)
            room.is_active = False
            db.session.commit()

        hoje = date.today()
        response = self.client.get(
            f'/classrooms/{self.room_id}/availability'
            f'?view=month&year={hoje.year}&month={hoje.month}&day={hoje.day}')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertNotIn('class="day-add"', page)

        detalhes = self.client.get(f'/classrooms/{self.room_id}')
        self.assertEqual(detalhes.status_code, 200)
        self.assertNotIn('Reservar', detalhes.get_data(as_text=True))

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
