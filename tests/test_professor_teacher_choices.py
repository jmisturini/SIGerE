"""Testes da lista de docentes do formulário de reserva no fluxo de professor.

Quem cria no fluxo de professor (reservation:create_pending) designa apenas
a si mesmo: o campo Professor do formulário lista só o próprio usuário (já
pré-selecionado) e o servidor rejeita POST com outro docente — inclusive a
opção vazia (0), que passa na validação do campo opcional. Gestores e demais
perfis continuam com a lista completa da unidade; o curinga '*' do
super-admin não seleciona o fluxo (a permissão precisa estar explícita). Na
edição, o docente atual de reservas antigas fica na lista para a designação
não se perder ao regravar o formulário, e trocá-lo só é aceito quando aponta
para o próprio professor.
"""
import os
import re
import tempfile
import unittest
from datetime import date, datetime, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Permission, Reservation, Role,
                        RoomCategory, Unity, User)

GESTOR_EMAIL = 'gestor@escola.edu'
PROF_A_EMAIL = 'ana@escola.edu'
PROF_B_EMAIL = 'bruno@escola.edu'
SUPER_EMAIL = 'super@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ProfessorTeacherChoicesTestCase(unittest.TestCase):
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

            perm_create = Permission(code='reservation:create', module='reservation',
                                     action='create')
            perm_pending = Permission(code='reservation:create_pending', module='reservation',
                                      action='create_pending')
            perm_read_own = Permission(code='reservation:read_own', module='reservation',
                                       action='read_own')
            perm_curinga = Permission(code='*', module='system', action='all')
            db.session.add_all([perm_create, perm_pending, perm_read_own, perm_curinga])
            db.session.flush()

            papel_gestor = Role(name='gestor-teste', label='Gestor Teste',
                                permissions=[perm_create, perm_read_own])
            db.session.add(papel_gestor)
            # Fluxo de professor: create_pending marca quem designa só a si mesmo
            papel_professor = Role(name='teacher', label='Professor',
                                   permissions=[perm_create, perm_pending, perm_read_own])
            db.session.add(papel_professor)
            # Super-admin: só o curinga '*' — não deve herdar o fluxo de professor
            papel_super = Role(name='super_admin', label='Super Administrador',
                               permissions=[perm_curinga])
            db.session.add(papel_super)
            db.session.flush()

            super_user = User(
                email=SUPER_EMAIL, full_name='Super Admin',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=papel_super.id, force_password_change=False,
                is_active_user=True,
            )
            super_user.set_password(PASSWORD)
            db.session.add(super_user)
            db.session.flush()

            gestor = User(
                email=GESTOR_EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=papel_gestor.id, force_password_change=False,
                is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)
            db.session.flush()

            self.prof_a = User(
                email=PROF_A_EMAIL, full_name='Prof Ana Criadora',
                role='room', profile_type='teacher', unities=[self.unity],
                role_id=papel_professor.id, force_password_change=False,
                is_active_user=True,
            )
            self.prof_a.set_password(PASSWORD)
            db.session.add(self.prof_a)
            db.session.flush()

            self.prof_b = User(
                email=PROF_B_EMAIL, full_name='Prof Bruno Colega',
                role='room', profile_type='teacher', unities=[self.unity],
                role_id=papel_professor.id, force_password_change=False,
                is_active_user=True,
            )
            self.prof_b.set_password(PASSWORD)
            db.session.add(self.prof_b)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()

            room = Classroom(name='Sala 1', code='S1', capacity=30,
                             unity_id=self.unity.id, category_id=category.id)
            db.session.add(room)
            db.session.flush()

            course = Course(name='Curso Teste', code='CT',
                            unity_id=self.unity.id, is_active=True)
            db.session.add(course)
            db.session.commit()
            self.room_id = room.id
            self.course_id = course.id
            self.unity_id = self.unity.id
            self.prof_a_id = self.prof_a.id
            self.prof_b_id = self.prof_b.id

        self._login(GESTOR_EMAIL)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email):
        # /login ignora o formulário com sessão ativa: desloga para trocar
        # de usuário (o setUp já loga como gestor).
        self.client.get('/logout')
        response = self.client.post('/login',
                                    data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _dia_futuro(self, dias_a_frente=1):
        d = date.today() + timedelta(days=dias_a_frente)
        while d.weekday() == 6:
            d += timedelta(days=1)
        return d

    def _payload(self, dia, teacher_id, titulo='Aula de teste'):
        return {
            'classroom': str(self.room_id),
            'course': str(self.course_id),
            'subject': '0', 'teacher': str(teacher_id),
            'title': titulo, 'description': '',
            'date': dia.strftime('%Y-%m-%d'),
            'start_time': '09:00', 'end_time': '10:00',
        }

    def _select_teacher(self, pagina):
        """Bloco <select> do campo Professor (o select de destinatários de
        notificação lista todos os usuários e não entra na verificação)."""
        m = re.search(r'<select[^>]*id="teacher".*?</select>', pagina, re.DOTALL)
        self.assertIsNotNone(m, 'campo Professor não encontrado na página')
        return m.group(0)

    def test_professor_ve_apenas_a_si_mesmo_e_pre_selecionado(self):
        self._login(PROF_A_EMAIL)
        response = self.client.get('/reservations/create')
        pagina = response.get_data(as_text=True)
        select = self._select_teacher(pagina)
        self.assertIn('Prof Ana Criadora', select)
        self.assertNotIn('Prof Bruno Colega', select)
        # Próprio professor já entra designado (WTForms: <option selected value=...>)
        opcao = re.search(rf'<option[^>]*value="{self.prof_a_id}"[^>]*>', select)
        self.assertIsNotNone(opcao, f'opção do professor {self.prof_a_id} ausente')
        self.assertIn('selected', opcao.group(0))

    def test_gestor_ve_lista_completa(self):
        response = self.client.get('/reservations/create')
        pagina = response.get_data(as_text=True)
        select = self._select_teacher(pagina)
        self.assertIn('Prof Ana Criadora', select)
        self.assertIn('Prof Bruno Colega', select)

    def test_super_admin_nao_entra_no_fluxo_professor(self):
        """O curinga '*' não seleciona o fluxo de professor: o super-admin
        vê a lista completa da unidade e cria reservas aprovadas."""
        self._login(SUPER_EMAIL)
        response = self.client.get('/reservations/create')
        select = self._select_teacher(response.get_data(as_text=True))
        self.assertIn('Prof Ana Criadora', select)
        self.assertIn('Prof Bruno Colega', select)

        dia = self._dia_futuro()
        response = self.client.post('/reservations/create',
                                    data=self._payload(dia, self.prof_b_id),
                                    follow_redirects=True)
        self.assertIn('agendada com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            reserva = Reservation.query.filter_by(date=dia).one()
            self.assertEqual(reserva.status, 'approved')
            self.assertEqual(reserva.teacher_id, self.prof_b_id)

    def test_professor_nao_designa_terceiro_no_post(self):
        """POST forjado com outro docente: o SelectField valida contra as
        opções e a reserva não é criada."""
        self._login(PROF_A_EMAIL)
        response = self.client.post('/reservations/create',
                                    data=self._payload(self._dia_futuro(),
                                                       self.prof_b_id))
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(Reservation.query.count(), 0)

    def test_professor_post_sem_docente_e_rejeitado(self):
        """POST com a opção vazia (0) passa na validação do campo opcional,
        mas o fluxo de professor exige a própria designação — nada é gravado."""
        self._login(PROF_A_EMAIL)
        response = self.client.post('/reservations/create',
                                    data=self._payload(self._dia_futuro(), 0))
        self.assertEqual(response.status_code, 200)
        self.assertIn('selecione o próprio nome', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(Reservation.query.count(), 0)

    def test_edicao_mantem_docente_original_de_reserva_antiga(self):
        """Reserva antiga do professor designada a um colega: o colega segue
        na lista e regravar o formulário não perde a designação."""
        dia = self._dia_futuro()
        with self.app.app_context():
            reserva = Reservation(
                user_id=self.prof_a_id, classroom_id=self.room_id,
                course_id=self.course_id, teacher_id=self.prof_b_id,
                title='Aula Legada', date=dia,
                start_time=datetime.strptime('09:00', '%H:%M').time(),
                end_time=datetime.strptime('10:00', '%H:%M').time(),
                status='approved', unity_id=self.unity_id,
            )
            db.session.add(reserva)
            db.session.commit()
            reserva_id = reserva.id

        self._login(PROF_A_EMAIL)
        response = self.client.get(f'/reservations/{reserva_id}/edit')
        select = self._select_teacher(response.get_data(as_text=True))
        self.assertIn('Prof Ana Criadora', select)
        self.assertIn('Prof Bruno Colega', select)

        response = self.client.post(f'/reservations/{reserva_id}/edit',
                                    data=self._payload(dia, self.prof_b_id,
                                                       titulo='Aula Legada Editada'),
                                    follow_redirects=True)
        self.assertIn('Reserva atualizada', response.get_data(as_text=True))
        with self.app.app_context():
            reserva = db.session.get(Reservation, reserva_id)
            self.assertEqual(reserva.teacher_id, self.prof_b_id)
            self.assertEqual(reserva.title, 'Aula Legada Editada')

    def test_edicao_professor_nao_limpa_docente_de_reserva_antiga(self):
        """Na edição, alterar a designação (inclusive limpar com a opção
        vazia) só é aceito quando aponta para o próprio professor — a reserva
        antiga designada a um colega segue com ele."""
        dia = self._dia_futuro()
        with self.app.app_context():
            reserva = Reservation(
                user_id=self.prof_a_id, classroom_id=self.room_id,
                course_id=self.course_id, teacher_id=self.prof_b_id,
                title='Aula Legada', date=dia,
                start_time=datetime.strptime('09:00', '%H:%M').time(),
                end_time=datetime.strptime('10:00', '%H:%M').time(),
                status='approved', unity_id=self.unity_id,
            )
            db.session.add(reserva)
            db.session.commit()
            reserva_id = reserva.id

        self._login(PROF_A_EMAIL)
        response = self.client.post(f'/reservations/{reserva_id}/edit',
                                    data=self._payload(dia, 0,
                                                       titulo='Aula Legada Editada'))
        self.assertIn('só pode apontar para você mesmo',
                      response.get_data(as_text=True))
        with self.app.app_context():
            reserva = db.session.get(Reservation, reserva_id)
            self.assertEqual(reserva.teacher_id, self.prof_b_id)
            self.assertEqual(reserva.title, 'Aula Legada')


if __name__ == '__main__':
    unittest.main()
