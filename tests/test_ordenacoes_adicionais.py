"""Testes das ordenações adicionadas às listagens que ainda não tinham
ordenação: feriados, tipos de curso, tokens da API, grupos de notificação,
empresas de ônibus (VT), minhas reservas, busca pública, preparações e
fichas da cozinha, horas extras, vale-alimentação e adicional noturno."""
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, time, timezone

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (ApiToken, Classroom, CourseType, Holiday, KitchenPreparation,
                        KitchenRecipe, KitchenRecipeIngredient, NotificationGroup,
                        Permission, Reservation, Role, RoomCategory, TeacherMealAllowance,
                        TeacherNightShiftPay, TeacherOvertimePay, TechnicalSheet,
                        Unity, User, VtEmpresa)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'

# Códigos exigidos pelas páginas exercitadas nesta suíte.
PERMISSOES = ('holiday:read', 'course_type:read', 'api:manage',
              'notification:groups', 'vt:empresas', 'reservation:read_own',
              'kitchen:read', 'payment:read', 'meal:read', 'an:read')


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class OrdenacoesAdicionaisTestCase(unittest.TestCase):
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

            perms = [Permission(code=code, module=code.split(':')[0],
                                action=code.split(':')[1]) for code in PERMISSOES]
            db.session.add_all(perms)
            role = Role(name='tudo', label='Acesso de Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            self.gestor = User(email=EMAIL, full_name='Gestor Teste', role='room',
                               profile_type='employee', unities=[self.unity],
                               role_id=role.id, registration='500',
                               force_password_change=False, is_active_user=True)
            self.gestor.set_password(PASSWORD)
            db.session.add(self.gestor)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='sala_aula', abbr='SA')
            db.session.add(category)
            db.session.flush()
            self.sala_z = Classroom(name='Sala Zulu', code='S1', capacity=10,
                                    unity_id=self.unity.id, category_id=category.id)
            self.sala_a = Classroom(name='Sala Alfa', code='S2', capacity=100,
                                    unity_id=self.unity.id, category_id=category.id)
            db.session.add_all([self.sala_z, self.sala_a])

            # ── Feriados: datas e nomes em ordens diferentes ──
            db.session.add_all([
                Holiday(name='Feriado Zulu', date=date(2026, 5, 1), is_active=True,
                        unity_id=self.unity.id),
                Holiday(name='Feriado Alfa', date=date(2026, 12, 25), is_active=True,
                        unity_id=self.unity.id),
                Holiday(name='Feriado Meio', date=date(2026, 1, 1), is_active=False,
                        unity_id=self.unity.id),
            ])

            # ── Tipos de curso: nome e status invertidos ──
            db.session.add_all([
                CourseType(name='Tipo Zulu', is_active=True),
                CourseType(name='Tipo Alfa', is_active=False),
            ])

            # ── Tokens da API: criação, uso, expiração e status distintos ──
            # O SQLite devolve datetimes ingênuos (UTC por convenção do sistema).
            agora = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.add_all([
                ApiToken(name='Token Zulu', token_hash='z' * 64, prefix='sige_zulu…',
                         created_by_id=self.gestor.id, created_at=agora,
                         last_used_at=agora, expires_at=None),
                ApiToken(name='Token Alfa', token_hash='a' * 64, prefix='sige_alfa…',
                         created_by_id=self.gestor.id, created_at=agora - timedelta(days=1),
                         last_used_at=agora - timedelta(days=3),
                         expires_at=agora + timedelta(days=10), is_active=False),
            ])

            # ── Grupos de notificação: contagem de membros diferente ──
            outro = User(email='outro@escola.edu', full_name='Outro Funcionario',
                         role='room', profile_type='employee', unities=[self.unity],
                         force_password_change=False, is_active_user=True)
            outro.set_password(PASSWORD)
            db.session.add(outro)
            db.session.flush()
            db.session.add_all([
                NotificationGroup(name='Grupo Zulu', unity_id=self.unity.id,
                                  members=[self.gestor]),
                NotificationGroup(name='Grupo Alfa', unity_id=self.unity.id,
                                  members=[self.gestor, outro]),
            ])

            # ── Empresas de ônibus: nome e situação invertidos ──
            db.session.add_all([
                VtEmpresa(nome='Empresa Zulu', is_active=True,
                          unity_id=self.unity.id),
                VtEmpresa(nome='Empresa Alfa', is_active=False,
                          unity_id=self.unity.id),
            ])

            # ── Minhas reservas: data, sala e título em ordens diferentes ──
            db.session.add_all([
                Reservation(user_id=self.gestor.id, classroom_id=self.sala_z.id,
                            title='Reserva Zulu', date=date.today() + timedelta(days=10),
                            start_time=time(8, 0), end_time=time(10, 0),
                            status='approved', unity_id=self.unity.id),
                Reservation(user_id=self.gestor.id, classroom_id=self.sala_a.id,
                            title='Reserva Alfa', date=date.today() + timedelta(days=5),
                            start_time=time(8, 0), end_time=time(10, 0),
                            status='approved', unity_id=self.unity.id),
            ])

            # ── Salas para a busca pública: código, prédio e capacidade ──
            db.session.add_all([
                Classroom(name='Zulu Room', code='S9', capacity=50, building='B',
                          floor='2', unity_id=self.unity.id, category_id=category.id),
                Classroom(name='Alfa Room', code='S8', capacity=10, building='A',
                          floor='1', unity_id=self.unity.id, category_id=category.id),
            ])

            # ── Professores para a busca: nome, matrícula e departamento ──
            prof_z = User(email='zprof@escola.edu', full_name='Zulu Professor',
                          role='room', profile_type='teacher', unities=[self.unity],
                          registration='100', department='Depto A',
                          force_password_change=False, is_active_user=True)
            prof_z.set_password(PASSWORD)
            prof_a = User(email='aprof@escola.edu', full_name='Alfa Professor',
                          role='room', profile_type='teacher', unities=[self.unity],
                          registration='50', department='Depto B',
                          force_password_change=False, is_active_user=True)
            prof_a.set_password(PASSWORD)
            db.session.add_all([prof_z, prof_a])

            # ── Preparações da cozinha: criação, nº de preparações e de
            #    ingredientes em ordens diferentes ──
            alfa = KitchenRecipe(name='Alfa Receita', unity_id=self.unity.id,
                                 created_at=agora - timedelta(days=1))
            for i in range(2):
                prep = KitchenPreparation(name=f'Alfa Prep {i}', position=i, recipe=alfa)
                prep.ingredients.append(KitchenRecipeIngredient(
                    name='Farinha', quantity=100.0, unit='g', position=0))
            db.session.add(alfa)
            zulu = KitchenRecipe(name='Zulu Receita', unity_id=self.unity.id,
                                 created_at=agora)
            prep_z = KitchenPreparation(name='Zulu Prep', position=0, recipe=zulu)
            for i in range(3):
                prep_z.ingredients.append(KitchenRecipeIngredient(
                    name=f'Ingrediente {i}', quantity=1.0, unit='un', position=i))
            db.session.add(zulu)
            db.session.flush()

            # ── Fichas técnicas salvas: arquivo, envio e preparação distintos ──
            ficha_b = TechnicalSheet(unity_id=self.unity.id,
                                     original_filename='B ficha.docx',
                                     stored_filename='b.docx', status='saved',
                                     uploaded_by_id=self.gestor.id,
                                     uploaded_at=agora)
            db.session.add(ficha_b)
            db.session.flush()
            db.session.add(KitchenRecipe(name='Alfa Ficha', unity_id=self.unity.id,
                                         technical_sheet_id=ficha_b.id))
            ficha_a = TechnicalSheet(unity_id=self.unity.id,
                                     original_filename='A ficha.docx',
                                     stored_filename='a.docx', status='saved',
                                     uploaded_by_id=self.gestor.id,
                                     uploaded_at=agora - timedelta(days=1))
            db.session.add(ficha_a)
            db.session.flush()
            db.session.add(KitchenRecipe(name='Zulu Ficha', unity_id=self.unity.id,
                                         technical_sheet_id=ficha_a.id))

            # ── Horas extras: mês e lançamento em ordens diferentes ──
            db.session.add_all([
                TeacherOvertimePay(teacher_id=self.gestor.id, teaching_level='Superior',
                                   unity_id=self.unity.id, weekly_workload=20,
                                   hourly_value=25.5, budget_code='00.00.0000.0',
                                   shift='Noturno', month_base='2026-01',
                                   created_at=agora - timedelta(days=1)),
                TeacherOvertimePay(teacher_id=self.gestor.id, teaching_level='Superior',
                                   unity_id=self.unity.id, weekly_workload=20,
                                   hourly_value=25.5, budget_code='00.00.0000.0',
                                   shift='Noturno', month_base='2026-03',
                                   created_at=agora),
            ])

            # ── Vale-alimentação: mesmos meses, criação invertida ──
            db.session.add_all([
                TeacherMealAllowance(teacher_id=self.gestor.id, month_base='2026-01',
                                     days=5, unity_id=self.unity.id,
                                     created_at=agora - timedelta(days=1)),
                TeacherMealAllowance(teacher_id=self.gestor.id, month_base='2026-03',
                                     days=3, unity_id=self.unity.id, created_at=agora),
            ])

            # ── Adicional noturno: matrícula numérica fora de ordem léxica ──
            db.session.add_all([
                TeacherNightShiftPay(unity_id=self.unity.id, month_base='2026-01',
                                     registration='100', full_name='Zulu Professor',
                                     entitled=True, night_minutes=100,
                                     created_at=agora),
                TeacherNightShiftPay(unity_id=self.unity.id, month_base='2026-03',
                                     registration='50', full_name='Alfa Professor',
                                     entitled=True, night_minutes=90,
                                     created_at=agora - timedelta(days=1)),
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

    def _login(self):
        response = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _ordem_na_pagina(self, url, titulos):
        page = self.client.get(url).get_data(as_text=True)
        corpo = page[page.find('<tbody>'):]
        return [t for t in sorted(titulos, key=lambda t: corpo.find(t)) if corpo.find(t) != -1]

    # ---------- feriados ----------

    def test_feriados_padrao_por_data(self):
        ordem = self._ordem_na_pagina('/admin/holidays',
                                      ['Feriado Zulu', 'Feriado Alfa', 'Feriado Meio'])
        self.assertEqual(ordem, ['Feriado Meio', 'Feriado Zulu', 'Feriado Alfa'])

    def test_feriados_data_desc(self):
        ordem = self._ordem_na_pagina('/admin/holidays?ordem=data_desc',
                                      ['Feriado Zulu', 'Feriado Alfa', 'Feriado Meio'])
        self.assertEqual(ordem, ['Feriado Alfa', 'Feriado Zulu', 'Feriado Meio'])

    def test_feriados_por_nome(self):
        ordem = self._ordem_na_pagina('/admin/holidays?ordem=nome',
                                      ['Feriado Zulu', 'Feriado Alfa', 'Feriado Meio'])
        self.assertEqual(ordem, ['Feriado Alfa', 'Feriado Meio', 'Feriado Zulu'])

    def test_feriados_por_status(self):
        ordem = self._ordem_na_pagina('/admin/holidays?ordem=status',
                                      ['Feriado Zulu', 'Feriado Alfa', 'Feriado Meio'])
        self.assertEqual(ordem, ['Feriado Zulu', 'Feriado Alfa', 'Feriado Meio'])

    # ---------- tipos de curso ----------

    def test_tipos_curso_padrao_nome(self):
        ordem = self._ordem_na_pagina('/admin/course-types', ['Tipo Zulu', 'Tipo Alfa'])
        self.assertEqual(ordem, ['Tipo Alfa', 'Tipo Zulu'])

    def test_tipos_curso_nome_desc(self):
        ordem = self._ordem_na_pagina('/admin/course-types?ordem=nome_desc',
                                      ['Tipo Zulu', 'Tipo Alfa'])
        self.assertEqual(ordem, ['Tipo Zulu', 'Tipo Alfa'])

    def test_tipos_curso_status_ativo_primeiro(self):
        ordem = self._ordem_na_pagina('/admin/course-types?ordem=status',
                                      ['Tipo Zulu', 'Tipo Alfa'])
        self.assertEqual(ordem, ['Tipo Zulu', 'Tipo Alfa'])

    # ---------- tokens da API ----------

    def test_tokens_padrao_criacao_recente(self):
        ordem = self._ordem_na_pagina('/admin/api-tokens',
                                      ['Token Zulu', 'Token Alfa'])
        self.assertEqual(ordem, ['Token Zulu', 'Token Alfa'])

    def test_tokens_por_nome(self):
        ordem = self._ordem_na_pagina('/admin/api-tokens?ordem=nome',
                                      ['Token Zulu', 'Token Alfa'])
        self.assertEqual(ordem, ['Token Alfa', 'Token Zulu'])

    def test_tokens_por_expiracao_sem_validade_por_ultimo(self):
        ordem = self._ordem_na_pagina('/admin/api-tokens?ordem=expiracao',
                                      ['Token Zulu', 'Token Alfa'])
        self.assertEqual(ordem, ['Token Alfa', 'Token Zulu'])

    def test_tokens_por_ultimo_uso(self):
        ordem = self._ordem_na_pagina('/admin/api-tokens?ordem=ultimo_uso',
                                      ['Token Zulu', 'Token Alfa'])
        self.assertEqual(ordem, ['Token Zulu', 'Token Alfa'])

    def test_tokens_por_status_ativo_primeiro(self):
        ordem = self._ordem_na_pagina('/admin/api-tokens?ordem=status',
                                      ['Token Zulu', 'Token Alfa'])
        self.assertEqual(ordem, ['Token Zulu', 'Token Alfa'])

    # ---------- grupos de notificação ----------

    def test_grupos_padrao_nome(self):
        ordem = self._ordem_na_pagina('/admin/notificacoes/grupos',
                                      ['Grupo Zulu', 'Grupo Alfa'])
        self.assertEqual(ordem, ['Grupo Alfa', 'Grupo Zulu'])

    def test_grupos_mais_membros_primeiro(self):
        ordem = self._ordem_na_pagina('/admin/notificacoes/grupos?ordem=membros',
                                      ['Grupo Zulu', 'Grupo Alfa'])
        self.assertEqual(ordem, ['Grupo Alfa', 'Grupo Zulu'])

    # ---------- empresas de ônibus ----------

    def test_empresas_padrao_nome(self):
        ordem = self._ordem_na_pagina('/admin/vt-empresas',
                                      ['Empresa Zulu', 'Empresa Alfa'])
        self.assertEqual(ordem, ['Empresa Alfa', 'Empresa Zulu'])

    def test_empresas_nome_desc(self):
        ordem = self._ordem_na_pagina('/admin/vt-empresas?ordem=nome_desc',
                                      ['Empresa Zulu', 'Empresa Alfa'])
        self.assertEqual(ordem, ['Empresa Zulu', 'Empresa Alfa'])

    def test_empresas_status_ativa_primeiro(self):
        ordem = self._ordem_na_pagina('/admin/vt-empresas?ordem=status',
                                      ['Empresa Zulu', 'Empresa Alfa'])
        self.assertEqual(ordem, ['Empresa Zulu', 'Empresa Alfa'])

    # ---------- minhas reservas ----------

    def test_minhas_padrao_data_desc(self):
        ordem = self._ordem_na_pagina('/reservations/my',
                                      ['Reserva Zulu', 'Reserva Alfa'])
        self.assertEqual(ordem, ['Reserva Zulu', 'Reserva Alfa'])

    def test_minhas_data_asc(self):
        ordem = self._ordem_na_pagina('/reservations/my?ordem=data_asc',
                                      ['Reserva Zulu', 'Reserva Alfa'])
        self.assertEqual(ordem, ['Reserva Alfa', 'Reserva Zulu'])

    def test_minhas_por_sala(self):
        ordem = self._ordem_na_pagina('/reservations/my?ordem=sala',
                                      ['Reserva Zulu', 'Reserva Alfa'])
        self.assertEqual(ordem, ['Reserva Alfa', 'Reserva Zulu'])

    def test_minhas_por_titulo(self):
        ordem = self._ordem_na_pagina('/reservations/my?ordem=titulo',
                                      ['Reserva Zulu', 'Reserva Alfa'])
        self.assertEqual(ordem, ['Reserva Alfa', 'Reserva Zulu'])

    # ---------- busca pública ----------

    def test_busca_salas_padrao_codigo(self):
        ordem = self._ordem_na_pagina('/search?type=classroom&q=o',
                                      ['Zulu Room', 'Alfa Room'])
        self.assertEqual(ordem, ['Alfa Room', 'Zulu Room'])

    def test_busca_salas_por_capacidade(self):
        ordem = self._ordem_na_pagina('/search?type=classroom&q=o&ordem=capacidade',
                                      ['Zulu Room', 'Alfa Room'])
        self.assertEqual(ordem, ['Zulu Room', 'Alfa Room'])

    def test_busca_salas_por_predio(self):
        ordem = self._ordem_na_pagina('/search?type=classroom&q=o&ordem=predio',
                                      ['Zulu Room', 'Alfa Room'])
        self.assertEqual(ordem, ['Alfa Room', 'Zulu Room'])

    def test_busca_professores_padrao_nome(self):
        ordem = self._ordem_na_pagina('/search?type=teacher&q=professor',
                                      ['Zulu Professor', 'Alfa Professor'])
        self.assertEqual(ordem, ['Alfa Professor', 'Zulu Professor'])

    def test_busca_professores_por_matricula(self):
        ordem = self._ordem_na_pagina(
            '/search?type=teacher&q=professor&ordem=matricula',
            ['Zulu Professor', 'Alfa Professor'])
        # numérica: 50 antes de 100
        self.assertEqual(ordem, ['Alfa Professor', 'Zulu Professor'])

    def test_busca_professores_por_departamento(self):
        ordem = self._ordem_na_pagina(
            '/search?type=teacher&q=professor&ordem=departamento',
            ['Zulu Professor', 'Alfa Professor'])
        self.assertEqual(ordem, ['Zulu Professor', 'Alfa Professor'])

    # ---------- preparações (cozinha) ----------

    def test_preparacoes_padrao_criacao_recente(self):
        ordem = self._ordem_na_pagina('/kitchen/preparacoes',
                                      ['Zulu Receita', 'Alfa Receita'])
        self.assertEqual(ordem, ['Zulu Receita', 'Alfa Receita'])

    def test_preparacoes_por_nome(self):
        ordem = self._ordem_na_pagina('/kitchen/preparacoes?ordem=nome',
                                      ['Zulu Receita', 'Alfa Receita'])
        self.assertEqual(ordem, ['Alfa Receita', 'Zulu Receita'])

    def test_preparacoes_mais_preparacoes(self):
        ordem = self._ordem_na_pagina('/kitchen/preparacoes?ordem=preparacoes',
                                      ['Zulu Receita', 'Alfa Receita'])
        self.assertEqual(ordem, ['Alfa Receita', 'Zulu Receita'])

    def test_preparacoes_mais_ingredientes(self):
        ordem = self._ordem_na_pagina('/kitchen/preparacoes?ordem=ingredientes',
                                      ['Zulu Receita', 'Alfa Receita'])
        self.assertEqual(ordem, ['Zulu Receita', 'Alfa Receita'])

    # ---------- fichas técnicas (cozinha) ----------

    def test_fichas_padrao_envio_recente(self):
        ordem = self._ordem_na_pagina('/kitchen/fichas',
                                      ['B ficha.docx', 'A ficha.docx'])
        self.assertEqual(ordem, ['B ficha.docx', 'A ficha.docx'])

    def test_fichas_envio_antigo(self):
        ordem = self._ordem_na_pagina('/kitchen/fichas?ordem=antigas',
                                      ['B ficha.docx', 'A ficha.docx'])
        self.assertEqual(ordem, ['A ficha.docx', 'B ficha.docx'])

    def test_fichas_por_arquivo(self):
        ordem = self._ordem_na_pagina('/kitchen/fichas?ordem=arquivo',
                                      ['B ficha.docx', 'A ficha.docx'])
        self.assertEqual(ordem, ['A ficha.docx', 'B ficha.docx'])

    def test_fichas_por_preparacao(self):
        ordem = self._ordem_na_pagina('/kitchen/fichas?ordem=preparacao',
                                      ['B ficha.docx', 'A ficha.docx'])
        # "B ficha.docx" está vinculada à preparação "Alfa Ficha"
        self.assertEqual(ordem, ['B ficha.docx', 'A ficha.docx'])

    # ---------- horas extras ----------

    def test_horas_extra_padrao_lancamento_recente(self):
        ordem = self._ordem_na_pagina('/payments/overtime/list?month_base=',
                                      ['Janeiro/2026', 'Março/2026'])
        self.assertEqual(ordem, ['Março/2026', 'Janeiro/2026'])

    def test_horas_extra_por_mes(self):
        ordem = self._ordem_na_pagina('/payments/overtime/list?month_base=&ordem=mes',
                                      ['Janeiro/2026', 'Março/2026'])
        self.assertEqual(ordem, ['Janeiro/2026', 'Março/2026'])

    def test_horas_extra_por_mes_desc(self):
        ordem = self._ordem_na_pagina('/payments/overtime/list?month_base=&ordem=mes_desc',
                                      ['Janeiro/2026', 'Março/2026'])
        self.assertEqual(ordem, ['Março/2026', 'Janeiro/2026'])

    def test_horas_extra_lancamento_antigo(self):
        ordem = self._ordem_na_pagina('/payments/overtime/list?month_base=&ordem=antigas',
                                      ['Janeiro/2026', 'Março/2026'])
        self.assertEqual(ordem, ['Janeiro/2026', 'Março/2026'])

    # ---------- vale-alimentação ----------

    def test_vale_padrao_lancamento_recente(self):
        ordem = self._ordem_na_pagina('/payments/meal-allowance',
                                      ['Janeiro/2026', 'Março/2026'])
        self.assertEqual(ordem, ['Março/2026', 'Janeiro/2026'])

    def test_vale_por_mes(self):
        ordem = self._ordem_na_pagina('/payments/meal-allowance?ordem=mes',
                                      ['Janeiro/2026', 'Março/2026'])
        self.assertEqual(ordem, ['Janeiro/2026', 'Março/2026'])

    def test_vale_por_mes_desc(self):
        ordem = self._ordem_na_pagina('/payments/meal-allowance?ordem=mes_desc',
                                      ['Janeiro/2026', 'Março/2026'])
        self.assertEqual(ordem, ['Março/2026', 'Janeiro/2026'])

    # ---------- adicional noturno ----------

    def test_adicional_padrao_lancamento_recente(self):
        ordem = self._ordem_na_pagina('/adicional-noturno/',
                                      ['Zulu Professor', 'Alfa Professor'])
        self.assertEqual(ordem, ['Zulu Professor', 'Alfa Professor'])

    def test_adicional_matricula_numerica(self):
        ordem = self._ordem_na_pagina(
            '/adicional-noturno/?ordem=matricula',
            ['Zulu Professor', 'Alfa Professor'])
        # numérica: 50 antes de 100
        self.assertEqual(ordem, ['Alfa Professor', 'Zulu Professor'])

    def test_adicional_por_professor(self):
        ordem = self._ordem_na_pagina(
            '/adicional-noturno/?ordem=professor',
            ['Zulu Professor', 'Alfa Professor'])
        self.assertEqual(ordem, ['Alfa Professor', 'Zulu Professor'])

    def test_adicional_por_mes(self):
        ordem = self._ordem_na_pagina('/adicional-noturno/?ordem=mes',
                                      ['Zulu Professor', 'Alfa Professor'])
        # Zulu está em 2026-01, Alfa em 2026-03
        self.assertEqual(ordem, ['Zulu Professor', 'Alfa Professor'])

    def test_adicional_por_mes_desc(self):
        ordem = self._ordem_na_pagina(
            '/adicional-noturno/?ordem=mes_desc',
            ['Zulu Professor', 'Alfa Professor'])
        self.assertEqual(ordem, ['Alfa Professor', 'Zulu Professor'])


if __name__ == '__main__':
    unittest.main()
