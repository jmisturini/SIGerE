"""Testes de integração da troca obrigatória de senha no primeiro login.

Cenário coberto (regressão da correção): o usuário com
force_password_change=True NÃO pode reutilizar a própria senha inicial —
nem na troca obrigatória do primeiro acesso, nem em trocas de senha
posteriores.

A suíte sobe a aplicação real (create_app) com banco SQLite temporário e
exercita o fluxo via test_client: login -> redirecionamento para
/change-password -> tentativa de reuso -> troca válida.
"""
import os
import tempfile
import unittest

from werkzeug.security import check_password_hash

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User

USERNAME = 'prof.teste'
INITIAL_PASSWORD = 'SenhaInicial123'
NEW_PASSWORD = 'NovaSenhaForte9'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class PasswordChangeTestCase(unittest.TestCase):
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
            user = User(
                username=USERNAME,
                email='prof.teste@escola.edu',
                full_name='Professor Teste',
                force_password_change=True,
                is_active_user=True,
            )
            user.set_password(INITIAL_PASSWORD)
            db.session.add(user)
            db.session.commit()
            self.user_id = user.id
            self.initial_hash = user.password_hash

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _login(self):
        return self.client.post(
            '/login',
            data={'username': USERNAME, 'password': INITIAL_PASSWORD},
            follow_redirects=False,
        )

    def _post_change(self, current, new, confirm=None):
        return self.client.post(
            '/change-password',
            data={
                'current_password': current,
                'password': new,
                'confirm_password': confirm if confirm is not None else new,
            },
            follow_redirects=False,
        )

    def _user_state(self):
        """(flag force_password_change, password_hash) lidos do banco."""
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            return user.force_password_change, user.password_hash

    # ── Testes ───────────────────────────────────────────────────────────

    def test_primeiro_login_redireciona_para_troca_obrigatoria(self):
        resp = self._login()
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith('/dashboard'), resp.location)

        resp = self.client.get('/', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith('/change-password'), resp.location)

        resp = self.client.get('/change-password')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Trocar Senha'.encode(), resp.data)

    def test_reuso_da_senha_inicial_e_rejeitado(self):
        """O núcleo da correção: mesma senha do primeiro acesso é bloqueada."""
        self._login()
        resp = self._post_change(INITIAL_PASSWORD, INITIAL_PASSWORD)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('não pode ser igual à senha atual'.encode(), resp.data)

        flag, current_hash = self._user_state()
        self.assertTrue(flag, 'force_password_change deve permanecer True')
        self.assertEqual(current_hash, self.initial_hash, 'a hash não pode mudar')
        self.assertTrue(check_password_hash(current_hash, INITIAL_PASSWORD))

    def test_variacao_apenas_na_confirmacao_e_rejeitada(self):
        """Senha nova != confirmação: erro de formulário, nada é gravado."""
        self._login()
        resp = self._post_change(INITIAL_PASSWORD, NEW_PASSWORD,
                                 confirm='ConfirmacaoDiferente1')

        self.assertEqual(resp.status_code, 200)
        flag, current_hash = self._user_state()
        self.assertTrue(flag)
        self.assertEqual(current_hash, self.initial_hash)

    def test_senha_atual_errada_e_rejeitada(self):
        self._login()
        resp = self._post_change('SenhaErrada999', NEW_PASSWORD)

        self.assertEqual(resp.status_code, 200)
        self.assertIn('Senha atual incorreta.'.encode(), resp.data)

        flag, current_hash = self._user_state()
        self.assertTrue(flag)
        self.assertEqual(current_hash, self.initial_hash)

    def test_nova_senha_curta_e_rejeitada(self):
        self._login()
        resp = self._post_change(INITIAL_PASSWORD, 'abc12')

        self.assertEqual(resp.status_code, 200)
        self.assertIn('A nova senha deve ter pelo menos 8 caracteres.'.encode(), resp.data)

        flag, current_hash = self._user_state()
        self.assertTrue(flag)
        self.assertEqual(current_hash, self.initial_hash)

    def test_troca_com_senha_diferente_funciona(self):
        resp = self._login()
        self.assertEqual(resp.status_code, 302)

        resp = self._post_change(INITIAL_PASSWORD, NEW_PASSWORD)
        self.assertEqual(resp.status_code, 302, 'sucesso deve redirecionar')

        # A mensagem de sucesso é exibida na próxima página renderizada.
        resp = self.client.get('/change-password')
        self.assertIn('Sua senha foi atualizada com sucesso!'.encode(), resp.data)

        flag, current_hash = self._user_state()
        self.assertFalse(flag, 'force_password_change deve virar False')
        self.assertTrue(check_password_hash(current_hash, NEW_PASSWORD))
        self.assertFalse(check_password_hash(current_hash, INITIAL_PASSWORD))

    def test_reuso_tambem_e_bloqueado_em_trocas_normais(self):
        """Depois da primeira troca, nova senha igual à atual também é bloqueada."""
        self._login()
        self._post_change(INITIAL_PASSWORD, NEW_PASSWORD)

        resp = self._post_change(NEW_PASSWORD, NEW_PASSWORD)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('não pode ser igual à senha atual'.encode(), resp.data)

        flag, current_hash = self._user_state()
        self.assertFalse(flag)
        self.assertTrue(check_password_hash(current_hash, NEW_PASSWORD))
        self.assertFalse(check_password_hash(current_hash, INITIAL_PASSWORD))


if __name__ == '__main__':
    unittest.main()
