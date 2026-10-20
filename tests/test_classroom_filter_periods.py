"""Testes do filtro de disponibilidade da listagem de Salas com vários períodos.

O select de períodos aceita múltipla escolha (Manhã/Tarde/Noite): a sala
precisa estar livre em TODOS os períodos escolhidos — uma única reserva
aprovada em qualquer um deles já exclui a sala. Um período só continua
funcionando como antes; sem período, a data sozinha não filtra.
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role,
                        RoomCategory, Unity, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ClassroomFilterPeriodsTestCase(unittest.TestCase):
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

            perms = [Permission(code='system:export', module='system', action='export')]
            db.session.add_all(perms)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            gestor = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()

            self.sala1 = Classroom(name='Sala Um', code='S1', capacity=30,
                                   unity_id=self.unity.id, category_id=category.id)
            self.sala2 = Classroom(name='Sala Dois', code='S2', capacity=30,
                                   unity_id=self.unity.id, category_id=category.id)
            db.session.add_all([self.sala1, self.sala2])
            db.session.commit()
            self.unity_id = self.unity.id
            self.gestor_id = gestor.id
            self.sala1_id = self.sala1.id
            self.sala2_id = self.sala2.id

        response = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
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

    def _dia(self):
        return date.today() + timedelta(days=1)

    def _reservar(self, sala_id, start, end):
        with self.app.app_context():
            db.session.add(Reservation(
                user_id=self.gestor_id, classroom_id=sala_id, title='Aula Teste',
                date=self._dia(), start_time=start, end_time=end,
                status='approved', unity_id=self.unity_id))
            db.session.commit()

    def _filtrar(self, *periodos):
        """GET da listagem com a data e os períodos selecionados (repetidos na
        query string, como o select múltiplo envia)."""
        query = f'available_date={self._dia().isoformat()}'
        for periodo in periodos:
            query += f'&available_period={periodo}'
        return self.client.get(f'/classrooms/?{query}')

    def test_periodo_unico_continua_funcionando(self):
        self._reservar(self.sala1_id, time(9, 0), time(11, 0))
        html = self._filtrar('morning').get_data(as_text=True)
        self.assertNotIn('Sala Um', html)
        self.assertIn('Sala Dois', html)

    def test_multiplos_periodos_exclui_ocupada_em_qualquer_um(self):
        self._reservar(self.sala1_id, time(9, 0), time(11, 0))   # manhã
        self._reservar(self.sala2_id, time(19, 0), time(21, 0))  # noite

        # Manhã + Noite: cada sala está ocupada em um dos períodos
        html = self._filtrar('morning', 'evening').get_data(as_text=True)
        self.assertNotIn('Sala Um', html)
        self.assertNotIn('Sala Dois', html)

        # Manhã + Tarde: a Sala Dois está livre nos dois períodos
        html = self._filtrar('morning', 'afternoon').get_data(as_text=True)
        self.assertNotIn('Sala Um', html)
        self.assertIn('Sala Dois', html)

    def test_mensagem_mostra_os_periodos_combinados(self):
        html = self._filtrar('morning', 'afternoon').get_data(as_text=True)
        self.assertIn('Mostrando salas disponíveis', html)
        self.assertIn('Manhã e Tarde', html)

    def test_sem_periodo_nao_filtra(self):
        self._reservar(self.sala1_id, time(9, 0), time(11, 0))
        response = self.client.get(
            f'/classrooms/?available_date={self._dia().isoformat()}')
        html = response.get_data(as_text=True)
        self.assertIn('Sala Um', html)
        self.assertIn('Sala Dois', html)
        self.assertNotIn('Mostrando salas disponíveis', html)

    def test_export_pdf_aceita_multiplos_periodos(self):
        self._reservar(self.sala1_id, time(9, 0), time(11, 0))
        response = self._filtrar('morning', 'evening')
        # Mesma URL da listagem serve para o PDF (o botão Exportar repassa a
        # query string inteira)
        response = self.client.get(f'/classrooms/export_pdf?{response.request.query_string.decode()}')
        self.assertEqual(response.status_code, 200)


if __name__ == '__main__':
    unittest.main()
