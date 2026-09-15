"""Smoke test temporário: create/edit de reserva renderiza com o mapa disciplina->curso."""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Permission, Reservation, Role,
                        RoomCategory, Subject, Unity, User)

class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False

class SubjectFilterTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            perm = Permission(code='*', module='system', action='all')
            db.session.add(perm); db.session.flush()
            role = Role(name='super_sf', label='Super SF', permissions=[perm])
            db.session.add(role); db.session.flush()
            unity = Unity(name='Unidade SF', code='SF')
            db.session.add(unity); db.session.flush()
            user = User(email='sf@escola.edu', full_name='Super SF', role='admin',
                        profile_type='employee', role_id=role.id, unity_id=unity.id,
                        force_password_change=False, is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            cat = RoomCategory(name='Sala de Aula', code='sl_sf')
            db.session.add(cat); db.session.flush()
            room = Classroom(name='Sala 1', code='S1', capacity=30,
                             category_id=cat.id, unity_id=unity.id)
            db.session.add(room)
            curso = Course(name='Informatica', code='INF_SF', unity_id=unity.id)
            db.session.add(curso); db.session.flush()
            outros = Course(name='Administracao', code='ADM_SF', unity_id=unity.id)
            db.session.add(outros); db.session.flush()
            bd = Subject(name='Banco de Dados', code='BD_SF',
                         course_id=curso.id, unity_id=unity.id)
            db.session.add(bd)
            db.session.add(Subject(name='Redes', code='RD_SF',
                                   course_id=curso.id, unity_id=unity.id))
            db.session.add(Subject(name='Contabilidade', code='CT_SF',
                                   course_id=outros.id, unity_id=unity.id))
            db.session.commit()
            self.unity_id, self.room_id = unity.id, room.id
            self.curso_id, self.outros_id = curso.id, outros.id
            self.bd_id = bd.id
        self.client.post('/login', data={
            'email': 'sf@escola.edu', 'password': 'SenhaForte123'},
            follow_redirects=True)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_create_page_embeds_course_map(self):
        resp = self.client.get('/reservations/create')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('subjectCourseMap', html)
        with self.app.app_context():
            mapa = {s.name: s.course_id for s in Subject.query.all()}
        for nome, curso_id in mapa.items():
            self.assertIn(str(curso_id), html)

    def test_edit_page_renders_with_legacy_subject(self):
        # Reserva antiga: curso Administracao + disciplina Banco de Dados (Informatica)
        with self.app.app_context():
            user = User.query.filter_by(email='sf@escola.edu').first()
            res = Reservation(user_id=user.id, classroom_id=self.room_id,
                              course_id=self.outros_id, subject_id=self.bd_id,
                              title='Aula antiga', date=date.today(),
                              start_time=time(8), end_time=time(10),
                              status='approved', unity_id=self.unity_id)
            db.session.add(res); db.session.commit()
            rid = res.id
        resp = self.client.get(f'/reservations/{rid}/edit')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('userChangedCourse', html)
        self.assertIn('selected', html)

    def test_create_reservation_still_saves(self):
        # Amanhã: horários fixos não podem esbarrar na validação de
        # "horário de início no passado" quando o teste roda depois das 14h.
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        resp = self.client.post('/reservations/create', data={
            'classroom': self.room_id, 'course': self.curso_id,
            'subject': self.bd_id, 'teacher': 0, 'title': 'Aula de BD',
            'description': '', 'date': tomorrow,
            'start_time': '14:00', 'end_time': '16:00',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            res = Reservation.query.filter_by(title='Aula de BD').first()
            self.assertIsNotNone(res)
            self.assertEqual(res.course_id, self.curso_id)
            self.assertEqual(res.subject_id, self.bd_id)

if __name__ == '__main__':
    unittest.main()
