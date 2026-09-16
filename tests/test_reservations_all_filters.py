"""Testes da página Todas as Reservas: abas Atuais/Futuras e Passadas,
filtros do calendário (datas, período, sala, professor, curso, disciplina),
filtro de status e ordenação (padrão: data crescente, da atual para a futura).
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Permission, Reservation, Role,
                        RoomCategory, Subject, Unity, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ReservationsAllFiltersTestCase(unittest.TestCase):
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

            perm = Permission(code='reservation:read_all', module='reservation', action='read_all')
            db.session.add(perm)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=[perm])
            db.session.add(role)
            db.session.flush()

            self.gestor = User(
                email=EMAIL, full_name='Gestor Teste', role='room',
                profile_type='employee', unity_id=self.unity.id,
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            self.gestor.set_password(PASSWORD)
            db.session.add(self.gestor)
            db.session.flush()

            # Duas salas com códigos em ordem alfabética invertida às datas
            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            self.sala_s1 = Classroom(name='Sala 1', code='S1', capacity=30,
                                     unity_id=self.unity.id, category_id=category.id)
            self.sala_s2 = Classroom(name='Sala 2', code='S2', capacity=30,
                                     unity_id=self.unity.id, category_id=category.id)
            db.session.add_all([self.sala_s1, self.sala_s2])
            db.session.flush()

            # Professores com nomes em ordem oposta às datas das reservas
            self.prof_ana = User(email='ana@escola.edu', full_name='Ana Souza',
                                 role='room', profile_type='teacher',
                                 unity_id=self.unity.id, is_active_user=True)
            self.prof_bruno = User(email='bruno@escola.edu', full_name='Bruno Lima',
                                   role='room', profile_type='teacher',
                                   unity_id=self.unity.id, is_active_user=True)
            for prof in (self.prof_ana, self.prof_bruno):
                prof.set_password(PASSWORD)
            db.session.add_all([self.prof_ana, self.prof_bruno])
            db.session.flush()

            self.curso = Course(name='Curso A', code='CA1', unity_id=self.unity.id)
            db.session.add(self.curso)
            db.session.flush()
            self.disciplina = Subject(name='Disciplina A', code='DA1',
                                      course_id=self.curso.id, unity_id=self.unity.id)
            db.session.add(self.disciplina)
            db.session.flush()

            amanha = date.today() + timedelta(days=1)
            depois = date.today() + timedelta(days=3)
            ontem = date.today() - timedelta(days=1)
            antiga = date.today() - timedelta(days=10)

            # Atuais/futuras: S2 amanhã (Bruno, pendente, tarde) e S1 depois (Ana, aprovada, manhã, c/ curso e disciplina)
            self.futura_s2 = self._criar_reserva(
                self.sala_s2, 'Reserva Futura S2', amanha, time(13, 0), time(14, 0),
                status='pending', teacher=self.prof_bruno)
            self.futura_s1 = self._criar_reserva(
                self.sala_s1, 'Reserva Futura S1', depois, time(8, 0), time(9, 0),
                status='approved', teacher=self.prof_ana,
                course_id=self.curso.id, subject_id=self.disciplina.id)
            # Passadas: ontem (Ana, aprovada) e antiga (Bruno, cancelada, noite)
            self.passada_ontem = self._criar_reserva(
                self.sala_s1, 'Reserva Passada Ontem', ontem, time(8, 0), time(9, 0),
                status='approved', teacher=self.prof_ana)
            self.passada_antiga = self._criar_reserva(
                self.sala_s2, 'Reserva Passada Antiga', antiga, time(19, 0), time(20, 0),
                status='cancelled', teacher=self.prof_bruno)

            # ids fixados dentro do contexto (objetos ficam detached depois)
            self.ids = {
                'sala_s1': self.sala_s1.id, 'sala_s2': self.sala_s2.id,
                'prof_ana': self.prof_ana.id,
                'curso': self.curso.id, 'disciplina': self.disciplina.id,
            }

        self._login()

    def _criar_reserva(self, room, title, when, inicio, fim, status='approved',
                       teacher=None, course_id=None, subject_id=None):
        reservation = Reservation(
            user_id=self.gestor.id, classroom_id=room.id, unity_id=self.unity.id,
            title=title, date=when, start_time=inicio, end_time=fim,
            status=status, teacher_id=teacher.id if teacher else None,
            course_id=course_id, subject_id=subject_id,
        )
        db.session.add(reservation)
        db.session.commit()
        return reservation.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self):
        response = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _ordem_dos_titulos(self, query=''):
        page = self.client.get('/reservations/all' + query).get_data(as_text=True)
        titulos = ['Reserva Futura S1', 'Reserva Futura S2',
                   'Reserva Passada Ontem', 'Reserva Passada Antiga']
        posicoes = [(t, page.find(t)) for t in titulos if page.find(t) != -1]
        return [t for t, _ in sorted(posicoes, key=lambda par: par[1])]

    # ---------- abas ----------

    def test_padrao_mostra_apenas_atuais_em_ordem_cronologica(self):
        ordem = self._ordem_dos_titulos()
        self.assertEqual(ordem, ['Reserva Futura S2', 'Reserva Futura S1'])
        page = self.client.get('/reservations/all').get_data(as_text=True)
        self.assertNotIn('Reserva Passada Ontem', page)

    def test_aba_passadas_ordem_cronologica_padrao(self):
        ordem = self._ordem_dos_titulos('?periodo=passadas')
        self.assertEqual(ordem, ['Reserva Passada Antiga', 'Reserva Passada Ontem'])
        page = self.client.get('/reservations/all?periodo=passadas').get_data(as_text=True)
        self.assertNotIn('Reserva Futura S2', page)

    def test_aba_atuais_passadas_preservam_filtros(self):
        sala_id = self.ids['sala_s2']
        page = self.client.get(f'/reservations/all?periodo=atuais&room_id={sala_id}').get_data(as_text=True)
        # As duas abas carregam o filtro de sala na query string
        self.assertIn(f'periodo=passadas', page)
        self.assertIn(f'room_id={sala_id}', page)

    # ---------- ordenação ----------

    def test_ordenacao_data_desc(self):
        ordem = self._ordem_dos_titulos('?periodo=passadas&ordem=data_desc')
        self.assertEqual(ordem, ['Reserva Passada Ontem', 'Reserva Passada Antiga'])

    def test_ordenacao_por_sala(self):
        ordem = self._ordem_dos_titulos('?ordem=sala')
        self.assertEqual(ordem, ['Reserva Futura S1', 'Reserva Futura S2'])

    def test_ordenacao_por_professor(self):
        ordem = self._ordem_dos_titulos('?ordem=professor')
        self.assertEqual(ordem, ['Reserva Futura S1', 'Reserva Futura S2'])

    def test_ordem_invalida_cai_no_padrao(self):
        ordem = self._ordem_dos_titulos('?ordem=qualquer-coisa')
        self.assertEqual(ordem, ['Reserva Futura S2', 'Reserva Futura S1'])

    # ---------- filtros ----------

    def test_filtro_sala(self):
        sala_id = self.ids['sala_s2']
        ordem = self._ordem_dos_titulos(f'?room_id={sala_id}')
        self.assertEqual(ordem, ['Reserva Futura S2'])

    def test_filtro_professor(self):
        ana_id = self.ids['prof_ana']
        ordem = self._ordem_dos_titulos(f'?teacher_id={ana_id}')
        self.assertEqual(ordem, ['Reserva Futura S1'])

    def test_filtro_status(self):
        ordem = self._ordem_dos_titulos('?status=pending')
        self.assertEqual(ordem, ['Reserva Futura S2'])

    def test_filtro_periodo_do_dia(self):
        ordem = self._ordem_dos_titulos('?period=afternoon')
        self.assertEqual(ordem, ['Reserva Futura S2'])
        ordem = self._ordem_dos_titulos('?period=morning')
        self.assertEqual(ordem, ['Reserva Futura S1'])

    def test_filtro_por_datas(self):
        amanha = (date.today() + timedelta(days=1)).isoformat()
        ordem = self._ordem_dos_titulos(f'?start={amanha}&end={amanha}')
        self.assertEqual(ordem, ['Reserva Futura S2'])

    def test_filtro_curso_e_disciplina(self):
        curso_id, disciplina_id = self.ids['curso'], self.ids['disciplina']
        ordem = self._ordem_dos_titulos(f'?course_id={curso_id}')
        self.assertEqual(ordem, ['Reserva Futura S1'])
        ordem = self._ordem_dos_titulos(f'?subject_id={disciplina_id}')
        self.assertEqual(ordem, ['Reserva Futura S1'])

    def test_filtros_combinam_com_aba_passadas(self):
        ana_id = self.ids['prof_ana']
        ordem = self._ordem_dos_titulos(f'?periodo=passadas&teacher_id={ana_id}')
        self.assertEqual(ordem, ['Reserva Passada Ontem'])

    def test_formulario_prefiltra_valores_da_query(self):
        sala_id = self.ids['sala_s2']
        page = self.client.get(f'/reservations/all?periodo=passadas&room_id={sala_id}&status=cancelled').get_data(as_text=True)
        self.assertIn(f'value="{sala_id}" selected', page)
        self.assertIn('value="cancelled" selected', page)


if __name__ == '__main__':
    unittest.main()
