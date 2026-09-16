"""Testes do botão "Editar Reserva" na página de detalhes da sala.

O botão aparece nas próximas reservas da sala para quem tem
reservation:edit_all ou para o dono da reserva — e leva à rota de edição.
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role, RoomCategory,
                        Unity, User)

ADMIN_EMAIL = 'gestor@escola.edu'
DONO_EMAIL = 'dono@escola.edu'
OUTRO_EMAIL = 'outro@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ClassroomDetailEditButtonTestCase(unittest.TestCase):
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

            perm_edit = Permission(code='reservation:edit_all', module='reservation', action='edit_all')
            db.session.add(perm_edit)
            role_admin = Role(name='gestor-teste', label='Gestor Teste', permissions=[perm_edit])
            role_comum = Role(name='professor-teste', label='Professor Teste')
            db.session.add_all([role_admin, role_comum])
            db.session.flush()

            self.admin = User(email=ADMIN_EMAIL, full_name='Gestor Teste', role='room',
                              profile_type='employee', unity_id=self.unity.id,
                              role_id=role_admin.id, force_password_change=False,
                              is_active_user=True)
            self.dono = User(email=DONO_EMAIL, full_name='Dono da Reserva', role='room',
                             profile_type='teacher', unity_id=self.unity.id,
                             role_id=role_comum.id, force_password_change=False,
                             is_active_user=True)
            self.outro = User(email=OUTRO_EMAIL, full_name='Outro Usuário', role='room',
                              profile_type='employee', unity_id=self.unity.id,
                              role_id=role_comum.id, force_password_change=False,
                              is_active_user=True)
            for u in (self.admin, self.dono, self.outro):
                u.set_password(PASSWORD)
            db.session.add_all([self.admin, self.dono, self.outro])
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            self.room = Classroom(name='Sala 1', code='S1', capacity=30,
                                  unity_id=self.unity.id, category_id=category.id)
            db.session.add(self.room)
            db.session.flush()

            amanha = date.today() + timedelta(days=1)
            self.reserva = Reservation(
                user_id=self.dono.id, classroom_id=self.room.id, unity_id=self.unity.id,
                title='Reserva do Dono', date=amanha, start_time=time(8, 0),
                end_time=time(9, 0), status='approved',
            )
            db.session.add(self.reserva)
            db.session.commit()
            self.reserva_id = self.reserva.id
            self.room_id = self.room.id

        self._login_as(ADMIN_EMAIL)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login_as(self, email):
        # encerra a sessão anterior — o /login redireciona quem já está autenticado
        self.client.get('/logout')
        response = self.client.post('/login', data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _pagina_da_sala(self):
        return self.client.get(f'/classrooms/{self.room_id}').get_data(as_text=True)

    def test_admin_vem_botao_editar(self):
        page = self._pagina_da_sala()
        self.assertIn(f'/reservations/{self.reserva_id}/edit', page)
        self.assertIn('Editar Reserva', page)

    def test_dono_vem_botao_editar(self):
        self._login_as(DONO_EMAIL)
        page = self._pagina_da_sala()
        self.assertIn(f'/reservations/{self.reserva_id}/edit', page)

    def test_usuario_sem_vinculo_nao_ve_botao(self):
        self._login_as(OUTRO_EMAIL)
        page = self._pagina_da_sala()
        self.assertNotIn(f'/reservations/{self.reserva_id}/edit', page)
        # a reserva continua listada — só o botão de editar não aparece
        self.assertIn('Reserva do Dono', page)


if __name__ == '__main__':
    unittest.main()
