"""Testes da área de perfil do usuário (autoatendimento).

Cobre: visualização dos dados, atualização de nome e departamento, e troca
opcional de senha com verificação da senha atual.
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import User

EMAIL = 'maria@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class UserProfileTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            self.user = User(email=EMAIL, full_name='Maria Souza', role='room',
                             profile_type='teacher', department='Informática',
                             force_password_change=False, is_active_user=True)
            self.user.set_password(PASSWORD)
            db.session.add(self.user)
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

    def _usuario(self):
        with self.app.app_context():
            user = db.session.query(User).filter_by(email=EMAIL).first()
            dados = {'nome': user.full_name, 'departamento': user.department,
                     'hash': user.password_hash}
            return dados

    # ---------- visualização ----------

    def test_exige_login(self):
        self.client.get('/logout')
        response = self.client.get('/perfil')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers.get('Location', ''))

    def test_perfil_mostra_dados_atuais(self):
        page = self.client.get('/perfil').get_data(as_text=True)
        self.assertIn('Meu Perfil', page)
        self.assertIn('Maria Souza', page)
        self.assertIn('Informática', page)
        self.assertIn(EMAIL, page)
        # o e-mail (login) não é editável no perfil
        self.assertIn('disabled', page)

    def test_menu_tem_link_para_o_perfil(self):
        page = self.client.get('/dashboard').get_data(as_text=True)
        self.assertIn('Meu Perfil', page)
        self.assertIn('/perfil', page)

    # ---------- atualização de nome e departamento ----------

    def test_atualiza_nome_e_departamento(self):
        response = self.client.post('/perfil',
                                    data={'full_name': 'Maria Souza de Almeida',
                                          'department': 'T.I'},
                                    follow_redirects=True)
        self.assertIn('Seu perfil foi atualizado com sucesso', response.get_data(as_text=True))
        dados = self._usuario()
        self.assertEqual(dados['nome'], 'Maria Souza de Almeida')
        self.assertEqual(dados['departamento'], 'T.I')

    def test_sem_senha_a_senha_nao_muda(self):
        self.client.post('/perfil', data={'full_name': 'Maria Souza',
                                          'department': 'Informática'})
        dados = self._usuario()
        hash_antes = dados['hash']
        # login com a senha antiga continua funcionando
        self.client.get('/logout')
        login = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                                 follow_redirects=True)
        self.assertIn('Bem-vindo', login.get_data(as_text=True))
        self.assertEqual(self._usuario()['hash'], hash_antes)

    def test_nome_obrigatorio(self):
        response = self.client.post('/perfil', data={'full_name': '', 'department': ''},
                                    follow_redirects=True)
        self.assertIn('Este campo é obrigatório', response.get_data(as_text=True))

    # ---------- troca de senha ----------

    def test_troca_de_senha_com_sucesso(self):
        response = self.client.post('/perfil',
                                    data={'full_name': 'Maria Souza',
                                          'department': 'Informática',
                                          'current_password': PASSWORD,
                                          'password': 'NovaSenha456',
                                          'confirm_password': 'NovaSenha456'},
                                    follow_redirects=True)
        self.assertIn('Seu perfil foi atualizado com sucesso', response.get_data(as_text=True))
        self.client.get('/logout')
        falha = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                                 follow_redirects=True)
        # a senha antiga não entra mais
        self.assertIn('E-mail ou senha inválidos', falha.get_data(as_text=True))
        acerto = self.client.post('/login', data={'email': EMAIL, 'password': 'NovaSenha456'},
                                  follow_redirects=True)
        self.assertIn('Bem-vindo', acerto.get_data(as_text=True))

    def test_senha_atual_errada_recusada(self):
        response = self.client.post('/perfil',
                                    data={'full_name': 'Maria Souza',
                                          'current_password': 'Errada123',
                                          'password': 'NovaSenha456',
                                          'confirm_password': 'NovaSenha456'})
        self.assertIn('Senha atual incorreta', response.get_data(as_text=True))

    def test_senha_atual_ausente_recusada(self):
        response = self.client.post('/perfil',
                                    data={'full_name': 'Maria Souza',
                                          'password': 'NovaSenha456',
                                          'confirm_password': 'NovaSenha456'})
        self.assertIn('Informe sua senha atual para alterar a senha', response.get_data(as_text=True))

    def test_nova_senha_igual_a_atual_recusada(self):
        response = self.client.post('/perfil',
                                    data={'full_name': 'Maria Souza',
                                          'current_password': PASSWORD,
                                          'password': PASSWORD,
                                          'confirm_password': PASSWORD})
        self.assertIn('não pode ser igual à senha atual', response.get_data(as_text=True))

    def test_confirmacao_diferente_recusada(self):
        response = self.client.post('/perfil',
                                    data={'full_name': 'Maria Souza',
                                          'current_password': PASSWORD,
                                          'password': 'NovaSenha456',
                                          'confirm_password': 'Diferente789'})
        self.assertIn('As senhas não coincidem', response.get_data(as_text=True))

    def test_nova_senha_curta_recusada(self):
        response = self.client.post('/perfil',
                                    data={'full_name': 'Maria Souza',
                                          'current_password': PASSWORD,
                                          'password': 'curta1',
                                          'confirm_password': 'curta1'})
        self.assertIn('pelo menos 8 caracteres', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
