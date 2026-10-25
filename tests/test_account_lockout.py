"""Bloqueio de conta por excesso de tentativas de login (CWE-307).

Cobre:
1. 10 senhas erradas bloqueiam a conta — nem a senha correta entra;
2. a resposta para senha errada continua genérica (sem enumerar contas);
3. login bem-sucedido zera o contador (falhas espalhadas não acumulam);
4. desbloqueio é exclusivo de quem tem user:lock — e zera o contador;
5. super-admin não pode ser bloqueado por operador sem '*';
6. ninguém bloqueia a própria conta.
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Permission, Role, Unity, User, MAX_TENTATIVAS_LOGIN)

SENHA = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class AccountLockoutTestCase(unittest.TestCase):
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
            for code in ('user:lock', 'user:edit', 'user:read'):
                perms[code] = Permission(code=code, module='user',
                                         action=code.split(':')[1],
                                         description=code)
            perms['*'] = Permission(code='*', module='system', action='all',
                                    description='Permissão universal')
            db.session.add_all(perms.values())
            db.session.flush()

            self.role_gestor = Role(name='gestor_teste', label='Gestor Teste',
                                    permissions=[perms['user:lock'], perms['user:edit'],
                                                 perms['user:read']])
            self.role_basico = Role(name='basico_teste', label='Básico Teste',
                                    permissions=[])
            self.role_super = Role(name='super_teste', label='Super Teste',
                                   permissions=[perms['*']])
            db.session.add_all([self.role_gestor, self.role_basico, self.role_super])
            db.session.flush()

            self.unity = Unity(name='Unidade A', code='UA', is_active=True)
            db.session.add(self.unity)

            def novo(email, nome, role):
                u = User(email=email, full_name=nome, registration=email,
                         profile_type='employee', role_id=role.id,
                         force_password_change=False, is_active_user=True)
                u.set_password(SENHA)
                db.session.add(u)
                return u

            # Contas globais (sem unidade): visíveis em qualquer escopo.
            self.gestor = novo('gestor@escola.edu', 'Gestor Bloqueios', self.role_gestor)
            self.sem_permissao = novo('semplok@escola.edu', 'Sem Permissão', self.role_basico)
            self.vitima = novo('vitima@escola.edu', 'Conta Alvo', self.role_basico)
            self.super1 = novo('super1@escola.edu', 'Super Um', self.role_super)
            db.session.commit()
            self.ids = {u.email: u.id for u in (self.gestor, self.sem_permissao,
                                                self.vitima, self.super1)}

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _post_login(self, email, senha):
        # Desloga primeiro: com sessão ativa, /login redireciona sem nem
        # processar o POST — não contaria tentativa nem trocaria de usuário.
        self.client.get('/logout')
        return self.client.post('/login', data={'email': email, 'password': senha},
                                follow_redirects=True)

    def _tentativas_erradas(self, email, qtde):
        for _ in range(qtde):
            self._post_login(email, 'SenhaErrada999')

    def _estado(self, email):
        """(is_locked, failed_login_attempts, locked_at) lidos do banco."""
        with self.app.app_context():
            u = db.session.query(User).filter_by(email=email).first()
            return u.is_locked, u.failed_login_attempts, u.locked_at

    def _admin_acao(self, acao, email_alvo, logado='gestor@escola.edu'):
        if logado:
            self._post_login(logado, SENHA)
        return self.client.post(f'/admin/users/{self.ids[email_alvo]}/{acao}',
                                follow_redirects=True)

    # ── Bloqueio automático ──────────────────────────────────────────────

    def test_limite_menos_um_nao_bloqueia(self):
        self._tentativas_erradas('vitima@escola.edu', MAX_TENTATIVAS_LOGIN - 1)
        bloqueada, tentativas, _ = self._estado('vitima@escola.edu')
        self.assertFalse(bloqueada)
        self.assertEqual(tentativas, MAX_TENTATIVAS_LOGIN - 1)

    def test_dez_tentativas_bloqueiam_e_senha_correta_e_negada(self):
        self._tentativas_erradas('vitima@escola.edu', MAX_TENTATIVAS_LOGIN)
        bloqueada, _, locked_at = self._estado('vitima@escola.edu')
        self.assertTrue(bloqueada)
        self.assertIsNotNone(locked_at)

        # Senha correta na conta bloqueada: negada, com mensagem específica.
        resp = self._post_login('vitima@escola.edu', SENHA)
        pagina = resp.get_data(as_text=True)
        self.assertIn('bloqueada por excesso de tentativas', pagina)
        # O flash de sucesso incluiria o nome; o título da página de login
        # ("Bem-vindo de volta") sempre existe e não prova nada.
        self.assertNotIn('Bem-vindo de volta, Conta Alvo', pagina)

    def test_senha_errada_tem_resposta_generica(self):
        """Sem enumeração: erro comum não revela bloqueio nem existência."""
        self._tentativas_erradas('vitima@escola.edu', MAX_TENTATIVAS_LOGIN)
        resp = self._post_login('vitima@escola.edu', 'SenhaErrada999')
        pagina = resp.get_data(as_text=True)
        self.assertIn('E-mail ou senha inválidos.', pagina)
        self.assertNotIn('bloqueada por excesso', pagina)

    def test_login_bem_sucedido_zera_contador(self):
        """Falhas antes de um acesso não acumulam com as de depois."""
        self._tentativas_erradas('vitima@escola.edu', MAX_TENTATIVAS_LOGIN - 1)
        self._post_login('vitima@escola.edu', SENHA)  # zera o contador
        self._tentativas_erradas('vitima@escola.edu', MAX_TENTATIVAS_LOGIN - 1)
        bloqueada, tentativas, _ = self._estado('vitima@escola.edu')
        self.assertFalse(bloqueada)
        self.assertEqual(tentativas, MAX_TENTATIVAS_LOGIN - 1)

    # ── Desbloqueio administrativo ───────────────────────────────────────

    def test_desbloqueio_pela_rota_restaura_acesso(self):
        self._tentativas_erradas('vitima@escola.edu', MAX_TENTATIVAS_LOGIN)

        resp = self._admin_acao('unlock', 'vitima@escola.edu')
        self.assertIn('desbloqueada', resp.get_data(as_text=True))
        bloqueada, tentativas, locked_at = self._estado('vitima@escola.edu')
        self.assertFalse(bloqueada)
        self.assertEqual(tentativas, 0)
        self.assertIsNone(locked_at)

        resp = self._post_login('vitima@escola.edu', SENHA)
        self.assertIn('Bem-vindo de volta, Conta Alvo', resp.get_data(as_text=True))

    def test_rota_exige_user_lock(self):
        self._post_login('semplok@escola.edu', SENHA)
        resp = self.client.post(f'/admin/users/{self.ids["vitima@escola.edu"]}/unlock',
                                follow_redirects=True)
        self.assertEqual(resp.status_code, 403)

    def test_super_admin_nao_pode_ser_bloqueado_por_operador_comum(self):
        resp = self._admin_acao('lock', 'super1@escola.edu')
        self.assertEqual(resp.status_code, 403)
        bloqueada, _, _ = self._estado('super1@escola.edu')
        self.assertFalse(bloqueada)

    def test_nao_bloqueia_a_propria_conta(self):
        resp = self._admin_acao('lock', 'gestor@escola.edu')
        self.assertIn('não pode bloquear sua própria conta',
                      resp.get_data(as_text=True))
        bloqueada, _, _ = self._estado('gestor@escola.edu')
        self.assertFalse(bloqueada)

    def test_bloqueio_manual_e_idempotente(self):
        resp = self._admin_acao('lock', 'vitima@escola.edu')
        self.assertIn('bloqueada. Nenhum login será aceito',
                      resp.get_data(as_text=True))
        bloqueada, _, _ = self._estado('vitima@escola.edu')
        self.assertTrue(bloqueada)

        # Segunda tentativa: aviso, sem erro nem dupla gravação.
        resp = self._admin_acao('lock', 'vitima@escola.edu')
        self.assertIn('já está bloqueada', resp.get_data(as_text=True))

    def test_unlock_em_conta_nao_bloqueada_e_informativo(self):
        resp = self._admin_acao('unlock', 'vitima@escola.edu')
        self.assertIn('não está bloqueada', resp.get_data(as_text=True))

    def test_bloqueio_manual_impede_login_ate_desbloqueio(self):
        self._admin_acao('lock', 'vitima@escola.edu')
        resp = self._post_login('vitima@escola.edu', SENHA)
        self.assertIn('bloqueada por excesso de tentativas',
                      resp.get_data(as_text=True))
        self.assertNotIn('Bem-vindo de volta, Conta Alvo',
                         resp.get_data(as_text=True))

    def test_bloqueio_derruba_sessao_ja_aberta(self):
        """Regressão CWE-863: usuário logado que tem a conta bloqueada perde
        a sessão na requisição seguinte (load_user devolve None)."""
        self._post_login('vitima@escola.edu', SENHA)
        resp = self.client.get('/dashboard')
        self.assertEqual(resp.status_code, 200)  # sessão viva antes do bloqueio

        # Ação administrativa em OUTRO client: a sessão da vítima precisa
        # permanecer intoca neste — é exatamente o que o teste observa.
        admin_client = self.app.test_client()
        admin_client.post('/login', data={'email': 'gestor@escola.edu',
                                          'password': SENHA})
        admin_client.post(f"/admin/users/{self.ids['vitima@escola.edu']}/lock")

        resp = self.client.get('/dashboard', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers.get('Location', ''))


if __name__ == '__main__':
    unittest.main()
