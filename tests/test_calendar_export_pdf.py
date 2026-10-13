"""Testes da exportação de aulas do calendário em PDF (/calendar/export_pdf):
mesmos filtros da API de eventos, nome de arquivo com o período, comportamento
sem/ com datas inválidas e o botão visível apenas com system:export.
"""
import os
import tempfile
import unittest
from datetime import date, time

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role, RoomCategory,
                        Unity, User)

EMAIL = 'super@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class CalendarExportPdfTestCase(unittest.TestCase):
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
                email=EMAIL, full_name='Super Teste',
                role='admin', profile_type='employee', role_id=role.id,
                force_password_change=False, is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)

            unity = Unity(name='Unidade Centro', code='CTR', is_active=True)
            db.session.add(unity)
            db.session.flush()
            self.unity_id = unity.id
            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            self.sala101 = Classroom(name='Sala 101', code='S101',
                                     capacity=30, category_id=category.id,
                                     unity_id=unity.id, is_active=True)
            self.sala202 = Classroom(name='Sala 202', code='S202',
                                     capacity=25, category_id=category.id,
                                     unity_id=unity.id, is_active=True)
            db.session.add_all([self.sala101, self.sala202])
            db.session.flush()
            self.sala101_id = self.sala101.id
            self.sala202_id = self.sala202.id

            db.session.add_all([
                # Aula de manhã na 101
                Reservation(user_id=user.id, classroom_id=self.sala101.id,
                            title='Aula de Matemática', date=date(2026, 9, 10),
                            start_time=time(8, 0), end_time=time(10, 0),
                            status='approved', unity_id=unity.id),
                # Aula de tarde na 202 (mesmo dia)
                Reservation(user_id=user.id, classroom_id=self.sala202.id,
                            title='Aula de Física', date=date(2026, 9, 10),
                            start_time=time(14, 0), end_time=time(16, 0),
                            status='approved', unity_id=unity.id),
                # Cancelada: não pode aparecer em API nem PDF
                Reservation(user_id=user.id, classroom_id=self.sala101.id,
                            title='Aula Cancelada', date=date(2026, 9, 11),
                            start_time=time(8, 0), end_time=time(10, 0),
                            status='cancelled', unity_id=unity.id),
            ])
            db.session.commit()
        self._login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email=EMAIL, password=PASSWORD):
        response = self.client.post('/login', data={'email': email, 'password': password},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _exportar(self, **kwargs):
        return self.client.get('/calendar/export_pdf', query_string=kwargs)

    def test_exportacao_retorna_pdf_com_periodo_no_arquivo(self):
        resp = self._exportar(initialDate='2026-09-01', finalDate='2026-09-30')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Content-Type'], 'application/pdf')
        self.assertIn('aulas_2026-09-01_a_2026-09-30.pdf',
                      resp.headers['Content-Disposition'])
        self.assertTrue(resp.get_data().startswith(b'%PDF'))

    def test_exportacao_sem_datas_nao_explode(self):
        """Sem intervalo o PDF sai vazio (quadro de ausência), como a API
        responde lista vazia — nunca todas as reservas da unidade."""
        resp = self._exportar()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Content-Type'], 'application/pdf')
        self.assertIn('filename=aulas.pdf', resp.headers['Content-Disposition'])

    def test_exportacao_com_datas_invalidas_nao_explode(self):
        resp = self._exportar(initialDate='data-ruim', finalDate='2026-09-30')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Content-Type'], 'application/pdf')

    def test_api_events_so_aprovadas_do_periodo(self):
        resp = self.client.get('/calendar/api/events', query_string={
            'initialDate': '2026-09-01', 'finalDate': '2026-09-30'})
        self.assertEqual(resp.status_code, 200)
        eventos = resp.get_json()
        self.assertEqual(len(eventos), 2)
        self.assertEqual([e['title'] for e in eventos],
                         ['Aula de Matemática', 'Aula de Física'])

    def test_api_events_respeita_filtro_de_sala(self):
        resp = self.client.get('/calendar/api/events', query_string={
            'initialDate': '2026-09-01', 'finalDate': '2026-09-30',
            'room_id': self.sala202_id})
        eventos = resp.get_json()
        self.assertEqual([e['title'] for e in eventos], ['Aula de Física'])

    def test_api_events_respeita_filtro_de_periodo(self):
        resp = self.client.get('/calendar/api/events', query_string={
            'initialDate': '2026-09-01', 'finalDate': '2026-09-30',
            'period': 'morning'})
        eventos = resp.get_json()
        self.assertEqual([e['title'] for e in eventos], ['Aula de Matemática'])

    def test_api_events_sem_datas_retorna_vazio(self):
        resp = self.client.get('/calendar/api/events')
        self.assertEqual(resp.get_json(), [])

    def test_exportacao_exige_permissao(self):
        """Sem system:export a rota devolve 403, mesmo autenticado."""
        with self.app.app_context():
            leitura = Permission(code='reservation:read_own',
                                 module='reservation', action='read_own')
            db.session.add(leitura)
            db.session.flush()
            role = Role(name='leitor-calendario', label='Leitor Calendário',
                        permissions=[leitura])
            db.session.add(role)
            db.session.flush()
            unity = db.session.get(Unity, self.unity_id)
            user = User(email='leitor@escola.edu', full_name='Leitor Teste',
                        role='employee', profile_type='employee',
                        role_id=role.id, unities=[unity],
                        force_password_change=False, is_active_user=True)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()

        leitor = self.app.test_client()
        resp = leitor.post('/login', data={'email': 'leitor@escola.edu',
                                           'password': PASSWORD},
                           follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        resp = leitor.get('/calendar/export_pdf',
                          query_string={'initialDate': '2026-09-01',
                                        'finalDate': '2026-09-30'})
        self.assertEqual(resp.status_code, 403)

    def test_botao_exportar_aparece_conforme_permissao(self):
        resp = self.client.get('/calendar/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Exportar PDF', resp.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
