"""Testes do módulo de Hora Extra (pagamentos).

Cobre as regras pedidas no módulo Financeiro:
- Bloqueio (com mensagem visível) de lançamentos com Mês Base anterior ao mês
  atual — antes, o lançamento era gravado silenciosamente, sem erro;
- Consulta abre no mês atual, com caixa de seleção de meses e opção
  "Todos os meses";
- Exportação filtrada por professor;
- Máscara do Código Orçamentário (xx.xx.xxxx.xx e xx.xx.xxxx.xx.xxxx).
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from io import BytesIO
from unittest.mock import patch

from openpyxl import load_workbook

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, TeacherOvertimePay, Unity, User

USERNAME = 'financeiro.teste'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class FixedDatetime(datetime):
    """datetime com now() fixado no dia 10 do mês corrente real: fica fora da
    janela do dia 25, então o mês atual é sempre lançável nos testes."""
    @classmethod
    def now(cls):
        today = datetime.now()
        return cls(today.year, today.month, 10, 12, 0)


class PaymentsTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        # O cliente de teste fala HTTP puro; cookie Secure impediria a sessão.
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(self.unity)
            db.session.flush()

            perms = [Permission(code=code, module='payment', action=code.split(':')[1])
                     for code in ('payment:read', 'payment:create', 'payment:edit',
                                  'payment:delete', 'payment:export')]
            db.session.add_all(perms)
            role = Role(name='financeiro-teste', label='Financeiro Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            manager = User(
                username=USERNAME, email='financeiro@escola.edu', full_name='Financeiro Teste',
                role='room', profile_type='employee', unity_id=self.unity.id,
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            manager.set_password(PASSWORD)
            teacher = User(
                username='prof.teste', email='prof@escola.edu', full_name='Professora Teste',
                role='viewer', profile_type='teacher', unity_id=self.unity.id,
                force_password_change=False, is_active_user=True,
            )
            teacher.set_password(PASSWORD)
            other_teacher = User(
                username='prof.outro', email='prof2@escola.edu', full_name='Outro Professor',
                role='viewer', profile_type='teacher', unity_id=self.unity.id,
                force_password_change=False, is_active_user=True,
            )
            other_teacher.set_password(PASSWORD)
            db.session.add_all([manager, teacher, other_teacher])
            db.session.commit()
            self.teacher_id, self.other_teacher_id = teacher.id, other_teacher.id
            self.unity_id = self.unity.id

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
        response = self.client.post('/login', data={'username': USERNAME, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _create_payload(self, **overrides):
        payload = {
            'teacher': str(self.teacher_id),
            'teaching_level': 'Superior',
            'shift': 'Noturno',
            'weekly_workload': '4',
            'hourly_value': '25,50',
            'budget_code': '950001234',
            'multiple_dates': '10/09/2026',
            'justification': 'Substituicao de aula',
            'month_base': datetime.now().strftime('%Y-%m'),
        }
        payload.update(overrides)
        return payload

    def _previous_month(self):
        return (datetime.now().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')

    def _add_overtime(self, month_base, teacher_id=None, budget_code='950001234'):
        with self.app.app_context():
            record = TeacherOvertimePay(
                teacher_id=teacher_id or self.teacher_id, teaching_level='Superior',
                unity_id=self.unity_id, weekly_workload=4, hourly_value=25.5,
                budget_code=budget_code, shift='Noturno', month_base=month_base,
            )
            db.session.add(record)
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

    # ---------- Cadastro: bloqueio de mês anterior ----------

    def test_create_past_month_is_blocked_with_error(self):
        response = self.client.post('/payments/overtime/create',
                                    data=self._create_payload(month_base=self._previous_month()),
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('meses anteriores ao mês atual', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.query(TeacherOvertimePay).count(), 0)

    def test_create_current_month_succeeds_and_formats_budget_code(self):
        with patch('app.blueprints.payments.datetime', FixedDatetime):
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
        with patch('app.blueprints.payments.datetime', FixedDatetime):
            response = self.client.post('/payments/overtime/create', data=self._create_payload(
                budget_code='95.00.0123.40.1234'), follow_redirects=True)
        self.assertIn('Lançamento de Hora Extra realizado', response.get_data(as_text=True))
        with self.app.app_context():
            record = db.session.query(TeacherOvertimePay).first()
            self.assertEqual(record.budget_code, '95.00.0123.40.1234')

    # ---------- Consulta: mês atual como padrão ----------

    def test_list_defaults_to_current_month(self):
        self._add_overtime(datetime.now().strftime('%Y-%m'))
        self._add_overtime('2024-08', teacher_id=self.other_teacher_id)

        # Sem parâmetros: abre no mês atual
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
        self._add_overtime(datetime.now().strftime('%Y-%m'), budget_code='950001234')
        response = self.client.get('/payments/overtime/list?month_base=')
        self.assertIn('95.00.0123.4', response.get_data(as_text=True))

    # ---------- Exportação por professor ----------

    def test_export_filtered_by_teacher(self):
        self._add_overtime(datetime.now().strftime('%Y-%m'))
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
        self.assertEqual(ws.cell(row=7, column=7).value, '95.00.0123.4')

    # ---------- Aviso de navegador ----------

    def test_browser_notice_compact_and_fixed(self):
        for url in ('/payments/overtime/list', '/payments/overtime/create'):
            page = self.client.get(url).get_data(as_text=True)
            self.assertIn('Evite o Mozilla Firefox', page)
            # O aviso antigo era dispensável (btn-close); o novo é fixo e compacto
            self.assertNotIn('alert-dismissible fade show d-flex', page)


if __name__ == '__main__':
    unittest.main()
