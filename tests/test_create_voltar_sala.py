"""Botão "Voltar" do formulário de Nova Reserva.

Ao chegar em /reservations/create a partir da página da sala (botão
"Reservar"), a query traz ?classroom_id=N e o formulário deve oferecer o
atalho de volta para os detalhes da sala. Regressão: o template usava
request.args.get('classroom_id', type=int), mas type não existe no Jinja —
qualquer acesso COM o parâmetro derrubava a página com 500 (sem o
parâmetro, o werkzeug devolvia o default antes de tocar no type e o bug
ficava escondido).
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Role, RoomCategory, Unity,
                        User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class CreateVoltarSalaTestCase(unittest.TestCase):
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

            perm = Permission(code='reservation:create', module='reservation',
                              action='create')
            db.session.add(perm)
            role = Role(name='gestor-teste', label='Gestor Teste',
                        permissions=[perm])
            db.session.add(role)
            db.session.flush()

            user = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            room = Classroom(name='Sala 1', code='S1', capacity=30,
                             unity_id=self.unity.id, category_id=category.id)
            db.session.add(room)
            db.session.commit()
            self.room_id = room.id

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

    def test_vindo_da_sala_pagina_abre_com_voltar(self):
        """Caminho do bug: Reservar na página da sala chega com
        ?classroom_id=N — a página abre e o Voltar aponta para a sala."""
        response = self.client.get(f'/reservations/create?classroom_id={self.room_id}')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('Voltar', page)
        self.assertIn(f'href="/classrooms/{self.room_id}"', page)

    def test_sem_parametro_abre_sem_voltar(self):
        """Entrada pelo menu (sem classroom_id) segue sem o botão Voltar."""
        response = self.client.get('/reservations/create')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Voltar', response.get_data(as_text=True))

    def test_parametro_lixo_nao_quebra(self):
        """classroom_id não numérico vira 0 pelo filtro |int — página abre
        sem o botão Voltar."""
        response = self.client.get('/reservations/create?classroom_id=abc')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('Voltar', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
