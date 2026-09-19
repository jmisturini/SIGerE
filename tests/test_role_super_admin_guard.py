"""Bloqueio da edição do papel do super-admin por não super-admins.

O papel que carrega a permissão curinga '*' só pode ser alterado pelo
próprio super-admin: um admin comum com role:edit poderia esvaziá-lo ou
renomeá-lo, derrubando o acesso universal. Cobre o bloqueio na rota
(GET e POST), a edição normal dos demais papéis e o estado da listagem
(botão de editar substituído por cadeado).
"""
import os
import tempfile
import unittest

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, Unity, User

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SuperAdminRoleGuardTestCase(unittest.TestCase):
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
            db.session.commit()
            _seed_permissions()
            db.session.commit()

            perms = [Permission.query.filter_by(code=c).first()
                     for c in ('role:read', 'role:edit', 'role:create')]
            gestor_role = Role(name='gestor-roles', label='Gestor de Papéis',
                               permissions=perms)
            db.session.add(gestor_role)
            db.session.flush()

            gestor = User(
                email=EMAIL, full_name='Gestor Teste', role='room',
                profile_type='employee', unity_id=self.unity.id,
                role_id=gestor_role.id, force_password_change=False,
                is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)

            super_user = User(
                email='super@escola.edu', full_name='Super Teste', role='admin',
                profile_type='employee', unity_id=self.unity.id,
                role_id=Role.query.filter_by(name='super_admin').first().id,
                force_password_change=False, is_active_user=True,
            )
            super_user.set_password(PASSWORD)
            db.session.add(super_user)

            self.super_role_id = Role.query.filter_by(name='super_admin').first().id
            self.teacher_role_id = Role.query.filter_by(name='teacher').first().id
            db.session.commit()

        self._login(EMAIL)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email):
        # Encerra a sessão anterior: logar já autenticado só redireciona,
        # sem trocar o usuário.
        self.client.get('/logout')
        response = self.client.post('/login', data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('E-mail ou senha inválidos', response.get_data(as_text=True))

    def _payload_super_admin(self, **overrides):
        with self.app.app_context():
            perm_ids = [p.id for p in
                        Role.query.filter_by(name='super_admin').first().permissions]
        payload = {
            'label': 'Super Administrador MODIFICADO',
            'description': 'Tentativa de alteração indevida',
            'permissions': [str(i) for i in perm_ids],
        }
        payload.update(overrides)
        return payload

    # ---------- Rota de edição ----------

    def test_get_edicao_super_admin_bloqueado(self):
        """Gestor com role:edit não abre o formulário do papel super_admin."""
        response = self.client.get(f'/admin/roles/{self.super_role_id}/edit',
                                   follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Apenas o super-admin pode editar', page)
        self.assertNotIn('Salvar Papel', page)

    def test_post_edicao_super_admin_bloqueado(self):
        """POST forjado não altera rótulo nem permissões do papel super_admin."""
        response = self.client.post(f'/admin/roles/{self.super_role_id}/edit',
                                    data=self._payload_super_admin(),
                                    follow_redirects=True)
        self.assertIn('Apenas o super-admin pode editar', response.get_data(as_text=True))

        with self.app.app_context():
            role = Role.query.filter_by(name='super_admin').first()
            self.assertEqual(role.label, 'Super Administrador')
            self.assertIn('*', {p.code for p in role.permissions})

    def test_edicao_papel_comum_continua_funcionando(self):
        """O bloqueio é só do papel super_admin: gestor edita os demais."""
        response = self.client.post(f'/admin/roles/{self.teacher_role_id}/edit',
                                    data={'label': 'Professor Ajustado',
                                          'description': 'Ok para gestor'},
                                    follow_redirects=True)
        self.assertIn('Papel atualizado com sucesso', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(
                Role.query.filter_by(name='teacher').first().label,
                'Professor Ajustado')

    def test_super_admin_edita_proprio_papel(self):
        """O super-admin continua podendo editar o próprio papel."""
        self._login('super@escola.edu')
        response = self.client.post(f'/admin/roles/{self.super_role_id}/edit',
                                    data=self._payload_super_admin(
                                        label='Super Administrador'),
                                    follow_redirects=True)
        self.assertIn('Papel atualizado com sucesso', response.get_data(as_text=True))

    # ---------- Listagem ----------

    def test_listagem_mostra_cadeado_em_vez_do_lapis(self):
        """Para o gestor, o papel super_admin exibe cadeado e sem link de edição."""
        response = self.client.get('/admin/roles')
        page = response.get_data(as_text=True)
        self.assertIn('Apenas o super-admin pode editar este papel.', page)
        self.assertNotIn(f'/admin/roles/{self.super_role_id}/edit', page)
        # Os demais papéis continuam com o link de edição
        self.assertIn(f'/admin/roles/{self.teacher_role_id}/edit', page)

    def test_listagem_mostra_lapis_para_super_admin(self):
        """O super-admin vê o botão de editar no próprio papel."""
        self._login('super@escola.edu')
        response = self.client.get('/admin/roles')
        page = response.get_data(as_text=True)
        self.assertIn(f'/admin/roles/{self.super_role_id}/edit', page)


if __name__ == '__main__':
    unittest.main()
