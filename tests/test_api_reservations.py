"""Testes da API REST de leitura de reservas (/api/v1).

Cobertura central: sem token a resposta expõe apenas data, horário, sala e
título (e só reservas aprovadas); com Bearer token (gerado no painel admin,
permissão api:manage) recebe todos os detalhes. Também cobre escopo
multi-unidade, filtros, paginação e erros em JSON.
"""
import hashlib
import secrets
import unittest
import os
import tempfile
from datetime import date, datetime, time, timedelta, timezone

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (ApiToken, Classroom, Course, Permission, Reservation,
                        Role, RoomCategory, Subject, Unity, User)

USERNAME = 'super.teste'
PASSWORD = 'SenhaForte123'
COMMON_USERNAME = 'comum.teste'
COMMON_PASSWORD = 'SenhaForte456'

PUBLIC_KEYS = {'id', 'title', 'date', 'start_time', 'end_time', 'classroom'}


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ApiReservationsTestCase(unittest.TestCase):
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
            comum_role = Role(name='comum_teste', label='Comum Teste')
            db.session.add(comum_role)
            db.session.flush()

            self.super_user = User(
                username=USERNAME, email='super@escola.edu', full_name='Super Teste',
                role='admin', profile_type='employee', role_id=super_role.id,
                force_password_change=False, is_active_user=True,
            )
            self.super_user.set_password(PASSWORD)
            db.session.add(self.super_user)

            self.comum_user = User(
                username=COMMON_USERNAME, email='comum@escola.edu',
                full_name='Comum Teste', role='viewer', profile_type='employee',
                role_id=comum_role.id, unity_id=None,  # definido abaixo (unidade 1)
                force_password_change=False, is_active_user=True,
            )
            self.comum_user.set_password(COMMON_PASSWORD)
            db.session.add(self.comum_user)

            self.teacher = User(
                username='teacher.teste', email='teacher@escola.edu',
                full_name='Prof. Teste', role='viewer', profile_type='teacher',
                force_password_change=False, is_active_user=True,
            )
            self.teacher.set_password('SenhaForte789')
            db.session.add(self.teacher)

            self.unity1 = Unity(name='Unidade Centro', code='CTR', is_active=True)
            self.unity2 = Unity(name='Unidade Norte', code='NRT', is_active=True)
            db.session.add_all([self.unity1, self.unity2])
            db.session.flush()

            self.comum_user.unity_id = self.unity1.id

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            self.classroom1 = Classroom(name='Sala 101', code='S101', capacity=30,
                                        category_id=category.id,
                                        unity_id=self.unity1.id, is_active=True)
            self.classroom2 = Classroom(name='Sala Norte 201', code='N201', capacity=20,
                                        category_id=category.id,
                                        unity_id=self.unity2.id, is_active=True)
            db.session.add_all([self.classroom1, self.classroom2])
            db.session.flush()

            self.course = Course(name='Curso Teste', code='CT01',
                                 unity_id=self.unity1.id)
            db.session.add(self.course)
            db.session.flush()
            self.subject = Subject(name='Disciplina Teste', code='DT01',
                                   course_id=self.course.id,
                                   unity_id=self.unity1.id)
            db.session.add(self.subject)
            db.session.flush()

            self.approved = Reservation(
                user_id=self.super_user.id, classroom_id=self.classroom1.id,
                title='Aula de Matemática', description='Capítulo 4',
                date=date(2026, 9, 10), start_time=time(8, 0), end_time=time(10, 0),
                status='approved', unity_id=self.unity1.id,
                teacher_id=self.teacher.id, course_id=self.course.id,
                subject_id=self.subject.id,
            )
            self.pending = Reservation(
                user_id=self.super_user.id, classroom_id=self.classroom1.id,
                title='Reunião Pendente', date=date(2026, 9, 11),
                start_time=time(14, 0), end_time=time(16, 0),
                status='pending', unity_id=self.unity1.id,
            )
            self.cancelled = Reservation(
                user_id=self.super_user.id, classroom_id=self.classroom1.id,
                title='Aula Cancelada', date=date(2026, 9, 12),
                start_time=time(8, 0), end_time=time(10, 0),
                status='cancelled', unity_id=self.unity1.id,
            )
            self.other_unity = Reservation(
                user_id=self.super_user.id, classroom_id=self.classroom2.id,
                title='Aula Norte', date=date(2026, 9, 10),
                start_time=time(8, 0), end_time=time(9, 0),
                status='approved', unity_id=self.unity2.id,
            )
            db.session.add_all([self.approved, self.pending, self.cancelled,
                                self.other_unity])
            db.session.commit()
            self.approved_id = self.approved.id
            self.pending_id = self.pending.id
            self.other_unity_id = self.other_unity.id
            self.unity1_id = self.unity1.id
            self.unity2_id = self.unity2.id
            self.classroom1_id = self.classroom1.id
            self.classroom2_id = self.classroom2.id
            self.super_user_id = self.super_user.id
            self.comum_user_id = self.comum_user.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _make_token(self, user_id, name='Token Teste', active=True,
                    expires_days=None):
        """Cria um token direto no banco e devolve o valor bruto (só aqui)."""
        raw = 'sige_' + secrets.token_urlsafe(32)
        expires_at = None
        if expires_days is not None:
            expires_at = (datetime.now(timezone.utc).replace(tzinfo=None)
                          + timedelta(days=expires_days))
        with self.app.app_context():
            db.session.add(ApiToken(name=name,
                                    token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                                    prefix=raw[:13] + '…',
                                    created_by_id=user_id,
                                    is_active=active,
                                    expires_at=expires_at))
            db.session.commit()
        return raw

    def _token_headers(self, raw):
        return {'Authorization': f'Bearer {raw}'}

    def _get_json(self, url, **kwargs):
        response = self.client.get(url, **kwargs)
        return response, response.get_json()

    # ── Anônimo: apenas campos públicos e reservas aprovadas ──

    def test_anonimo_lista_apenas_campos_publicos_e_aprovadas(self):
        response, data = self._get_json('/api/v1/reservations')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(data['authenticated'])
        self.assertEqual(data['unity_id'], self.unity1_id)  # primeira ativa

        titles = [r['title'] for r in data['reservations']]
        self.assertEqual(titles, ['Aula de Matemática'])  # sem pendente/cancelada/outra unidade

        item = data['reservations'][0]
        self.assertEqual(set(item.keys()), PUBLIC_KEYS)
        self.assertEqual(set(item['classroom'].keys()), {'id', 'code', 'name'})
        self.assertEqual(item['date'], '2026-09-10')
        self.assertEqual(item['start_time'], '08:00:00')
        self.assertEqual(item['end_time'], '10:00:00')
        self.assertEqual(item['classroom']['code'], 'S101')

    def test_anonimo_detalhe_aprovada_e_404_para_pendente(self):
        response, data = self._get_json(f'/api/v1/reservations/{self.approved_id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data.keys()), PUBLIC_KEYS)

        response, data = self._get_json(f'/api/v1/reservations/{self.pending_id}')
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', data)

    def test_anonimo_escolhe_unidade_pelo_parametro(self):
        response, data = self._get_json('/api/v1/reservations',
                                        query_string={'unity_id': self.unity2_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['unity_id'], self.unity2_id)
        self.assertEqual([r['title'] for r in data['reservations']], ['Aula Norte'])

        response, _ = self._get_json('/api/v1/reservations',
                                     query_string={'unity_id': 99999})
        self.assertEqual(response.status_code, 404)

    # ── Autenticado via Bearer token: todos os detalhes ──

    def test_bearer_token_recebe_todos_os_detalhes(self):
        raw = self._make_token(self.super_user_id)
        response, data = self._get_json('/api/v1/reservations',
                                        headers=self._token_headers(raw))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['authenticated'])

        item = data['reservations'][0]
        self.assertEqual(item['title'], 'Aula de Matemática')
        self.assertEqual(item['status'], 'approved')
        self.assertEqual(item['description'], 'Capítulo 4')
        self.assertEqual(item['teacher']['full_name'], 'Prof. Teste')
        self.assertEqual(item['created_by']['username'], USERNAME)
        self.assertEqual(item['course']['name'], 'Curso Teste')
        self.assertEqual(item['subject']['name'], 'Disciplina Teste')
        self.assertEqual(item['unity']['code'], 'CTR')
        self.assertEqual(item['classroom']['capacity'], 30)
        self.assertIn('created_at', item)
        self.assertIn('repeat_group_id', item)

    def test_token_pede_todas_as_situacoes(self):
        raw = self._make_token(self.super_user_id)
        response, data = self._get_json('/api/v1/reservations',
                                        query_string={'status': 'all'},
                                        headers=self._token_headers(raw))
        titles = {r['title'] for r in data['reservations']}
        self.assertEqual(titles, {'Aula de Matemática', 'Reunião Pendente',
                                  'Aula Cancelada'})

        response, data = self._get_json('/api/v1/reservations',
                                        query_string={'status': 'pending'},
                                        headers=self._token_headers(raw))
        self.assertEqual([r['title'] for r in data['reservations']],
                         ['Reunião Pendente'])
        self.assertEqual(data['reservations'][0]['status'], 'pending')

    def test_sessao_sem_token_recebe_payload_publico(self):
        """A sessão de navegador NÃO concede mais detalhes: o acesso completo
        exige token gerado no painel admin."""
        self.client.post('/login', data={'username': USERNAME, 'password': PASSWORD},
                         follow_redirects=True)
        response, data = self._get_json(f'/api/v1/reservations/{self.approved_id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(data.keys()), PUBLIC_KEYS)
        self.assertNotIn('description', data)

    def test_tokens_invalidos_retornam_401(self):
        raw = self._make_token(self.super_user_id)
        revogado = self._make_token(self.super_user_id, name='Revogado', active=False)
        expirado = self._make_token(self.super_user_id, name='Expirado',
                                    expires_days=-1)
        inativo = self._make_token(self.comum_user_id)  # dono será desativado
        with self.app.app_context():
            user = db.session.get(User, self.comum_user_id)
            user.is_active_user = False
            db.session.commit()

        for headers in (
            self._token_headers('sige_token-que-nao-existe'),
            self._token_headers(revogado),
            self._token_headers(expirado),
            self._token_headers(inativo),
            {'Authorization': 'Bearer '},
            {'Authorization': 'Basic ' + 'YWRtaW46YWRtaW4='},  # esquema antigo
            {'Authorization': 'Token abc'},
        ):
            response, data = self._get_json('/api/v1/reservations', headers=headers)
            self.assertEqual(response.status_code, 401)
            self.assertIn('error', data)
            self.assertEqual(response.headers.get('WWW-Authenticate'),
                             'Bearer realm="SIGerE API"')
        # sanity: o token válido continua funcionando
        response, _ = self._get_json('/api/v1/reservations',
                                     headers=self._token_headers(raw))
        self.assertEqual(response.status_code, 200)

    def test_registro_de_ultimo_uso(self):
        raw = self._make_token(self.super_user_id)
        self.client.get('/api/v1/reservations', headers=self._token_headers(raw))
        with self.app.app_context():
            token = db.session.query(ApiToken).filter_by(created_by_id=self.super_user_id).first()
            self.assertIsNotNone(token.last_used_at)

    def test_token_usuario_comum_fica_preso_a_proprias_unidade(self):
        raw = self._make_token(self.comum_user_id)
        response, data = self._get_json('/api/v1/reservations',
                                        headers=self._token_headers(raw))
        self.assertEqual(data['unity_id'], self.unity1_id)

        # ?unity_id= é ignorado para o dono do token sem permissão de trocar
        response, data = self._get_json('/api/v1/reservations',
                                        query_string={'unity_id': self.unity2_id},
                                        headers=self._token_headers(raw))
        self.assertEqual(data['unity_id'], self.unity1_id)
        self.assertEqual([r['title'] for r in data['reservations']],
                         ['Aula de Matemática'])

    def test_token_admin_escolhe_outra_unidade(self):
        raw = self._make_token(self.super_user_id)
        response, data = self._get_json('/api/v1/reservations',
                                        query_string={'unity_id': self.unity2_id},
                                        headers=self._token_headers(raw))
        self.assertEqual(data['unity_id'], self.unity2_id)
        self.assertEqual([r['title'] for r in data['reservations']], ['Aula Norte'])

    # ── Filtros e paginação ──

    def test_filtros_de_data_sala_e_periodo(self):
        raw = self._make_token(self.super_user_id)
        headers = self._token_headers(raw)

        response, data = self._get_json(
            '/api/v1/reservations',
            query_string={'status': 'all', 'start': '2026-09-11'},
            headers=headers)
        self.assertEqual({r['title'] for r in data['reservations']},
                         {'Reunião Pendente', 'Aula Cancelada'})

        response, data = self._get_json(
            '/api/v1/reservations',
            query_string={'status': 'all', 'start': '2026-09-11', 'end': '2026-09-11'},
            headers=headers)
        self.assertEqual([r['title'] for r in data['reservations']],
                         ['Reunião Pendente'])

        response, data = self._get_json(
            '/api/v1/reservations',
            query_string={'classroom_code': 'S101'}, headers=headers)
        self.assertEqual(len(data['reservations']), 1)

        response, data = self._get_json(
            '/api/v1/reservations',
            query_string={'period': 'night'}, headers=headers)
        self.assertEqual(data['reservations'], [])

        response, data = self._get_json(
            '/api/v1/reservations',
            query_string={'start': '10/09/2026'}, headers=headers)
        self.assertEqual(response.status_code, 400)

        response, data = self._get_json(
            '/api/v1/reservations',
            query_string={'status': 'qualquer'}, headers=headers)
        self.assertEqual(response.status_code, 400)

    def test_paginacao(self):
        raw = self._make_token(self.super_user_id)
        headers = self._token_headers(raw)
        response, data = self._get_json(
            '/api/v1/reservations',
            query_string={'status': 'all', 'per_page': 2, 'page': 1},
            headers=headers)
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(len(data['reservations']), 2)

        response, data = self._get_json(
            '/api/v1/reservations',
            query_string={'status': 'all', 'per_page': 2, 'page': 2},
            headers=headers)
        self.assertEqual(len(data['reservations']), 1)

    # ── Salas e erros em JSON ──

    def test_salas_publico_e_autenticado(self):
        response, data = self._get_json('/api/v1/rooms')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([r['code'] for r in data['rooms']], ['S101'])
        self.assertEqual(set(data['rooms'][0].keys()), {'id', 'code', 'name'})

        raw = self._make_token(self.super_user_id)
        response, data = self._get_json('/api/v1/rooms',
                                        headers=self._token_headers(raw))
        room = data['rooms'][0]
        self.assertEqual(room['category'], 'Sala de Aula')
        self.assertEqual(room['capacity'], 30)

    def test_erros_da_api_em_json(self):
        response, data = self._get_json('/api/v1/reservations/99999')
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', data)

        response, data = self._get_json('/api/v1/reservations',
                                        query_string={'period': 'madrugada'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', data)

    def test_cors_permite_apps_web_externas(self):
        """Apps hospedadas em outra origem (quadro de porta, painéis) leem a
        API do navegador; o preflight do fetch autenticado também passa."""
        response, _ = self._get_json('/api/v1/reservations')
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), '*')
        self.assertEqual(response.headers.get('Access-Control-Allow-Headers'),
                         'Authorization')

        response = self.client.options('/api/v1/reservations', headers={
            'Access-Control-Request-Method': 'GET',
            'Access-Control-Request-Headers': 'authorization',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('Access-Control-Allow-Origin'), '*')
        self.assertEqual(response.headers.get('Access-Control-Allow-Headers'),
                         'Authorization')


class TestRateLimitConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = True


class ApiRateLimitTestCase(unittest.TestCase):
    """429 da API deve ser JSON — o handler global de rate limit dá flash e
    redireciona ao login, comportamento que não serve para integrações."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestRateLimitConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestRateLimitConfig)
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_exceder_limite_retorna_429_em_json(self):
        last = None
        for _ in range(121):  # limite do blueprint: 120 por minuto
            last = self.client.get('/api/v1/reservations')
        self.assertEqual(last.status_code, 429)
        self.assertIn('error', last.get_json())


if __name__ == '__main__':
    unittest.main()
