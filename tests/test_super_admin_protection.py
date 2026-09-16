"""Proteção da conta super-administrador contra operadores sem '*'.

Cobre os três bloqueios da área de permissões:
1. administrador não edita/desativa/reseta a senha do super-admin;
2. administrador não atribui papel com permissão universal '*' (a si mesmo
   ou a terceiros), nem na criação nem na edição, nem adiciona '*' a papéis;
3. alternância da unidade ativa é exclusiva do super-admin — a permissão
   legada unity:switch, sozinha, não libera mais o seletor.
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Permission, Role, Unity, User)

SENHA = 'SenhaForte123'

# Somos os códigos usados nos testes; os IDs vêm do banco.
PERMS_ADMIN = ('user:read', 'user:create', 'user:edit', 'user:toggle',
               'role:read', 'role:create', 'role:edit', 'role:delete',
               'unity:switch', 'system:dashboard')


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SuperAdminProtectionTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            perms = {}
            for code, module, action, desc in [
                ('*', 'system', 'all', 'Permissão universal'),
                ('reservation:create', 'reservation', 'create', 'Criar reservas'),
                *[(c, c.split(':')[0], c.split(':')[1], c) for c in PERMS_ADMIN],
            ]:
                perms[code] = Permission(code=code, module=module,
                                         action=action, description=desc)
                db.session.add(perms[code])
            db.session.flush()

            self.role_super = Role(name='super_teste', label='Super Teste',
                                   permissions=[perms['*']])
            self.role_admin = Role(name='admin_teste', label='Admin Teste',
                                   permissions=[perms[c] for c in PERMS_ADMIN])
            self.role_basico = Role(name='basico_teste', label='Básico Teste',
                                    permissions=[perms['reservation:create']])
            db.session.add_all([self.role_super, self.role_admin, self.role_basico])
            db.session.flush()

            self.unity_a = Unity(name='Unidade A', code='UA', is_active=True)
            self.unity_b = Unity(name='Unidade B', code='UB', is_active=True)
            db.session.add_all([self.unity_a, self.unity_b])
            db.session.flush()

            def novo(email, nome, role):
                u = User(email=email, full_name=nome, registration=email,
                         profile_type='employee', role_id=role.id,
                         force_password_change=False, is_active_user=True)
                u.set_password(SENHA)
                db.session.add(u)
                return u

            self.super1 = novo('super1@escola.edu', 'Super Um', self.role_super)
            self.super2 = novo('super2@escola.edu', 'Super Dois', self.role_super)
            self.admin = novo('admin@escola.edu', 'Admin Comum', self.role_admin)
            self.comum = novo('comum@escola.edu', 'Usuário Comum', self.role_basico)
            db.session.commit()
            self.ids = {u.email: u.id for u in (self.super1, self.super2,
                                                self.admin, self.comum)}
            self.role_ids = {'super': self.role_super.id,
                             'admin': self.role_admin.id,
                             'basico': self.role_basico.id}
            self.perm_super_id = perms['*'].id
            self.unity_ids = (self.unity_a.id, self.unity_b.id)

        self._login('admin@escola.edu')

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email):
        # logout antes: o /login redireciona sem processar credenciais quando
        # já há sessão ativa, então trocar de usuário exige encerrar a anterior
        self.client.get('/logout')
        response = self.client.post('/login',
                                    data={'email': email, 'password': SENHA},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _dados_usuario(self, email='novo@escola.edu', nome='Novo Usuário',
                       role_id=None, unity_id=None, **extras):
        dados = {'profile_type': 'employee', 'email': email, 'full_name': nome,
                 'registration': email, 'unity_id': unity_id or self.unity_ids[0],
                 'role_id': role_id or self.role_ids['basico'],
                 'password': 'SenhaForte999', 'is_active_user': True}
        dados.update(extras)
        return dados

    # ── 1. Conta super-admin intocável por operador sem '*' ──

    def test_admin_nao_edita_super_admin(self):
        super_id = self.ids['super1@escola.edu']
        self.assertEqual(
            self.client.get(f'/admin/users/{super_id}/edit').status_code, 403)

        response = self.client.post(f'/admin/users/{super_id}/edit',
                                    data=self._dados_usuario(
                                        email='super1@escola.edu',
                                        nome='Super Sequestrado'))
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            alvo = db.session.get(User, super_id)
            self.assertEqual(alvo.full_name, 'Super Um')

    def test_admin_nao_desativa_nao_reseta_super_admin(self):
        super_id = self.ids['super1@escola.edu']
        self.assertEqual(
            self.client.post(f'/admin/users/{super_id}/toggle').status_code, 403)
        self.assertEqual(
            self.client.post(f'/admin/users/{super_id}/reset-password').status_code,
            403)
        with self.app.app_context():
            alvo = db.session.get(User, super_id)
            self.assertTrue(alvo.is_active_user)
            self.assertFalse(alvo.force_password_change)
            self.assertTrue(alvo.check_password(SENHA))

    def test_super_admin_gerencia_outro_super_e_usuarios(self):
        # sanity: com '*', a gestão segue funcionando — inclusive de outro super
        self._login('super1@escola.edu')
        dados = self._dados_usuario(email='super2@escola.edu',
                                    nome='Super Dois Renomeado')
        response = self.client.post(
            f"/admin/users/{self.ids['super2@escola.edu']}/edit",
            data={**dados, 'password': ''}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('atualizado com sucesso', response.get_data(as_text=True))

    # ── 2. Sem '*', nada de atribuir papel super-admin ──

    def test_admin_nao_cria_usuario_com_papel_super(self):
        response = self.client.post(
            '/admin/users/create',
            data=self._dados_usuario(role_id=self.role_ids['super']))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Apenas o super-administrador',
                      response.get_data(as_text=True))
        with self.app.app_context():
            criado = User.query.filter_by(email='novo@escola.edu').first()
            self.assertIsNone(criado)

        # com papel comum a criação funciona
        response = self.client.post(
            '/admin/users/create',
            data=self._dados_usuario(role_id=self.role_ids['basico']),
            follow_redirects=True)
        self.assertIn('cadastrado com sucesso', response.get_data(as_text=True))

    def test_admin_nao_atribui_papel_super_em_edicao(self):
        comum_id = self.ids['comum@escola.edu']
        base = {'profile_type': 'employee', 'email': 'comum@escola.edu',
                'full_name': 'Usuário Comum', 'registration': 'comum@escola.edu',
                'unity_id': self.unity_ids[0], 'password': ''}

        # papel principal → super
        response = self.client.post(f'/admin/users/{comum_id}/edit',
                                    data={**base, 'role_id': self.role_ids['super']})
        self.assertIn('Apenas o super-administrador',
                      response.get_data(as_text=True))
        # papel comum mantido + super como adicional
        response = self.client.post(
            f'/admin/users/{comum_id}/edit',
            data={**base, 'role_id': self.role_ids['basico'],
                  'extra_roles': [str(self.role_ids['super'])]})
        self.assertIn('Apenas o super-administrador',
                      response.get_data(as_text=True))

        with self.app.app_context():
            comum = db.session.get(User, comum_id)
            self.assertEqual(comum.role_id, self.role_ids['basico'])
            self.assertEqual([r.id for r in comum.extra_roles], [])

        # edição inofensiva (sem tocar em papéis) continua funcionando
        response = self.client.post(
            f'/admin/users/{comum_id}/edit',
            data={**base, 'full_name': 'Usuário Comum Renomeado',
                  'role_id': self.role_ids['basico']},
            follow_redirects=True)
        self.assertIn('atualizado com sucesso', response.get_data(as_text=True))

    def test_admin_nao_concede_permissao_super_em_papeis(self):
        perm = self.perm_super_id

        # papel novo com '*' → negado (choice oculto rejeita o POST forjado)
        response = self.client.post('/admin/roles/create',
                                    data={'label': 'Promoção Sorrateira',
                                          'permissions': [perm]})
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            papel = Role.query.filter_by(label='Promoção Sorrateira').first()
            self.assertIsNone(papel)

        # papel existente não ganha '*' na edição
        response = self.client.post(
            f"/admin/roles/{self.role_ids['basico']}/edit",
            data={'label': 'Básico Teste', 'permissions': [perm]})
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            papel = db.session.get(Role, self.role_ids['basico'])
            self.assertEqual([p.code for p in papel.permissions],
                             ['reservation:create'])

    def test_formulario_de_papel_oculta_permissao_super(self):
        checkbox_super = f'id="perm-{self.perm_super_id}"'
        response = self.client.get('/admin/roles/create')
        self.assertNotIn(checkbox_super, response.get_data(as_text=True))

        self._login('super1@escola.edu')
        response = self.client.get('/admin/roles/create')
        self.assertIn(checkbox_super, response.get_data(as_text=True))

    # ── 3. Alternância de unidade é exclusiva do super-admin ──

    def test_admin_com_unity_switch_nao_alterna_unidade(self):
        # mesmo com a permissão legada unity:switch, sem '*' não troca
        response = self.client.post('/unity/switch',
                                    data={'unity_id': self.unity_ids[1]},
                                    follow_redirects=True)
        self.assertIn('não tem permissão', response.get_data(as_text=True))
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('unity_id'))

        # e o seletor do topbar não aparece
        response = self.client.get('/dashboard')
        self.assertNotIn('Trocar unidade ativa', response.get_data(as_text=True))

    def test_super_admin_alterna_unidade(self):
        self._login('super1@escola.edu')
        response = self.client.get('/dashboard')
        self.assertIn('Trocar unidade ativa', response.get_data(as_text=True))

        response = self.client.post('/unity/switch',
                                    data={'unity_id': self.unity_ids[1]},
                                    follow_redirects=True)
        self.assertIn('Unidade ativa alterada', response.get_data(as_text=True))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('unity_id'), self.unity_ids[1])


if __name__ == '__main__':
    unittest.main()
