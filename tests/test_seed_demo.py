"""Testes do comando `flask seed-demo`.

O cenário de demonstração deve cobrir cada parte do sistema: unidades com
módulos variados, todos os papéis de usuário, tipos de sala, reservas em
todas as situações, feriados, hora extra, vale-transporte, cozinha e token
da API. Também valida a idempotência (recusa duplicar) e o `--reset`.
"""
import hashlib
import os
import tempfile
import unittest
from datetime import date, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (
    ApiToken, Classroom, Course, Holiday, KitchenPreparation,
    KitchenRecipe, KitchenRecipeIngredient, Reservation, RoomCategory,
    Subject, TeacherOvertimePay, TechnicalSheet, Unity, User, VtRecord,
    user_roles,
)
from app.seed_demo import DEMO_API_TOKEN, DEMO_PASSWORD


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SeedDemoCommandTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + \
            self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
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

    def _rodar(self, *args):
        return self.app.test_cli_runner().invoke(args=['seed-demo', *args])

    # ── Cobertura do cenário ────────────────────────────────────────────────

    def test_seed_demo_popula_todos_os_modulos(self):
        result = self._rodar()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('demonstração criado', result.output.lower())

        with self.app.app_context():
            # Multi-unidade: 3 unidades, uma sem Cozinha e uma inativa
            self.assertEqual(Unity.query.count(), 3)
            norte = Unity.query.filter_by(code='DEM-NORTE').first()
            sul = Unity.query.filter_by(code='DEM-SUL').first()
            ctr = Unity.query.filter_by(code='DEM-CTR').first()
            self.assertFalse(norte.kitchen_enabled)
            self.assertFalse(sul.is_active)
            self.assertIsNotNone(ctr.weather_latitude)

            # Todos os papéis e os cantos de usuário
            self.assertEqual(User.query.filter_by(
                email='gestor.marina@demo.edu.br').one().role_obj.name, 'room_manager')
            self.assertEqual(User.query.filter_by(
                email='analista.rafael@demo.edu.br').one().role_obj.name, 'coordinator')
            ana = User.query.filter_by(email='prof.ana@demo.edu.br').one()
            self.assertTrue(ana.has_permission('kitchen:read'))
            self.assertEqual([r.name for r in ana.extra_roles], ['kitchen'])
            self.assertFalse(User.query.filter_by(
                email='prof.elisa@demo.edu.br').one().is_active_user)
            self.assertTrue(User.query.filter_by(
                email='prof.felipe@demo.edu.br').one().force_password_change)
            self.assertTrue(User.query.filter_by(
                email='func.marcos@demo.edu.br').one().is_teacher)
            # Todos os logins de demonstração aceitam a senha padrão
            for email in ('admin@school.edu', 'gestor.marina@demo.edu.br',
                          'prof.ana@demo.edu.br',
                          'func.juliana@demo.edu.br'):
                user = User.query.filter_by(email=email).one()
                self.assertTrue(user.check_password(DEMO_PASSWORD))

            # Categorias com aparência do totem + salas variadas
            self.assertGreaterEqual(RoomCategory.query.count(), 7)
            self.assertEqual(RoomCategory.query.filter_by(
                code='auditorium').one().totem_window, 'week')
            self.assertTrue(RoomCategory.query.filter_by(
                code='computer_lab').one().controla_computadores)
            salas = Classroom.query.all()
            self.assertGreaterEqual(len(salas), 17)
            inativas = [s for s in salas if not s.is_active]
            self.assertEqual(len(inativas), 1)
            self.assertEqual(inativas[0].name, 'Sala de Reunião — Direção')

            # Acadêmico: um curso inativo entre os ativos
            self.assertTrue(any(not c.is_active for c in Course.query.all()))
            self.assertGreaterEqual(Subject.query.count(), 10)

            # Feriados ativos e o exemplo inativo
            self.assertTrue(any(not h.is_active for h in Holiday.query.all()))
            self.assertTrue(any(h.is_active for h in Holiday.query.all()))

            # Reservas: todas as situações + série + sem domingo
            statuses = {r.status for r in Reservation.query.all()}
            self.assertIn('approved', statuses)
            self.assertIn('pending', statuses)
            self.assertIn('cancelled', statuses)
            self.assertTrue(all(r.date.weekday() != 6
                                for r in Reservation.query.all()))
            origem = Reservation.query.filter_by(
                title='Programação Web — Turma Noturna').first()
            self.assertIsNotNone(origem)
            self.assertEqual(Reservation.query.filter_by(
                repeat_group_id=origem.id).count(), 5)
            self.assertIsNotNone(Reservation.query.filter(
                Reservation.reviewed_by.isnot(None)).first())
            # Há reservas na unidade Norte e NENHUMA na inativa Sul
            self.assertTrue(Reservation.query.filter_by(
                unity_id=norte.id).first())
            self.assertFalse(Reservation.query.filter_by(
                unity_id=sul.id).first())

            # Financeiro: hora extra no mês base corrente + VT com grupos
            mes_atual = date.today().strftime('%Y-%m')
            self.assertEqual(TeacherOvertimePay.query.filter_by(
                month_base=mes_atual).count(), 4)
            self.assertGreaterEqual(VtRecord.query.count(), 11)
            grupos = {r.group for r in VtRecord.query.all()}
            self.assertIn('professores', grupos)
            self.assertIn('faculdade', grupos)
            self.assertIn('restaurante', grupos)
            self.assertTrue(any(r.original_name
                                for r in VtRecord.query.all()))
            self.assertEqual(VtRecord.query.filter_by(
                registration='VT-0909').count(), 2)  # matrícula repetida
            self.assertTrue(any(r.is_exportable
                                for r in VtRecord.query.all()))

            # Cozinha: receitas com escala, ingrediente inativo e ficha pendente
            self.assertEqual(TechnicalSheet.query.filter_by(
                status='pending').count(), 1)
            self.assertEqual(TechnicalSheet.query.filter_by(
                status='saved').count(), 1)
            pendente = TechnicalSheet.query.filter_by(
                status='pending').one()
            self.assertIsNotNone(pendente.parsed_data)
            self.assertIn('preparacoes', pendente.parsed_data)
            self.assertTrue(any(r.scaled_portions
                                for r in KitchenRecipe.query.all()))
            self.assertTrue(any(not i.is_active for i in
                                KitchenRecipeIngredient.query.all()))
            # Ficha salva tem arquivo DOCX real na pasta de uploads
            saved = TechnicalSheet.query.filter_by(status='saved').one()
            self.assertTrue(os.path.exists(os.path.join(
                self.app.instance_path, 'uploads', 'technical_sheets',
                saved.stored_filename)))

            # Token da API com o valor fixo documentado
            token = ApiToken.query.one()
            self.assertEqual(token.token_hash, hashlib.sha256(
                DEMO_API_TOKEN.encode('utf-8')).hexdigest())

    def test_seed_demo_refusa_rodar_duas_vezes(self):
        primeira = self._rodar()
        self.assertEqual(primeira.exit_code, 0)
        segunda = self._rodar()
        self.assertNotEqual(segunda.exit_code, 0)
        self.assertIn('--reset', segunda.output)

    def test_seed_demo_reset_recria_sem_orfaos(self):
        primeira = self._rodar()
        self.assertEqual(primeira.exit_code, 0)
        with self.app.app_context():
            reservas_antes = Reservation.query.count()
            usuarios_antes = User.query.count()

        segunda = self._rodar('--reset')
        self.assertEqual(segunda.exit_code, 0, segunda.output)
        self.assertIn('removida', segunda.output)

        with self.app.app_context():
            # Recriado integralmente (mesmas quantidades da 1ª execução)
            self.assertEqual(Reservation.query.count(), reservas_antes)
            self.assertEqual(User.query.count(), usuarios_antes)
            self.assertEqual(
                Unity.query.filter(Unity.code.like('DEM-%')).count(), 3)
            # Sem órfãos de cozinha: todo ingrediente tem preparação viva
            preparacoes = {p.id for p in KitchenPreparation.query.all()}
            self.assertTrue(all(i.preparation_id in preparacoes
                                for i in KitchenRecipeIngredient.query.all()))
            # Sem vínculos órfãos de papéis adicionais
            ids_vivos = {u.id for u in User.query.all()}
            vinculos = db.session.execute(
                db.select(user_roles.c.user_id)).scalars().all()
            self.assertTrue(all(uid in ids_vivos for uid in vinculos))
            # O token de demonstração foi recriado (1 linha)
            self.assertEqual(ApiToken.query.count(), 1)

    # ── Integração: as telas e a API enxergam o cenário ─────────────────────

    def test_seed_demo_alimenta_telas_e_api(self):
        self.assertEqual(self._rodar().exit_code, 0)
        # Mesma regra do seed: domingo não tem expediente — exibir "amanhã"
        dia_util = date.today()
        if dia_util.weekday() == 6:
            dia_util += timedelta(days=1)
        data_arg = dia_util.isoformat()
        client = self.app.test_client()

        # Portal público: cronograma, totem e busca exibem as reservas do dia
        self.assertEqual(
            client.get(f'/cronograma?data={data_arg}').status_code, 200)
        self.assertEqual(client.get('/totem/').status_code, 200)
        busca = client.get(f'/buscar-aula?data={data_arg}&q=Cozinha')
        self.assertEqual(busca.status_code, 200)
        self.assertIn('Cozinha Brasileira'.encode(), busca.data)

        # API pública anônima: payload reduzido (sem situação interna) e
        # apenas aprovadas — pendentes/canceladas ficam invisíveis
        anonima = client.get('/api/v1/reservations')
        self.assertEqual(anonima.status_code, 200)
        dados = anonima.get_json()
        self.assertFalse(dados['authenticated'])
        self.assertTrue(dados['reservations'])
        publico = dados['reservations'][0]
        self.assertNotIn('status', publico)
        self.assertNotIn('teacher', publico)
        # Com o token de demonstração: todas as situações, payload completo
        autenticada = client.get(
            '/api/v1/reservations?status=all',
            headers={'Authorization': f'Bearer {DEMO_API_TOKEN}'})
        self.assertEqual(autenticada.status_code, 200)
        dados = autenticada.get_json()
        self.assertTrue(dados['authenticated'])
        statuses = {r['status'] for r in dados['reservations']}
        self.assertIn('pending', statuses)
        self.assertIn('cancelled', statuses)
        completo = dados['reservations'][0]
        self.assertIn('teacher', completo)
        self.assertIn('unity', completo)

        # Login do gestor de demonstração e dashboard por categorias
        self.assertEqual(client.post('/login', data={
            'email': 'gestor.marina@demo.edu.br',
            'password': DEMO_PASSWORD,
        }, follow_redirects=True).status_code, 200)
        self.assertEqual(client.get('/dashboard').status_code, 200)
        self.assertEqual(client.get('/calendar/').status_code, 200)
        eventos = client.get(
            f'/calendar/api/events?start=2020-01-01&end=2030-12-31')
        self.assertEqual(eventos.status_code, 200)
        self.assertTrue(eventos.get_json())


if __name__ == '__main__':
    unittest.main()
