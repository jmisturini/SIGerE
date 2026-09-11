"""Testes da página admin de tokens da API (Painel → Tokens da API).

Cobre o gate pela permissão api:manage, a geração com valor exibido uma única
vez, revogação/reativação, exclusão e o uso do token gerado na API /api/v1.
"""
import os
import re
import tempfile
import unittest
from datetime import date, time

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (ApiToken, Classroom, Permission, Reservation, Role,
                        RoomCategory, Unity, User)

USERNAME = 'admin.teste'
PASSWORD = 'SenhaForte123'

TOKEN_RE = re.compile(r'id="tokenValor" value="([^"]+)"')


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ApiTokensAdminTestCase(unittest.TestCase):
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
            super_role = Role(name='super_teste', label='Super Teste',
                              permissions=[curinga])
            db.session.add(super_role)
            sem_role = Role(name='sem_teste', label='Sem Permissão')
            db.session.add(sem_role)
            db.session.flush()

            self.admin = User(username=USERNAME, email='admin@escola.edu',
                              full_name='Admin Teste', role='admin',
                              profile_type='employee', role_id=super_role.id,
                              force_password_change=False, is_active_user=True)
            self.admin.set_password(PASSWORD)
            db.session.add(self.admin)

            self.sem_permissao = User(username='sem.teste', email='sem@escola.edu',
                                      full_name='Sem Permissão', role='viewer',
                                      profile_type='employee', role_id=sem_role.id,
                                      force_password_change=False, is_active_user=True)
            self.sem_permissao.set_password('SenhaForte456')
            db.session.add(self.sem_permissao)

            unity = Unity(name='Unidade Centro', code='CTR', is_active=True)
            db.session.add(unity)
            db.session.flush()
            self.unity_id = unity.id
            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            classroom = Classroom(name='Sala 101', code='S101', capacity=30,
                                  category_id=category.id, unity_id=unity.id,
                                  is_active=True)
            db.session.add(classroom)
            db.session.flush()
            self.classroom_id = classroom.id
            db.session.add(Reservation(user_id=self.admin.id,
                                       classroom_id=classroom.id,
                                       title='Aula de Teste', date=date(2026, 9, 10),
                                       start_time=time(8, 0), end_time=time(10, 0),
                                       status='approved', unity_id=unity.id))
            db.session.commit()
            self.admin_id = self.admin.id

        self._login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, username=USERNAME, password=PASSWORD):
        response = self.client.post('/login',
                                    data={'username': username, 'password': password},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_pagina_exige_permissao_api_manage(self):
        response = self.client.get('/admin/api-tokens')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Tokens da API', response.get_data(as_text=True))

        outro = self.app.test_client()
        outro.post('/login', data={'username': 'sem.teste', 'password': 'SenhaForte456'},
                   follow_redirects=True)
        response = outro.get('/admin/api-tokens')
        self.assertEqual(response.status_code, 403)

    def test_gerar_token_exibe_valor_uma_vez(self):
        response = self.client.post('/admin/api-tokens/create',
                                    data={'name': 'Painel porta S101', 'duration': 0})
        page = response.get_data(as_text=True)
        match = TOKEN_RE.search(page)
        self.assertIsNotNone(match, 'Valor completo do token deve aparecer na página')
        raw = match.group(1)
        self.assertTrue(raw.startswith('sige_'))

        with self.app.app_context():
            tokens = ApiToken.query.all()
            self.assertEqual(len(tokens), 1)
            token = tokens[0]
            self.assertEqual(token.name, 'Painel porta S101')
            # banco guarda apenas o hash — o valor bruto não é recuperável
            self.assertNotIn(raw, token.token_hash)
            self.assertEqual(len(token.token_hash), 64)
            self.assertIsNone(token.expires_at)
            self.assertEqual(token.prefix, raw[:13] + '…')
        # exibição da listagem: valor bruto some, prefixo aparece
        response = self.client.get('/admin/api-tokens')
        page = response.get_data(as_text=True)
        self.assertNotIn(raw, page)
        self.assertIn(token.prefix if hasattr(token, 'prefix') else '', page)

    def test_token_gerado_autentica_a_api(self):
        response = self.client.post('/admin/api-tokens/create',
                                    data={'name': 'Integração', 'duration': 0})
        raw = TOKEN_RE.search(response.get_data(as_text=True)).group(1)

        response = self.client.get('/api/v1/reservations',
                                   headers={'Authorization': f'Bearer {raw}'})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['authenticated'])
        self.assertEqual(data['reservations'][0]['status'], 'approved')
        self.assertIn('teacher', data['reservations'][0])

    def test_token_com_validade(self):
        self.client.post('/admin/api-tokens/create',
                         data={'name': 'Token 30 dias', 'duration': 30})
        with self.app.app_context():
            token = ApiToken.query.first()
            self.assertIsNotNone(token.expires_at)
            delta = token.expires_at - token.created_at.replace(tzinfo=None)
            self.assertAlmostEqual(delta.total_seconds(), 30 * 86400, delta=60)

    def test_nome_curto_e_rejeitado(self):
        response = self.client.post('/admin/api-tokens/create',
                                    data={'name': 'ab', 'duration': 0},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(ApiToken.query.count(), 0)

    def test_revogar_e_reativar_token(self):
        response = self.client.post('/admin/api-tokens/create',
                                    data={'name': 'Para revogar', 'duration': 0})
        raw = TOKEN_RE.search(response.get_data(as_text=True)).group(1)
        with self.app.app_context():
            token_id = ApiToken.query.first().id

        response = self.client.post(f'/admin/api-tokens/{token_id}/toggle',
                                    follow_redirects=True)
        self.assertIn('revogado', response.get_data(as_text=True))

        api = self.client.get('/api/v1/reservations',
                              headers={'Authorization': f'Bearer {raw}'})
        self.assertEqual(api.status_code, 401)

        self.client.post(f'/admin/api-tokens/{token_id}/toggle')
        api = self.client.get('/api/v1/reservations',
                              headers={'Authorization': f'Bearer {raw}'})
        self.assertEqual(api.status_code, 200)
        self.assertTrue(api.get_json()['authenticated'])

    def test_excluir_token(self):
        response = self.client.post('/admin/api-tokens/create',
                                    data={'name': 'Para excluir', 'duration': 0})
        raw = TOKEN_RE.search(response.get_data(as_text=True)).group(1)
        with self.app.app_context():
            token_id = ApiToken.query.first().id

        self.client.post(f'/admin/api-tokens/{token_id}/delete', follow_redirects=True)
        with self.app.app_context():
            self.assertEqual(ApiToken.query.count(), 0)

        api = self.client.get('/api/v1/reservations',
                              headers={'Authorization': f'Bearer {raw}'})
        self.assertEqual(api.status_code, 401)

    def test_ultimo_uso_aparece_na_listagem(self):
        response = self.client.post('/admin/api-tokens/create',
                                    data={'name': 'Uso registrado', 'duration': 0})
        raw = TOKEN_RE.search(response.get_data(as_text=True)).group(1)
        self.client.get('/api/v1/reservations',
                        headers={'Authorization': f'Bearer {raw}'})
        response = self.client.get('/admin/api-tokens')
        self.assertNotIn('>nunca<', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
