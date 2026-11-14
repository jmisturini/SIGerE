"""Funcionário que também leciona nas listas de pagamento e na busca pública.

O cadastro "Também cadastrar como Professor" (is_teacher) designa o
funcionário para reservas — e ele recebe Hora Extra e Vale-Alimentação como
qualquer professor. Regressão: os filtros usavam apenas
profile_type == 'teacher' e escondiam essas contas nos formulários de
pagamento (payments.py) e na busca pública de professores (public.py) —
o cronograma já as listava (padrão união profile_type | is_teacher).
"""
import os
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Permission, Role, TeacherMealAllowance,
                        TeacherOvertimePay, Unity, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'
FUNC_PROF = 'Funcionario Professor'
PROF_PURO = 'Professor Puro'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class FuncionarioProfessorPagamentosTestCase(unittest.TestCase):
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

            codigos = ['payment:read', 'payment:create', 'payment:edit',
                       'meal:read', 'meal:create', 'meal:edit', 'user:edit']
            perms = [Permission(code=c, module=c.split(':')[0], action=c.split(':')[1])
                     for c in codigos]
            db.session.add_all(perms)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()
            self.unity_id = self.unity.id
            self.role_id = role.id

            gestor = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)

            # professor puro (profile_type='teacher')
            professor = User(
                email='professor@escola.edu', full_name=PROF_PURO,
                role='room', profile_type='teacher', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            professor.set_password(PASSWORD)
            # funcionário que também leciona (o caso da regressão)
            func_prof = User(
                email='funcprof@escola.edu', full_name=FUNC_PROF,
                role='room', profile_type='employee', unities=[self.unity],
                force_password_change=False, is_active_user=True,
                is_teacher=True,
            )
            func_prof.set_password(PASSWORD)
            db.session.add_all([professor, func_prof])
            db.session.commit()
            self.func_prof_id = func_prof.id

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

    def test_hora_extra_listagem_e_formulario(self):
        listagem = self.client.get('/payments/overtime/list')
        self.assertEqual(listagem.status_code, 200)
        page = listagem.get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        self.assertIn(FUNC_PROF, page)

        formulario = self.client.get('/payments/overtime/create')
        self.assertEqual(formulario.status_code, 200)
        page = formulario.get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        self.assertIn(FUNC_PROF, page)

    def test_vale_alimentacao_lista_funcionario_professor(self):
        response = self.client.get('/payments/meal-allowance')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        self.assertIn(FUNC_PROF, page)

    def test_busca_publica_encontra_funcionario_professor(self):
        response = self.client.get('/search?type=teacher&q=Funcionario')
        self.assertEqual(response.status_code, 200)
        self.assertIn(FUNC_PROF, response.get_data(as_text=True))

    # ---------- Troca de perfil na edição (professor ↔ funcionário) ----------

    def _editar(self, user_id, **overrides):
        """POST na edição com o mínimo exigido pelo UserForm."""
        payload = {
            'full_name': PROF_PURO,
            'email': 'professor@escola.edu',
            'registration': 'MAT100',
            'unities': str(self.unity_id),
            'role_id': str(self.role_id),
            'password': '',
            'is_active_user': 'y',
            'profile_type': 'teacher',
        }
        payload.update(overrides)
        return self.client.post(f'/admin/users/{user_id}/edit', data=payload,
                                follow_redirects=True)

    def test_professor_tornado_funcionario_sai_das_listas(self):
        # Professor vira funcionário sem "Também cadastrar como Professor":
        # sai das dropdowns de professor (reservas, pagamentos, agenda...)
        # porque a união profile_type | is_teacher deixa de incluí-lo.
        with self.app.app_context():
            prof_id = db.session.query(User).filter_by(
                email='professor@escola.edu').first().id
        response = self._editar(prof_id, profile_type='employee',
                                sector='Secretaria', function='Apoio')
        self.assertIn('Usuário atualizado com sucesso', response.get_data(as_text=True))
        formulario = self.client.get('/payments/overtime/create')
        self.assertEqual(formulario.status_code, 200)
        page = formulario.get_data(as_text=True)
        self.assertNotIn(PROF_PURO, page)
        self.assertIn(FUNC_PROF, page)

    def test_professor_tornado_funcionario_que_leciona_permanece(self):
        # Professor vira funcionário que continua lecionando: com o checkbox
        # "Também cadastrar como Professor" ele permanece nas dropdowns.
        with self.app.app_context():
            prof_id = db.session.query(User).filter_by(
                email='professor@escola.edu').first().id
        response = self._editar(prof_id, profile_type='employee',
                                sector='Cozinha', function='Instrutor prático',
                                is_teacher='y')
        self.assertIn('Usuário atualizado com sucesso', response.get_data(as_text=True))
        formulario = self.client.get('/payments/overtime/create')
        self.assertEqual(formulario.status_code, 200)
        page = formulario.get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        self.assertIn(FUNC_PROF, page)

    # ---------- Edição de lançamentos com professor fora da união ----------

    def test_professor_fora_da_uniao_permanece_na_edicao_hora_extra(self):
        # Lançamento gravado para o professor que depois deixa de ser
        # professor (troca de perfil): a edição precisa mantê-lo entre as
        # choices. Sem isso, o GET não marca opção alguma e o navegador
        # reenvia o primeiro da lista — salvar reatribuiria o lançamento
        # em silêncio (achado do CodeRabbit no PR #228).
        with self.app.app_context():
            prof_id = db.session.query(User).filter_by(
                email='professor@escola.edu').first().id
            entrada = TeacherOvertimePay(
                teacher_id=prof_id, unity_id=self.unity_id,
                teaching_level='Técnico', weekly_workload=Decimal('4.00'),
                hourly_value=Decimal('50.00'), budget_code='123456789',
                shift='Matutino', multiple_dates='10',
                justification='Aula extra', course_type='Técnico',
                month_base=datetime.now().strftime('%Y-%m'))
            db.session.add(entrada)
            db.session.commit()
            entrada_id = entrada.id
        self._editar(prof_id, profile_type='employee', sector='Secretaria',
                     function='Apoio')
        page = self.client.get(f'/payments/overtime/edit/{entrada_id}').get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        response = self.client.post(f'/payments/overtime/edit/{entrada_id}', data={
            'teacher': str(prof_id), 'teaching_level': 'Técnico',
            'course_type': 'Técnico', 'weekly_workload_hours': '4',
            'weekly_workload_minutes': '0', 'hourly_value': '50,00',
            'budget_code': '123456789', 'shift': 'Matutino',
            'justification': 'Aula extra', 'multiple_dates': '10',
        }, follow_redirects=True)
        self.assertIn('Alteração realizada!', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.get(TeacherOvertimePay, entrada_id).teacher_id,
                             prof_id)

    def test_professor_fora_da_uniao_permanece_na_edicao_vale(self):
        # Mesma regra na edição do Vale Alimentação.
        with self.app.app_context():
            prof_id = db.session.query(User).filter_by(
                email='professor@escola.edu').first().id
            entrada = TeacherMealAllowance(
                teacher_id=prof_id, unity_id=self.unity_id, days=5,
                month_base=datetime.now().strftime('%Y-%m'))
            db.session.add(entrada)
            db.session.commit()
            entrada_id = entrada.id
        self._editar(prof_id, profile_type='employee', sector='Secretaria',
                     function='Apoio')
        page = self.client.get(
            f'/payments/meal-allowance/{entrada_id}/edit').get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        response = self.client.post(
            f'/payments/meal-allowance/{entrada_id}/edit',
            data={'teacher': str(prof_id),
                  'month_base': datetime.now().strftime('%Y-%m'), 'days': '6'},
            follow_redirects=True)
        self.assertIn('Alteração realizada!', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.get(TeacherMealAllowance, entrada_id).teacher_id,
                             prof_id)


    _OVERTIME_POST = {
        'teaching_level': 'Técnico', 'course_type': 'Técnico',
        'weekly_workload_hours': '4', 'weekly_workload_minutes': '0',
        'hourly_value': '50,00', 'budget_code': '123456789',
        'shift': 'Matutino', 'justification': 'Aula extra',
        'multiple_dates': '10',
    }

    def test_professor_gravado_sem_vinculo_permanece_na_edicao_hora_extra(self):
        # O professor gravado pode ter PERDIDO o vínculo com a unidade ativa
        # depois do lançamento (removido para outra unidade): manter o
        # histórico é deliberado — salvar sem trocar o professor funciona —
        # e uma TROCA para um professor de outra unidade segue barrada
        # (política escolhida na rodada do CodeRabbit no PR #230; o Vale
        # Alimentação já aceitava o gravado sem revalidação).
        with self.app.app_context():
            outra = Unity(name='Unidade Outra', code='OU')
            db.session.add(outra)
            db.session.flush()
            prof = db.session.query(User).filter_by(
                email='professor@escola.edu').first()
            prof_id = prof.id
            entrada = TeacherOvertimePay(
                teacher_id=prof_id, unity_id=self.unity_id,
                teaching_level='Técnico', weekly_workload=Decimal('4.00'),
                hourly_value=Decimal('50.00'), budget_code='123456789',
                shift='Matutino', multiple_dates='10',
                justification='Aula extra', course_type='Técnico',
                month_base=datetime.now().strftime('%Y-%m'))
            db.session.add(entrada)
            db.session.commit()
            entrada_id = entrada.id
            # professor segue ativo, mas com vínculo só na OUTRA unidade
            prof.unities = [outra]
            db.session.commit()
        page = self.client.get(
            f'/payments/overtime/edit/{entrada_id}').get_data(as_text=True)
        self.assertIn(PROF_PURO, page)
        payload = dict(self._OVERTIME_POST, teacher=str(prof_id))
        response = self.client.post(
            f'/payments/overtime/edit/{entrada_id}', data=payload,
            follow_redirects=True)
        self.assertIn('Alteração realizada!', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.get(TeacherOvertimePay, entrada_id).teacher_id,
                             prof_id)
        # troca para um professor de outra unidade: barrado. Ele não entra
        # nas choices da unidade ativa (escopo) e o guarda de unidade
        # (_professor_da_unidade_or_none) também o recusa — a combinação
        # fecha o POST forjado com id de fora.
        with self.app.app_context():
            externa = Unity(name='Unidade Externa', code='EX')
            db.session.add(externa)
            db.session.flush()
            externo = User(email='externo@escola.edu', full_name='Externo X',
                           role='room', profile_type='teacher',
                           unities=[externa], force_password_change=False,
                           is_active_user=True)
            externo.set_password(PASSWORD)
            db.session.add(externo)
            db.session.commit()
            externo_id = externo.id
        payload = dict(self._OVERTIME_POST, teacher=str(externo_id))
        response = self.client.post(
            f'/payments/overtime/edit/{entrada_id}', data=payload,
            follow_redirects=True)
        self.assertNotIn('Alteração realizada!',
                         response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.get(TeacherOvertimePay, entrada_id).teacher_id,
                             prof_id)


if __name__ == '__main__':
    unittest.main()
