"""Testes dos vínculos N:N entre usuários e unidades.

O mesmo professor ou funcionário pode atuar em várias unidades (user_unities):
- O cadastro/edição aceita múltiplas unidades e persiste a associação;
- A unidade ativa do usuário com múltiplos vínculos pode ser alternada pelo
  seletor (POST /unity/switch), que recusa unidades fora do escopo;
- Usuário com vínculo único fica fixado nele (não alterna);
- A listagem de usuários mostra os vinculados à unidade ativa + contas
  globais, escondendo os vinculados apenas a outras unidades.
"""
import os
import tempfile
import unittest

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, Unity, User

PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class UsuariosMultiplasUnidadesTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            _seed_permissions()
            db.session.commit()

            self.alfa = Unity(name='Unidade Alfa', code='UA')
            self.beta = Unity(name='Unidade Beta', code='UB')
            db.session.add_all([self.alfa, self.beta])
            db.session.flush()

            permissao_total = Permission.query.filter_by(code='*').first()
            role_super = Role(name='super', label='Super',
                              permissions=[permissao_total])
            role_basico = Role.query.filter_by(name='employee').first()
            db.session.add_all([role_super, role_basico])
            db.session.flush()

            def novo(email, nome, role, unities=()):
                u = User(email=email, full_name=nome, role='viewer',
                         profile_type='employee', registration=email,
                         role_id=role.id, unities=list(unities),
                         force_password_change=False, is_active_user=True)
                u.set_password(PASSWORD)
                db.session.add(u)
                return u

            self.super_user = novo('super@escola.edu', 'Super Um', role_super)
            self.multi = novo('multi@escola.edu', 'Multi Unidade', role_basico,
                              unities=[self.alfa, self.beta])
            self.alfa_only = novo('alfa@escola.edu', 'Só Alfa', role_basico,
                                  unities=[self.alfa])
            self.beta_only = novo('beta@escola.edu', 'Só Beta', role_basico,
                                  unities=[self.beta])
            db.session.commit()
            self.alfa_id, self.beta_id = self.alfa.id, self.beta.id
            self.multi_id, self.alfa_only_id = self.multi.id, self.alfa_only.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email):
        self.client.get('/logout')
        response = self.client.post('/login',
                                    data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    # ── Modelo: associação N:N ──────────────────────────────────────────

    def test_modelo_guarda_multiplas_unidades(self):
        with self.app.app_context():
            multi = db.session.get(User, self.multi_id)
            self.assertEqual(sorted(multi.unity_ids),
                             sorted([self.alfa_id, self.beta_id]))
            # primary: primeira unidade por nome (ordem do relacionamento)
            self.assertEqual(multi.primary_unity_id, self.alfa_id)

            alfa_only = db.session.get(User, self.alfa_only_id)
            self.assertEqual(alfa_only.unity_ids, [self.alfa_id])
            self.assertEqual(alfa_only.primary_unity_id, self.alfa_id)

    def test_escopo_unidade_inclui_vinculados_e_globais(self):
        with self.app.app_context():
            na_alfa = User.query.filter(User.escopo_unidade(self.alfa_id)) \
                .order_by(User.email).all()
            emails = [u.email for u in na_alfa]
            # super é global (sem vínculos): aparece em todas as listagens
            self.assertEqual(emails, ['alfa@escola.edu', 'multi@escola.edu',
                                      'super@escola.edu'])

    # ── Cadastro/edição com múltiplas unidades ──────────────────────────

    def test_cadastro_com_multiplas_unidades(self):
        self._login('super@escola.edu')
        with self.app.app_context():
            role_id = Role.query.filter_by(name='employee').first().id
        response = self.client.post('/admin/users/create', data={
            'profile_type': 'employee', 'email': 'nova@escola.edu',
            'full_name': 'Nova Multi', 'registration': 'MAT-MULTI',
            'sector': 'Secretaria', 'function': 'Assistente',
            'unities': [str(self.alfa_id), str(self.beta_id)],
            'role_id': str(role_id), 'password': 'SenhaForte999',
            'is_active_user': 'y',
        }, follow_redirects=True)
        self.assertIn('cadastrado com sucesso', response.get_data(as_text=True))

        with self.app.app_context():
            user = User.query.filter_by(email='nova@escola.edu').first()
            self.assertIsNotNone(user)
            self.assertEqual(sorted(user.unity_ids),
                             sorted([self.alfa_id, self.beta_id]))

    def test_cadastro_exige_ao_menos_uma_unidade(self):
        self._login('super@escola.edu')
        with self.app.app_context():
            role_id = Role.query.filter_by(name='employee').first().id
        response = self.client.post('/admin/users/create', data={
            'profile_type': 'employee', 'email': 'sem@escola.edu',
            'full_name': 'Sem Unidade', 'registration': 'MAT-SEM',
            'role_id': str(role_id), 'password': 'SenhaForte999',
            'is_active_user': 'y',
        })
        self.assertIn('Selecione pelo menos uma unidade',
                      response.get_data(as_text=True))

    def test_edicao_acrescenta_unidade(self):
        self._login('super@escola.edu')
        with self.app.app_context():
            user = db.session.get(User, self.alfa_only_id)
            role_id = user.role_id
            response = self.client.post(f'/admin/users/{self.alfa_only_id}/edit',
                                        data={
                'email': 'alfa@escola.edu', 'full_name': 'Só Alfa',
                'registration': 'alfa@escola.edu', 'sector': 'Apoio',
                'function': 'Auxiliar', 'is_teacher': 'n',
                'unities': [str(self.alfa_id), str(self.beta_id)],
                'role_id': str(role_id), 'is_active_user': 'y',
            }, follow_redirects=True)
            self.assertIn('atualizado com sucesso',
                          response.get_data(as_text=True))
            db.session.expire(user)
            self.assertEqual(sorted(user.unity_ids),
                             sorted([self.alfa_id, self.beta_id]))

    # ── Unidade ativa e troca pelo seletor ──────────────────────────────

    def test_multi_unidade_alternar_pelo_seletor(self):
        self._login('multi@escola.edu')
        # sem sessão: cai na primeira unidade própria (ordem alfabética)
        page = self.client.get('/calendar/').get_data(as_text=True)
        self.assertIn('Unidade Alfa', page)

        response = self.client.post('/unity/switch',
                                    data={'unity_id': self.beta_id},
                                    follow_redirects=True)
        self.assertIn('Unidade ativa alterada', response.get_data(as_text=True))
        page = self.client.get('/calendar/').get_data(as_text=True)
        self.assertIn('Unidade Beta', page)

    def test_multi_unidade_nao_alterna_para_unidade_estranha(self):
        with self.app.app_context():
            gama = Unity(name='Unidade Gama', code='UG')
            db.session.add(gama)
            db.session.commit()
            gama_id = gama.id
        self._login('alfa@escola.edu')  # vínculo único com Alfa
        response = self.client.post('/unity/switch',
                                    data={'unity_id': gama_id},
                                    follow_redirects=True)
        self.assertIn('não tem permissão', response.get_data(as_text=True))
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('unity_id'))

    def test_vinculo_unico_nao_tem_seletor(self):
        self._login('alfa@escola.edu')
        page = self.client.get('/calendar/').get_data(as_text=True)
        self.assertNotIn('Trocar', page)

    def test_multi_unidade_tem_seletor_com_proprias_unidades(self):
        self._login('multi@escola.edu')
        page = self.client.get('/calendar/').get_data(as_text=True)
        self.assertIn('Trocar', page)
        self.assertIn('Unidade Alfa', page)
        self.assertIn('Unidade Beta', page)

    def test_perder_vinculo_derruba_unidade_da_sessao(self):
        # troca para Beta e depois perde o vínculo: a sessão não vale mais e
        # o usuário cai no vínculo restante (Alfa)
        self._login('multi@escola.edu')
        self.client.post('/unity/switch', data={'unity_id': self.beta_id})
        with self.app.app_context():
            multi = db.session.get(User, self.multi_id)
            # re-busca do Unity: a instância de setUp ficou detached após as
            # requisições (session.remove() no teardown do app context)
            alfa = db.session.get(Unity, self.alfa_id)
            multi.unities = [alfa]
            db.session.commit()
        page = self.client.get('/calendar/').get_data(as_text=True)
        self.assertIn('Unidade Alfa', page)

    # ── Escopo da listagem de usuários ──────────────────────────────────

    def test_listagem_usuarios_por_unidade_ativa(self):
        self._login('super@escola.edu')  # global: unidade ativa = Alfa (1ª ativa)
        page = self.client.get('/admin/users').get_data(as_text=True)
        self.assertIn('Multi Unidade', page)
        self.assertIn('Só Alfa', page)
        self.assertNotIn('Só Beta', page)


if __name__ == '__main__':
    unittest.main()
