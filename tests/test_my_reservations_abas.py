"""Testes das abas de período em Minhas Reservas.

A listagem é separada em duas abas — Atuais e Futuras (hoje em diante) e
Passadas — cada uma com paginação própria: o período entra no filtro antes
do paginate, então os contadores e páginas de uma aba não interferem na
outra. A troca de aba preserva os filtros ativos (status e ordenação) e
reinicia para a primeira página.
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role, RoomCategory,
                        Unity, User)

EMAIL = 'professor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class MyReservationsAbasTestCase(unittest.TestCase):
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

            perm_read_own = Permission(code='reservation:read_own',
                                       module='reservation', action='read_own')
            db.session.add(perm_read_own)
            role = Role(name='professor', label='Professor',
                        permissions=[perm_read_own])
            db.session.add(role)
            db.session.flush()

            user = User(
                email=EMAIL, full_name='Professor Teste',
                role='room', profile_type='teacher', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()
            self.user_id = user.id

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()

            room = Classroom(name='Sala 1', code='S1', capacity=30,
                             unity_id=self.unity.id, category_id=category.id)
            db.session.add(room)
            db.session.flush()
            self.room_id = room.id

            ontem = date.today() - timedelta(days=1)
            amanha = date.today() + timedelta(days=1)
            self._criar('Futura Unica', amanha)
            # Horários distintos: a ordenação padrão (data desc) fica
            # determinística dentro do mesmo dia.
            self._criar('Passada Um', ontem, time(8, 0), time(9, 0))
            self._criar('Passada Dois', ontem, time(9, 0), time(10, 0))
            self._criar('Passada Tres', ontem, time(10, 0), time(11, 0))

        self._login()

    def _criar(self, titulo, quando, start=time(8, 0), end=time(9, 0)):
        reservation = Reservation(
            user_id=self.user_id, classroom_id=self.room_id,
            unity_id=self.unity.id, title=titulo, date=quando,
            start_time=start, end_time=end, status='approved',
        )
        db.session.add(reservation)
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
        response = self.client.post('/login',
                                    data={'email': EMAIL, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_aba_padrao_mostra_apenas_atuais_e_futuras(self):
        """Sem ?periodo, a aba Atuais e Futuras não lista reservas passadas."""
        response = self.client.get('/reservations/my')
        pagina = response.get_data(as_text=True)
        self.assertIn('Futura Unica', pagina)
        self.assertNotIn('Passada Um', pagina)
        self.assertIn('Reservas Atuais e Futuras', pagina)
        self.assertNotIn('Reservas Passadas</h5>', pagina)

    def test_aba_passadas_mostra_apenas_passadas(self):
        """?periodo=passadas lista só o histórico, em cinza."""
        response = self.client.get('/reservations/my?periodo=passadas')
        pagina = response.get_data(as_text=True)
        self.assertIn('Passada Um', pagina)
        self.assertNotIn('Futura Unica', pagina)
        self.assertIn('Reservas Passadas</h5>', pagina)
        self.assertIn('<tr class="text-muted">', pagina)

    def test_periodo_invalido_cai_no_padrao(self):
        response = self.client.get('/reservations/my?periodo=qualquer')
        pagina = response.get_data(as_text=True)
        self.assertIn('Futura Unica', pagina)
        self.assertNotIn('Passada Um', pagina)

    @patch('app.blueprints.reservations.RESERVATIONS_PER_PAGE', 2)
    def test_paginacao_independente_por_aba(self):
        """Com 2 reservas por página: a aba padrão (1 reserva) não pagina;
        a de passadas (3 reservas) pagina e navega sem misturar períodos."""
        pagina = self.client.get('/reservations/my').get_data(as_text=True)
        self.assertNotIn('registro(s) — página', pagina)

        pagina = self.client.get(
            '/reservations/my?periodo=passadas').get_data(as_text=True)
        self.assertIn('3 registro(s) — página 1 de 2', pagina)
        # Ordenação padrão: data desc com horário como desempate — as duas
        # primeiras do dia na pág. 1, a última na pág. 2.
        self.assertIn('Passada Um', pagina)
        self.assertIn('Passada Dois', pagina)
        self.assertNotIn('Passada Tres', pagina)

        pagina = self.client.get(
            '/reservations/my?periodo=passadas&page=2').get_data(as_text=True)
        self.assertIn('Passada Tres', pagina)
        self.assertNotIn('Passada Um', pagina)
        self.assertNotIn('Futura Unica', pagina)

    def test_troca_de_aba_preserva_filtros_e_volta_a_pagina_1(self):
        """Os links de aba mantêm status e ordenação ativos e descartam a
        página atual."""
        response = self.client.get(
            '/reservations/my?periodo=passadas&status=approved&ordem=sala&page=2')
        pagina = response.get_data(as_text=True)
        self.assertIn('periodo=atuais&amp;status=approved&amp;ordem=sala', pagina)
        self.assertIn('periodo=passadas&amp;status=approved&amp;ordem=sala', pagina)
        self.assertNotIn('page=2', pagina.split('nav nav-tabs')[1].split('</ul>')[0])


if __name__ == '__main__':
    unittest.main()
