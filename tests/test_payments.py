"""Testes do módulo de Hora Extra (pagamentos).

Cobre as regras atuais do módulo Financeiro:
- Mês de referência pela janela de lançamento (dia 21 do mês anterior a dia 20
  do mês corrente conta para o mês atual; depois disso, para o próximo) — e a
  exceção: selecionar o próximo mês no Mês de Referência inclui a entrada no
  próximo mês de pagamento;
- O campo Mês do formulário segue o mês de referência (oferece o mês anterior
  a ele e o próprio) e limita o calendário; os dias são gravados sem mês/ano,
  com o mês das datas na coluna dates_month (nulo nos lançamentos antigos,
  cujos dias pertencem ao mês base);
- Fechamento do mês (permissão payment:close_month): baixa a planilha final e
  tranca edição/exclusão dos lançamentos daquele mês — lançamentos do mês
  seguinte permanecem editáveis; a consulta abre no mês atual do calendário;
- Carga horária exibida e exportada em hora/minuto inteiros (4h30), sem
  conversão para hora decimal;
- Consulta com caixa de seleção de meses e opção "Todos os meses"; exportação
  filtrada por professor;
- Máscara do Código Orçamentário (xx.xx.xxxx.x e xx.xx.xxxx.xx.xxxx);
- Aviso de navegador removido das duas páginas do módulo.
"""
import os
import re
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from openpyxl import load_workbook

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (CourseType, OvertimeMonthClosure, Permission, Role,
                        TeacherOvertimePay, Unity, User)

EMAIL = 'financeiro@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class FixedDatetime(datetime):
    """datetime com now() fixado no dia 10 do mês corrente real: dentro da
    janela 20→20, o mês da janela é sempre o mês atual."""
    @classmethod
    def now(cls):
        today = datetime.now()
        return cls(today.year, today.month, 10, 12, 0)


class FixedDatetimeDia25(datetime):
    """now() fixado no dia 25 do mês corrente real: depois do dia 20, a janela
    aponta para o mês seguinte."""
    @classmethod
    def now(cls):
        today = datetime.now()
        return cls(today.year, today.month, 25, 12, 0)


class PaymentsTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        # O cliente de teste fala HTTP puro; cookie Secure impediria a sessão.
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        # Relógio do blueprint fixado no dia 10: a janela 20→20 aponta sempre
        # para o mês atual, tornando os testes independentes do dia de execução.
        patcher = patch('app.blueprints.payments.datetime', FixedDatetime)
        patcher.start()
        self.addCleanup(patcher.stop)

        with self.app.app_context():
            db.create_all()
            self.unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(self.unity)
            db.session.flush()

            perms = [Permission(code=code, module='payment', action=code.split(':')[1])
                     for code in ('payment:read', 'payment:create', 'payment:edit',
                                  'payment:delete', 'payment:export', 'payment:close_month')]
            db.session.add_all(perms)
            role = Role(name='financeiro-teste', label='Financeiro Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            manager = User(
                email='financeiro@escola.edu', full_name='Financeiro Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            manager.set_password(PASSWORD)
            teacher = User(
                email='prof@escola.edu', full_name='Professora Teste',
                role='viewer', profile_type='teacher', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            teacher.set_password(PASSWORD)
            other_teacher = User(
                email='prof2@escola.edu', full_name='Outro Professor',
                role='viewer', profile_type='teacher', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            other_teacher.set_password(PASSWORD)
            db.session.add_all([manager, teacher, other_teacher])
            db.session.flush()

            self.course_type = CourseType(name='Técnico', is_active=True)
            db.session.add(self.course_type)
            db.session.commit()
            self.teacher_id, self.other_teacher_id = teacher.id, other_teacher.id
            self.unity_id = self.unity.id
            self.course_type_id = self.course_type.id

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

    def _create_payload(self, **overrides):
        payload = {
            'teacher': str(self.teacher_id),
            'teaching_level': 'Superior',
            'course_type': str(self.course_type_id),
            'shift': 'Noturno',
            'weekly_workload_hours': '4',
            'weekly_workload_minutes': '30',
            'hourly_value': '25,50',
            'budget_code': '950001234',
            'multiple_dates': '10, 17',
            'justification': 'Substituicao de aula',
            'observation': 'Turma integral',
        }
        payload.update(overrides)
        return payload

    def _mes_atual(self):
        return datetime.now().strftime('%Y-%m')

    def _mes_seguinte(self):
        hoje = datetime.now()
        mes = hoje.month + 1
        ano = hoje.year + (1 if mes > 12 else 0)
        return f'{ano:04d}-{1 if mes > 12 else mes:02d}'

    def _mes_anterior(self):
        hoje = datetime.now()
        mes = hoje.month - 1
        ano = hoje.year - (1 if mes < 1 else 0)
        return f'{ano:04d}-{12 if mes < 1 else mes:02d}'

    def _add_overtime(self, month_base, teacher_id=None, budget_code='950001234', created_at=None,
                      weekly_workload=4, course_type_id='SET', observation=None):
        with self.app.app_context():
            record = TeacherOvertimePay(
                teacher_id=teacher_id or self.teacher_id, teaching_level='Superior',
                course_type_id=self.course_type_id if course_type_id == 'SET' else course_type_id,
                unity_id=self.unity_id, weekly_workload=weekly_workload, hourly_value=25.5,
                budget_code=budget_code, shift='Noturno', month_base=month_base,
                observation=observation,
            )
            if created_at is not None:
                record.created_at = created_at
            db.session.add(record)
            db.session.commit()
            return record.id

    def _fechar_mes(self, month_base):
        with self.app.app_context():
            db.session.add(OvertimeMonthClosure(
                unity_id=self.unity_id, month_base=month_base))
            db.session.commit()

    # ---------- Máscara do Código Orçamentário ----------

    def test_format_budget_code(self):
        from app.blueprints.payments import format_budget_code
        self.assertEqual(format_budget_code('950001234'), '95.00.0123.4')
        self.assertEqual(format_budget_code('95000123401234'), '95.00.0123.40.1234')
        self.assertEqual(format_budget_code('95.00.0123.4'), '95.00.0123.4')
        # 10 dígitos não existe: volta sem alteração (a validação rejeita)
        self.assertEqual(format_budget_code('9500012340'), '9500012340')
        self.assertEqual(format_budget_code('12345'), '12345')
        self.assertIsNone(format_budget_code(None))

    def test_hours_minutes_filter(self):
        from app.blueprints.payments import hours_minutes_filter
        self.assertEqual(hours_minutes_filter(Decimal('4.50')), '4h30')
        self.assertEqual(hours_minutes_filter(Decimal('4.33')), '4h20')
        self.assertEqual(hours_minutes_filter(4), '4h')
        self.assertEqual(hours_minutes_filter(None), '—')

    # ---------- Cadastro: mês base derivado da janela 20→20 ----------

    def test_create_deriva_mes_base_da_janela(self):
        # Dia 10 (antes do dia 20): o lançamento conta para o mês corrente.
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.month_base, self._mes_atual())

    def test_create_apos_dia_20_conta_para_o_mes_seguinte(self):
        with patch('app.blueprints.payments.datetime', FixedDatetimeDia25):
            response = self.client.post('/payments/overtime/create',
                                        data=self._create_payload(), follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.month_base, self._mes_seguinte())

    def test_create_current_month_succeeds_and_formats_budget_code(self):
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.budget_code, '95.00.0123.4')

    def test_create_accepts_masked_budget_code(self):
        # O campo formatado pela máscara (com pontos) passa na validação
        # e é normalizado no banco.
        response = self.client.post('/payments/overtime/create', data=self._create_payload(
            budget_code='95.00.0123.40.1234'), follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.budget_code, '95.00.0123.40.1234')

    # ---------- Tipo de curso (obrigatório) e observação ----------

    def test_create_exige_tipo_de_curso(self):
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(course_type='0'),
                                    follow_redirects=True)
        self.assertIn('Selecione o tipo de curso', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.query(TeacherOvertimePay).count(), 0)

    def test_create_salva_tipo_de_curso_e_observacao(self):
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(), follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.course_type_id, self.course_type_id)
            self.assertEqual(record.observation, 'Turma integral')
        # Campos também aparecem nos detalhes do lançamento
        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertIn('Técnico', page)
        self.assertIn('Turma integral', page)

    def test_create_referencia_proximo_mes_anteipa_entrada(self):
        # Dia 10 (dentro da janela do mês atual): selecionar o próximo mês no
        # Mês de Referência inclui a entrada no próximo mês de pagamento.
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(
                                        reference_month=self._mes_seguinte()),
                                    follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.month_base, self._mes_seguinte())

    def test_create_apos_dia_20_mes_atual_postado_conta_proximo(self):
        # Depois do dia 20 a janela já aponta para o mês seguinte: selecionar
        # o mês atual no Mês de Referência não traz a entrada de volta.
        with patch('app.blueprints.payments.datetime', FixedDatetimeDia25):
            response = self.client.post('/payments/overtime/create',
                                        data=self._create_payload(
                                            reference_month=self._mes_atual()),
                                        follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.month_base, self._mes_seguinte())

    def test_form_mostra_mes_referencia_selecionavel(self):
        page = self.client.get('/payments/overtime/create').get_data(as_text=True)
        self.assertIn('Mês de Referência', page)
        self.assertIn('id="reference_month"', page)
        # Opções: mês atual (selecionado pela janela) e mês seguinte
        self.assertRegex(page, rf'<option value="{self._mes_atual()}" selected>')
        self.assertRegex(page, rf'<option value="{self._mes_seguinte()}"')
        # Dica da janela segue presente no topo do formulário
        self.assertIn('dia 20 do mês', page)

    def test_form_campo_mes_oferece_anterior_e_atual(self):
        # Com a referência padrão (mês atual pela janela), o campo Mês oferece
        # o mês anterior e o próprio mês de referência, já selecionado.
        page = self.client.get('/payments/overtime/create').get_data(as_text=True)
        self.assertIn('id="dates_month"', page)
        bloco = re.search(r'<select name="dates_month".*?</select>', page, re.S).group(0)
        self.assertIn(f'value="{self._mes_anterior()}"', bloco)
        self.assertIn(f'value="{self._mes_atual()}"', bloco)
        self.assertRegex(bloco, rf'<option value="{self._mes_atual()}" selected>')
        self.assertNotIn(self._mes_seguinte(), bloco)

    def test_form_campo_mes_segue_referencia_proximo(self):
        # Com o próximo mês selecionado no Mês de Referência (POST reexibido
        # com erro de validação), o campo Mês passa a oferecer o mês atual e o
        # próximo — não mais o anterior ao mês atual.
        payload = self._create_payload(teacher='', reference_month=self._mes_seguinte())
        page = self.client.post('/payments/overtime/create', data=payload).get_data(as_text=True)
        bloco = re.search(r'<select name="dates_month".*?</select>', page, re.S).group(0)
        self.assertIn(f'value="{self._mes_atual()}"', bloco)
        self.assertIn(f'value="{self._mes_seguinte()}"', bloco)
        self.assertRegex(bloco, rf'<option value="{self._mes_seguinte()}" selected>')
        self.assertNotIn(self._mes_anterior(), bloco)

    def test_create_grava_mes_das_datas(self):
        # O mês das datas selecionado é gravado ao lado dos dias: referência no
        # próximo mês com datas do mês atual (mês anterior à referência).
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(
                                        reference_month=self._mes_seguinte(),
                                        dates_month=self._mes_atual(),
                                        multiple_dates='25, 28'),
                                    follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.month_base, self._mes_seguinte())
            self.assertEqual(record.dates_month, self._mes_atual())
            self.assertEqual(record.multiple_dates, '25, 28')

    def test_create_sem_mes_das_datas_grava_nulo(self):
        # Sem o campo Mês no POST (JavaScript desligado), o mês das datas fica
        # nulo e a edição assume os dias no mês base.
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(), follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertIsNone(record.dates_month)

    def test_create_recusa_mes_das_datas_invalido(self):
        # Mês das datas fora do par (referência e anterior) não é gravado.
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(dates_month='2020-01'),
                                    follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertIsNone(record.dates_month)

    # ---------- Carga horária semanal: hora + minuto, sem decimal ----------

    def test_create_form_has_hours_minutes_fields_and_hint(self):
        page = self.client.get('/payments/overtime/create').get_data(as_text=True)
        self.assertIn('id="weekly_workload_hours"', page)
        self.assertIn('id="weekly_workload_minutes"', page)
        self.assertIn('id="workload-hint"', page)

    def test_create_grava_carga_e_listagem_mostra_hora_minuto(self):
        # 4h30 é gravado internamente como 4,5 — e exibido como 4h30, sem
        # hora decimal em lugar nenhum.
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(), follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.weekly_workload, Decimal('4.50'))

        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertIn('<td>4h30</td>', page)
        self.assertNotIn('4,5', page)

    def test_list_modal_shows_hours_and_launch_date(self):
        self._add_overtime(self._mes_atual(), weekly_workload=Decimal('4.50'))
        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertIn('4h30', page)
        # Dia de lançamento nos detalhes
        self.assertIn('Data do Lançamento', page)

    def test_create_rejects_minutes_out_of_range(self):
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(weekly_workload_minutes='75'),
                                    follow_redirects=True)
        self.assertIn('Os minutos devem estar entre 0 e 59.', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.query(TeacherOvertimePay).count(), 0)

    def test_create_rejects_zero_workload(self):
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(weekly_workload_hours='0',
                                                              weekly_workload_minutes='0'),
                                    follow_redirects=True)
        self.assertIn('Carga Horária Semanal deve ser maior que 0', response.get_data(as_text=True))

    def test_export_writes_hours_and_minutes(self):
        # A planilha recebe hora e minutos inteiros (4h30) — sem decimal
        self._add_overtime(self._mes_atual(), weekly_workload=Decimal('4.50'))
        response = self.client.get(f'/payments/export/overtime?teacher_filter={self.teacher_id}')
        workbook = load_workbook(BytesIO(response.data))
        ws = workbook['Extra NEB']
        self.assertEqual(ws.cell(row=7, column=4).value, '4h30')

    def test_export_ordem_das_colunas_no_modelo(self):
        # Cabeçalhos do modelo institucional na ordem esperada, com o Tipo de
        # Curso logo após o Nível de Docência e a Observação no fim.
        self._add_overtime(self._mes_atual())
        response = self.client.get(f'/payments/export/overtime?teacher_filter={self.teacher_id}')
        workbook = load_workbook(BytesIO(response.data))
        ws = workbook['Extra NEB']
        esperados = ['Nome do Professor', 'Nível de Docência', 'Tipo de Curso',
                     'Número de Horas', 'Valor H/a', 'Datas', 'Turno',
                     'Código Orçamentário', 'Justificativa', 'Observação']
        for coluna, esperado in enumerate(esperados, start=1):
            self.assertEqual(ws.cell(row=6, column=coluna).value, esperado)

    def test_export_inclui_tipo_de_curso_e_observacao(self):
        self._add_overtime(self._mes_atual(), observation='Turma integral')
        response = self.client.get(f'/payments/export/overtime?teacher_filter={self.teacher_id}')
        workbook = load_workbook(BytesIO(response.data))
        ws = workbook['Extra NEB']
        self.assertEqual(ws.cell(row=7, column=3).value, 'Técnico')
        self.assertEqual(ws.cell(row=7, column=10).value, 'Turma integral')

    def test_edit_get_splits_decimal_into_hours_minutes(self):
        # 4.33 volta para o formulário como 4h20
        record_id = self._add_overtime(self._mes_atual(), weekly_workload=Decimal('4.33'))
        page = self.client.get(f'/payments/overtime/edit/{record_id}').get_data(as_text=True)
        self.assertRegex(page, r'id="weekly_workload_hours"[^>]*value="4"')
        self.assertRegex(page, r'id="weekly_workload_minutes"[^>]*value="20"')

    def test_edit_selects_the_record_teacher(self):
        # O relationship TeacherOvertimePay.teacher (objeto User) tem o mesmo
        # nome do campo teacher: o WTForms tenta int(User), falha em silêncio
        # e a seleção cai no primeiro professor da lista. "Professora Teste"
        # não é a primeira da lista ("Outro Professor" vem antes).
        record_id = self._add_overtime(self._mes_atual())
        page = self.client.get(f'/payments/overtime/edit/{record_id}').get_data(as_text=True)
        opcao = re.search(rf'<option[^>]*value="{self.teacher_id}"[^>]*>', page)
        self.assertIsNotNone(opcao, 'option do professor do lançamento não encontrada')
        self.assertIn('selected', opcao.group(0))

    def test_edit_restaura_tipo_de_curso(self):
        # Mesmo padrão do professor: o relationship course_type (objeto) tem o
        # nome do campo — a rota restaura a seleção pelo id.
        record_id = self._add_overtime(self._mes_atual())
        page = self.client.get(f'/payments/overtime/edit/{record_id}').get_data(as_text=True)
        opcao = re.search(rf'<option[^>]*value="{self.course_type_id}"[^>]*>', page)
        self.assertIsNotNone(opcao, 'option do tipo de curso não encontrada')
        self.assertIn('selected', opcao.group(0))

    def test_edit_stores_converted_decimal(self):
        record_id = self._add_overtime(self._mes_atual())
        response = self.client.post(f'/payments/overtime/edit/{record_id}',
                                    data=self._create_payload(weekly_workload_hours='2',
                                                              weekly_workload_minutes='45'),
                                    follow_redirects=True)
        self.assertIn('Alteração realizada', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.get(TeacherOvertimePay, record_id)
            self.assertEqual(record.weekly_workload, Decimal('2.75'))

    # ---------- Consulta: mês da janela como padrão ----------

    def test_list_defaults_to_current_month(self):
        self._add_overtime(self._mes_atual())
        self._add_overtime('2024-08', teacher_id=self.other_teacher_id)

        # Sem parâmetros: abre no mês da janela (mês atual com o relógio fixo)
        response = self.client.get('/payments/overtime/list')
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('<td class="ps-4 fw-bold">Professora Teste</td>', page)  # mês atual na tabela
        self.assertNotIn('<td class="ps-4 fw-bold">Outro Professor</td>', page)  # mês antigo de fora

        # Selecionar o mês antigo na caixa de seleção traz o registro
        response = self.client.get('/payments/overtime/list?month_base=2024-08')
        self.assertIn('<td class="ps-4 fw-bold">Outro Professor</td>', response.get_data(as_text=True))

        # "Todos os meses" (valor vazio) traz tudo
        response = self.client.get('/payments/overtime/list?month_base=')
        page = response.get_data(as_text=True)
        self.assertIn('Professora Teste', page)
        self.assertIn('Outro Professor', page)
        self.assertIn('Todos os meses', page)

    def test_list_shows_budget_code_formatted(self):
        # Registro antigo (criado direto no banco, sem máscara) aparece formatado
        self._add_overtime(self._mes_atual(), budget_code='950001234')
        response = self.client.get('/payments/overtime/list?month_base=')
        self.assertIn('95.00.0123.4', response.get_data(as_text=True))

    def test_list_abre_no_mes_atual_do_calendario_apos_dia_20(self):
        # Depois do dia 20, a consulta abre no mês atual do calendário — não no
        # mês da janela, que já virou o mês seguinte. É o mês que o Fechar Mês
        # tranca por padrão.
        self._add_overtime(self._mes_atual())
        self._add_overtime(self._mes_seguinte(), teacher_id=self.other_teacher_id)
        with patch('app.blueprints.payments.datetime', FixedDatetimeDia25):
            page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertIn('<td class="ps-4 fw-bold">Professora Teste</td>', page)
        self.assertNotIn('<td class="ps-4 fw-bold">Outro Professor</td>', page)

    def test_list_mostra_periodo_de_lancamento(self):
        # A dica da consulta informa o período do mês visualizado: do dia 21
        # do mês anterior ao dia 20 do próprio mês.
        page = self.client.get('/payments/overtime/list?month_base=2024-08').get_data(as_text=True)
        self.assertIn('Período de lançamento', page)
        self.assertIn('Agosto/2024', page)
        self.assertIn('21/07/2024', page)
        self.assertIn('20/08/2024', page)

    def test_list_periodo_vira_o_ano(self):
        # Janeiro reúne o que foi lançado do dia 21 de dezembro do ano anterior.
        page = self.client.get('/payments/overtime/list?month_base=2026-01').get_data(as_text=True)
        self.assertIn('21/12/2025', page)
        self.assertIn('20/01/2026', page)

    def test_list_periodo_para_todos_os_meses(self):
        # Sem mês filtrado, a dica não aponta um período específico.
        page = self.client.get('/payments/overtime/list?month_base=').get_data(as_text=True)
        self.assertIn('Mostrando os lançamentos de todos os períodos.', page)

    # ---------- Exportação por professor ----------

    def test_export_filtered_by_teacher(self):
        self._add_overtime(self._mes_atual())
        self._add_overtime('2024-08', teacher_id=self.other_teacher_id)

        response = self.client.get(f'/payments/export/overtime?teacher_filter={self.teacher_id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response.content_type)

        workbook = load_workbook(BytesIO(response.data))
        ws = workbook['Extra NEB']
        names = [ws.cell(row=row, column=1).value for row in range(7, ws.max_row + 1)]
        self.assertIn('Professora Teste', names)
        self.assertNotIn('Outro Professor', names)
        # Código Orçamentário sai formatado mesmo para registros antigos
        self.assertEqual(ws.cell(row=7, column=8).value, '95.00.0123.4')

    # ---------- Fechamento do mês ----------

    def test_list_shows_edit_delete_for_open_month(self):
        self._add_overtime(self._mes_atual())

        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        # O cadeado das linhas (não o ícone do botão Fechar Mês)
        self.assertNotIn('bi-lock-fill text-muted', page)
        self.assertIn('/payments/overtime/edit/', page)
        self.assertIn('/payments/overtime/delete/', page)

    def test_fechar_mes_baixa_planilha_e_tranca(self):
        record_id = self._add_overtime(self._mes_atual(), weekly_workload=Decimal('4.50'))

        response = self.client.post('/payments/overtime/close-month',
                                    data={'month_base': self._mes_atual()})
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response.content_type)
        workbook = load_workbook(BytesIO(response.data))
        ws = workbook['Extra NEB']
        self.assertEqual(ws.cell(row=7, column=4).value, '4h30')

        with self.app.app_context():
            closure = db.session.query(OvertimeMonthClosure).one()
            self.assertEqual(closure.month_base, self._mes_atual())
            self.assertIsNotNone(closure.closed_by_id)

        # A listagem mostra o cadeado e o aviso de mês fechado
        page = self.client.get(f'/payments/overtime/list?month_base={self._mes_atual()}').get_data(as_text=True)
        self.assertIn('bi-lock-fill text-muted', page)
        self.assertIn('somente leitura', page)
        self.assertNotIn('/payments/overtime/edit/', page)

        # E o backend bloqueia edição/exclusão dos lançamentos do mês
        response = self.client.get(f'/payments/overtime/edit/{record_id}', follow_redirects=True)
        self.assertIn('já foi fechado', response.get_data(as_text=True))
        response = self.client.post(f'/payments/overtime/delete/{record_id}', follow_redirects=True)
        self.assertIn('não pode mais ser excluído', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.query(TeacherOvertimePay).count(), 1)

    def test_fechar_mes_sem_lancamentos_recusado(self):
        response = self.client.post('/payments/overtime/close-month',
                                    data={'month_base': '2024-08'},
                                    follow_redirects=True)
        self.assertIn('Não há lançamentos', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.query(OvertimeMonthClosure).count(), 0)

    def test_fechar_mes_ja_fechado_nao_duplica(self):
        self._fechar_mes(self._mes_atual())
        self._add_overtime(self._mes_atual())
        response = self.client.post('/payments/overtime/close-month',
                                    data={'month_base': self._mes_atual()},
                                    follow_redirects=True)
        self.assertIn('já estavam fechados', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.query(OvertimeMonthClosure).count(), 1)

    def test_fechar_mes_exige_permissao(self):
        self._add_overtime(self._mes_atual())
        with self.app.app_context():
            role = Role.query.filter_by(name='financeiro-teste').first()
            role.permissions = [p for p in role.permissions if p.code != 'payment:close_month']
            db.session.commit()
        response = self.client.post('/payments/overtime/close-month',
                                    data={'month_base': self._mes_atual()})
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertEqual(db.session.query(OvertimeMonthClosure).count(), 0)

    def test_botao_fechar_mes_somente_com_permissao(self):
        self._add_overtime(self._mes_atual())
        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertIn('Fechar Mês', page)

        with self.app.app_context():
            role = Role.query.filter_by(name='financeiro-teste').first()
            role.permissions = [p for p in role.permissions if p.code != 'payment:close_month']
            db.session.commit()
        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertNotIn('Fechar Mês', page)

    def test_list_hides_edit_delete_para_mes_fechado(self):
        self._add_overtime(self._mes_atual())
        self._fechar_mes(self._mes_atual())

        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertIn('bi-lock-fill text-muted', page)
        self.assertNotIn('/payments/overtime/edit/', page)
        self.assertNotIn('/payments/overtime/delete/', page)

    def test_fechar_mes_atual_mantem_proximo_editavel(self):
        # O fechamento tranca apenas o mês fechado: os lançamentos do mês
        # seguinte continuam visíveis, editáveis e excluíveis.
        self._add_overtime(self._mes_atual())
        proximo_id = self._add_overtime(self._mes_seguinte(),
                                        teacher_id=self.other_teacher_id)

        response = self.client.post('/payments/overtime/close-month',
                                    data={'month_base': self._mes_atual()})
        self.assertEqual(response.status_code, 200)

        page = self.client.get(
            f'/payments/overtime/list?month_base={self._mes_atual()}').get_data(as_text=True)
        self.assertIn('bi-lock-fill text-muted', page)
        self.assertNotIn('/payments/overtime/edit/', page)

        page = self.client.get(
            f'/payments/overtime/list?month_base={self._mes_seguinte()}').get_data(as_text=True)
        self.assertNotIn('bi-lock-fill text-muted', page)
        self.assertIn(f'/payments/overtime/edit/{proximo_id}', page)
        self.assertIn(f'/payments/overtime/delete/{proximo_id}', page)

        # O backend também permite editar o lançamento do mês seguinte
        response = self.client.get(f'/payments/overtime/edit/{proximo_id}')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('já foi fechado', response.get_data(as_text=True))

    def test_edit_legado_restaura_datas_no_mes_base(self):
        # Registro antigo com apenas os dias ("10, 17"): o campo Mês volta no
        # mês base do lançamento, onde o calendário restaura os dias.
        record_id = self._add_overtime(self._mes_atual())
        with self.app.app_context():
            record = db.session.get(TeacherOvertimePay, record_id)
            record.multiple_dates = '10, 17'
            db.session.commit()
        page = self.client.get(f'/payments/overtime/edit/{record_id}').get_data(as_text=True)
        bloco = re.search(r'<select name="dates_month".*?</select>', page, re.S).group(0)
        self.assertRegex(bloco, rf'<option value="{self._mes_atual()}" selected>')

    def test_edit_mes_das_datas_gravado(self):
        # Lançamento com mês das datas anterior ao mês base: o campo Mês volta
        # nele, dentro das opções (mês base e anterior) oferecidas na edição.
        record_id = self._add_overtime(self._mes_seguinte())
        with self.app.app_context():
            record = db.session.get(TeacherOvertimePay, record_id)
            record.dates_month = self._mes_atual()
            record.multiple_dates = '25, 28'
            db.session.commit()
        page = self.client.get(f'/payments/overtime/edit/{record_id}').get_data(as_text=True)
        bloco = re.search(r'<select name="dates_month".*?</select>', page, re.S).group(0)
        self.assertIn(f'value="{self._mes_atual()}"', bloco)
        self.assertIn(f'value="{self._mes_seguinte()}"', bloco)
        self.assertRegex(bloco, rf'<option value="{self._mes_atual()}" selected>')

    def test_edit_datas_completas_legado(self):
        # Registro gravado por uma versão intermediária com datas completas e
        # dates_month nulo: o mês vem da própria data ("25/09/2026" → setembro).
        record_id = self._add_overtime(self._mes_atual())
        with self.app.app_context():
            record = db.session.get(TeacherOvertimePay, record_id)
            record.multiple_dates = '25/09/2026'
            db.session.commit()
        page = self.client.get(f'/payments/overtime/edit/{record_id}').get_data(as_text=True)
        bloco = re.search(r'<select name="dates_month".*?</select>', page, re.S).group(0)
        self.assertRegex(bloco, rf'<option value="{self._mes_anterior()}" selected>')

    def test_edit_preserva_mes_das_datas_sem_campo(self):
        # Editar sem o campo Mês no POST (cliente sem o seletor) mantém o mês
        # das datas gravado — os dias continuam pertencendo ao mês certo.
        record_id = self._add_overtime(self._mes_seguinte())
        with self.app.app_context():
            record = db.session.get(TeacherOvertimePay, record_id)
            record.dates_month = self._mes_atual()
            record.multiple_dates = '25, 28'
            db.session.commit()
        response = self.client.post(f'/payments/overtime/edit/{record_id}',
                                    data=self._create_payload(
                                        weekly_workload_hours='2',
                                        weekly_workload_minutes='45'),
                                    follow_redirects=True)
        self.assertIn('Alteração realizada', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.get(TeacherOvertimePay, record_id)
            self.assertEqual(record.dates_month, self._mes_atual())
            self.assertEqual(record.month_base, self._mes_seguinte())

    def test_delete_overtime_preserva_filtros_de_origem(self):
        # Excluir a partir da linha não pode devolver a listagem limpa
        # (sem o mês/professor filtrados nem a página atual).
        record_id = self._add_overtime(self._mes_atual())
        referrer = ('http://localhost/payments/overtime/list'
                    f'?month_base={self._mes_atual()}&page=2')
        response = self.client.post(f'/payments/overtime/delete/{record_id}',
                                    headers={'Referer': referrer})
        location = response.headers.get('Location', '')
        self.assertIn('/payments/overtime/list?', location)
        self.assertIn('month_base=', location)
        self.assertIn('page=2', location)

    # ---------- Paginação dentro do bloco de conteúdo ----------

    def test_pagination_renders_inside_page_content(self):
        # Antes, o macro ficava no bloco scripts e a paginação era renderizada
        # depois do layout (abaixo do rodapé). Deve vir antes do <footer>.
        for _ in range(30):  # 25 por página → 2 páginas
            self._add_overtime(self._mes_atual())

        page = self.client.get('/payments/overtime/list?month_base=').get_data(as_text=True)
        self.assertIn('Navegação de páginas', page)
        self.assertLess(page.index('Navegação de páginas'), page.index('<footer'))

    # ---------- Aviso de navegador removido ----------

    def test_aviso_de_navegador_removido(self):
        for url in ('/payments/overtime/list', '/payments/overtime/create'):
            page = self.client.get(url).get_data(as_text=True)
            self.assertNotIn('Evite o Mozilla Firefox', page)
            self.assertNotIn('recomenda-se o uso do Google Chrome', page)


if __name__ == '__main__':
    unittest.main()
