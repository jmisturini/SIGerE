"""Testes da página de disponibilidade da sala nas três visões (dia, semana
e mês): rota, navegação anterior/próxima e exibição das reservas aprovadas.
"""
import os
import tempfile
import unittest
from datetime import date, time

from app import create_app
from app.blueprints.classrooms import MESES_PT
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role, RoomCategory,
                        Unity, User)

USERNAME = 'super.teste'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class AvailabilityViewsTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            curinga = Permission(code='*', module='system', action='all')
            db.session.add(curinga)
            db.session.flush()
            role = Role(name='super_teste', label='Super Teste', permissions=[curinga])
            db.session.add(role)
            db.session.flush()
            user = User(
                username=USERNAME, email='super@escola.edu', full_name='Super Teste',
                role='admin', profile_type='employee', role_id=role.id,
                force_password_change=False, is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)

            unity = Unity(name='Unidade Centro', code='CTR', is_active=True)
            db.session.add(unity)
            db.session.flush()
            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            self.classroom = Classroom(name='Sala 101', code='S101',
                                       capacity=30, category_id=category.id,
                                       unity_id=unity.id, is_active=True)
            db.session.add(self.classroom)
            db.session.flush()
            self.reservation = Reservation(
                user_id=user.id, classroom_id=self.classroom.id,
                title='Aula de Teste', date=date(2026, 9, 10),
                start_time=time(8, 0), end_time=time(10, 0),
                status='approved', unity_id=unity.id,
            )
            db.session.add(self.reservation)
            db.session.commit()
            self.classroom_id = self.classroom.id
            self.unity_id = unity.id
            self.reservation_id = self.reservation.id
        self._login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self):
        response = self.client.post('/login', data={'username': USERNAME, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _get(self, **kwargs):
        response = self.client.get(f'/classrooms/{self.classroom_id}/availability',
                                   query_string=kwargs)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_visao_mensal_e_o_padrao(self):
        page = self._get(year=2026, month=9)
        self.assertIn('Setembro de 2026', page)
        self.assertIn('Aula de Teste', page)
        # Sem parâmetros: cai no mês atual, sem quebrar
        page = self._get()
        self.assertIn(MESES_PT[date.today().month - 1], page)

    def test_visao_diaria_mostra_reserva_e_dia_vazio(self):
        page = self._get(view='day', year=2026, month=9, day=10)
        self.assertIn('Quinta-feira, 10/09/2026', page)
        self.assertIn('Aula de Teste', page)
        self.assertIn('08:00 – 10:00', page)

        page = self._get(view='day', year=2026, month=9, day=11)
        self.assertIn('Nenhuma reserva neste dia', page)
        self.assertNotIn('Aula de Teste', page)

    def test_visao_semanal_mostra_os_sete_dias_e_a_reserva(self):
        page = self._get(view='week', year=2026, month=9, day=10)
        self.assertIn('06/09', page)   # domingo da semana de 10/09/2026
        self.assertIn('12/09/2026', page)  # sábado no título do período
        self.assertIn('Aula de Teste', page)

    def test_visao_invalida_cai_no_mensal(self):
        page = self._get(view='ano', year=2026, month=9)
        self.assertIn('Setembro de 2026', page)

    def test_navegacao_anterior_proxima_preserva_a_visao(self):
        page = self._get(view='day', year=2026, month=9, day=10)
        self.assertIn('day=9', page)      # Anterior → 09/09/2026
        self.assertIn('day=11', page)     # Próximo → 11/09/2026
        page = self._get(view='week', year=2026, month=9, day=10)
        self.assertIn('day=13', page)     # semana seguinte começa em 13/09
        page = self._get(view='month', year=2026, month=9, day=10)
        # hrefs escapam '&' como '&amp;' no HTML
        self.assertIn('month=8&amp;day=10', page)   # mês anterior mantém o dia
        self.assertIn('month=10&amp;day=10', page)  # mês seguinte mantém o dia

    def test_mes_atual_sem_day_ancora_em_hoje(self):
        """Abrir/trocar a visão no mês corrente sem ?day= não pode cair no
        dia 1: a âncora é o dia atual (causa do bug relatado ao alternar
        entre dia, semana e mês)."""
        hoje = date.today()
        page = self._get(view='month', year=hoje.year, month=hoje.month)
        self.assertIn(f'day={hoje.day}', page)
        page = self._get(view='week', year=hoje.year, month=hoje.month)
        self.assertIn(f'day={hoje.day}', page)

    def test_dia_da_ancora_clampa_no_comprimento_do_mes(self):
        """Dia 31 navegando para um mês de 30 dias ancora no último dia,
        em vez de voltar para hoje."""
        page = self._get(view='month', year=2026, month=9, day=31)
        self.assertIn('Setembro de 2026', page)
        self.assertIn('day=30', page)  # botões Semana/Dia ancorados em 30/09
        self.assertNotIn('day=31', page)

    def test_exportacao_acompanha_a_visao(self):
        """O PDF exportado cobre o período da visão em uso, não só o mês."""
        base = f'/classrooms/{self.classroom_id}/export_availability'

        resp = self.client.get(base, query_string={'view': 'day', 'year': 2026,
                                                   'month': 9, 'day': 10})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Content-Type'], 'application/pdf')
        self.assertIn('reservas_S101_2026-09-10.pdf', resp.headers['Content-Disposition'])

        resp = self.client.get(base, query_string={'view': 'week', 'year': 2026,
                                                   'month': 9, 'day': 10})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('reservas_S101_2026-09-06_a_2026-09-12.pdf',
                      resp.headers['Content-Disposition'])

        resp = self.client.get(base, query_string={'view': 'month', 'year': 2026,
                                                   'month': 9})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('reservas_S101_9-2026.pdf', resp.headers['Content-Disposition'])

    def test_detalhes_da_reserva_na_pagina(self):
        """Mês e semana abrem o modal de detalhes; a visão diária ganha botão."""
        page = self._get(view='month', year=2026, month=9)
        self.assertIn('data-bs-target="#modalReserva"', page)
        self.assertIn('data-titulo="Aula de Teste"', page)
        self.assertIn('id="modalReserva"', page)
        # usuário com permissão curinga ganha o link para a página completa
        self.assertIn(f'data-link="/reservations/{self.reservation_id}"', page)
        self.assertIn('data-link-visivel="1"', page)

        page = self._get(view='day', year=2026, month=9, day=10)
        self.assertIn('data-bs-target="#modalReserva"', page)
        self.assertIn('Detalhes', page)

    def test_link_de_detalhes_completos_respeita_permissao(self):
        """Sem reservation:read_all (nem ser o dono), o modal não oferece o
        link para a página completa de detalhes."""
        with self.app.app_context():
            room_read = Permission.query.filter_by(code='room:read').first()
            if not room_read:
                room_read = Permission(code='room:read', module='room', action='read')
                db.session.add(room_read)
                db.session.flush()
            role = Role(name='leitor-salas', label='Leitor de Salas',
                        permissions=[room_read])
            db.session.add(role)
            db.session.flush()
            user = User(username='leitor.teste', email='leitor@escola.edu',
                        full_name='Leitor Teste', role='room',
                        profile_type='employee', unity_id=self.unity_id,
                        role_id=role.id, force_password_change=False,
                        is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.commit()

        leitor = self.app.test_client()
        resp = leitor.post('/login', data={'username': 'leitor.teste',
                                           'password': 'SenhaForte123'},
                           follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        resp = leitor.get(f'/classrooms/{self.classroom_id}/availability',
                          query_string={'view': 'month', 'year': 2026, 'month': 9})
        self.assertEqual(resp.status_code, 200)
        page = resp.get_data(as_text=True)
        self.assertIn('data-link-visivel="0"', page)
        self.assertNotIn('data-link-visivel="1"', page)


if __name__ == '__main__':
    unittest.main()
