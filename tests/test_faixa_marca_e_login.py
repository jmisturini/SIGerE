"""Testes dos acabamentos de layout (referência Observatório Senac SC).

A faixa de marca do Painel (título + strip de módulos + tagline) e o
acabamento da tela de login (campos com ícone, botão largo com seta e
nota de segurança) são-presentes em todas as renderizações — os testes
guardam contra regressão de estrutura.
"""
import os
import tempfile
import unittest

from app import create_app
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


class FaixaMarcaLoginTestCase(unittest.TestCase):
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

            codigos = ('unity:read', 'system:dashboard', 'reservation:read_own')
            perms = [Permission(code=c, module=c.split(':')[0], action=c.split(':')[1])
                     for c in codigos]
            db.session.add_all(perms)
            role = Role(name='gestor', label='Gestor', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(email=EMAIL, full_name='Gestor Teste', role='room',
                        profile_type='employee', unities=[self.unity],
                        role_id=role.id, force_password_change=False,
                        is_active_user=True)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    # --- Faixa de marca do Painel ---

    def test_painel_tem_faixa_de_marca(self):
        """O Painel traz a faixa com título, strip de módulos e tagline."""
        self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                         follow_redirects=True)
        page = self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn('painel-faixa-titulo', page)
        self.assertIn('Gestão de Salas e Reservas', page)
        # Os quatro módulos do strip, com seus ícones
        for modulo in ('Reservas', 'Salas', 'Relatórios', 'Financeiro'):
            self.assertIn('painel-faixa-item', page)
            self.assertIn(modulo, page)
        self.assertIn('Rotina acadêmica sem conflito de horário', page)

    # --- Login renovado ---

    def test_login_tem_o_acabamento(self):
        """A tela de login traz os rótulos, o botão com seta e a nota."""
        page = self.client.get('/login').get_data(as_text=True)
        self.assertIn('E-mail institucional', page)
        self.assertIn('Use suas credenciais institucionais para continuar.', page)
        self.assertIn('Entrar no sistema', page)
        self.assertIn('Acesso protegido e restrito a usuários autorizados.', page)
        self.assertIn('login-campo', page)
        # Painel de marca com a frase de abertura e o rodapé institucional
        self.assertIn('Reservas e agendas em um só lugar.', page)
        self.assertIn('Senac Santa Catarina', page)

    def test_login_continua_funcionando(self):
        """Guarda de regressão: o acabamento não pode quebrar a autenticação."""
        resposta = self.client.post('/login',
                                    data={'email': EMAIL, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('Bem-vindo de volta', resposta.get_data(as_text=True))
        self.client.get('/logout')
        page = self.client.get('/dashboard', follow_redirects=True)
        self.assertIn('/login', page.request.url)

    def test_landing_usa_o_mesmo_formulario(self):
        """O card "Entrar no sistema" da landing renderiza o partial
        compartilhado com a página /login — mesma linguagem, sem divergir."""
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('login-campo', page)
        self.assertIn('Entrar no sistema', page)
        self.assertIn('Acesso protegido e restrito a usuários autorizados.', page)
        # Sem as faixas decorativas do layout antigo
        self.assertNotIn('faixa-topo', page)


if __name__ == '__main__':
    unittest.main()
