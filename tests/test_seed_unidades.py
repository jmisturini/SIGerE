"""Testes do comando `flask seed-unidades` e da rota que relê o arquivo
de unidades pelo painel (botão "Reler arquivo" na listagem de unidades).

O comando/cada rota cadastra as unidades do Senac SC a partir do JSON
extraído do portal (docs/unidades-senac-sc.json): cria as ausentes,
atualiza as existentes e ignora registros sem `cadastro_sugerido`.
"""
import json
import os
import tempfile
import unittest

from app import create_app
from app.commands import UNIDADES_JSON_PADRAO
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, Unity, User

USERNAME = 'super.teste'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SeedUnidadesCommandTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        with self.app.app_context():
            db.create_all()
        with open(UNIDADES_JSON_PADRAO, encoding='utf-8') as fh:
            data = json.load(fh)
        # Unidades efetivamente cadastráveis (com bloco cadastro_sugerido).
        self.esperadas = [u for u in data['unidades'] if u.get('cadastro_sugerido')]
        self.ignorados = [u for u in data['unidades'] if not u.get('cadastro_sugerido')]

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_seed_unidades_cria_unidades_do_json(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['seed-unidades'])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(f"Criadas: {len(self.esperadas)}", result.output)
        with self.app.app_context():
            self.assertEqual(db.session.query(Unity).count(), len(self.esperadas))
            ara = db.session.query(Unity).filter_by(code='ARA').first()
            self.assertIsNotNone(ara)
            self.assertEqual(ara.name, 'Senac Araranguá')
            self.assertIn('88900-015', ara.address)
            self.assertEqual(ara.phone, '(48) 3522-1192')
            self.assertEqual(ara.weather_city, 'Araranguá, SC')
            # JSON atual traz is_active=false em todos os cadastros (debug)
            self.assertFalse(ara.is_active)

    def test_seed_unidades_ignora_registros_sem_cadastro(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['seed-unidades'])
        self.assertEqual(result.exit_code, 0, result.output)
        for ignorado in self.ignorados:
            self.assertIn(ignorado['nome'], result.output)
        with self.app.app_context():
            nomes = {u.name for u in db.session.query(Unity).all()}
            for ignorado in self.ignorados:
                self.assertNotIn(ignorado['nome'], nomes)

    def test_seed_unidades_e_idempotente(self):
        runner = self.app.test_cli_runner()
        primeira = runner.invoke(args=['seed-unidades'])
        self.assertEqual(primeira.exit_code, 0, primeira.output)
        segunda = runner.invoke(args=['seed-unidades'])
        self.assertEqual(segunda.exit_code, 0, segunda.output)
        self.assertIn(f"Atualizadas: {len(self.esperadas)}", segunda.output)
        self.assertIn("Criadas: 0", segunda.output)
        with self.app.app_context():
            self.assertEqual(db.session.query(Unity).count(), len(self.esperadas))
            # Dados sobrevivem à reexecução
            ara = db.session.query(Unity).filter_by(code='ARA').first()
            self.assertEqual(ara.name, 'Senac Araranguá')
            # is_active do JSON é imposto também na atualização: mesmo que
            # alguém reative a unidade, reler o arquivo a desativa de novo.
            ara.is_active = True
            db.session.commit()
        terceira = runner.invoke(args=['seed-unidades'])
        self.assertEqual(terceira.exit_code, 0, terceira.output)
        with self.app.app_context():
            ara = db.session.query(Unity).filter_by(code='ARA').first()
            self.assertFalse(ara.is_active)

    def test_seed_unidades_atualiza_dados_alterados(self):
        runner = self.app.test_cli_runner()
        self.assertEqual(runner.invoke(args=['seed-unidades']).exit_code, 0)
        with open(UNIDADES_JSON_PADRAO, encoding='utf-8') as fh:
            data = json.load(fh)
        registro = next(u for u in data['unidades']
                        if u['cadastro_sugerido']['code'] == 'ARA')
        registro['cadastro_sugerido']['phone'] = '(48) 99999-0000'
        fd, tmp_path = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False)
        try:
            result = runner.invoke(args=['seed-unidades', '--file', tmp_path])
            self.assertEqual(result.exit_code, 0, result.output)
        finally:
            os.remove(tmp_path)
        with self.app.app_context():
            ara = db.session.query(Unity).filter_by(code='ARA').first()
            self.assertEqual(ara.phone, '(48) 99999-0000')

    def test_seed_unidades_falha_com_arquivo_inexistente(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['seed-unidades', '--file', 'inexistente.json'])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn('não encontrado', result.output)


class UnidadesSyncRouteTestCase(unittest.TestCase):
    """Botão "Reler arquivo" da listagem: POST /admin/unities/sync."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with open(UNIDADES_JSON_PADRAO, encoding='utf-8') as fh:
            data = json.load(fh)
        self.esperadas = [u for u in data['unidades'] if u.get('cadastro_sugerido')]

        with self.app.app_context():
            db.create_all()
            curinga = Permission(code='*', module='system', action='all')
            sem_perm = Permission(code='unity:read', module='unity', action='read')
            db.session.add_all([curinga, sem_perm])
            db.session.flush()
            role_super = Role(name='super_teste', label='Super Teste', permissions=[curinga])
            role_leitura = Role(name='leitura', label='Somente leitura', permissions=[sem_perm])
            db.session.add_all([role_super, role_leitura])
            db.session.flush()
            super_user = User(
                username=USERNAME, email='super@escola.edu', full_name='Super Teste',
                role='admin', profile_type='employee', role_id=role_super.id,
                force_password_change=False, is_active_user=True,
            )
            super_user.set_password(PASSWORD)
            leitor = User(
                username='leitor.teste', email='leitor@escola.edu', full_name='Leitor',
                role='gestor', profile_type='employee', role_id=role_leitura.id,
                force_password_change=False, is_active_user=True,
            )
            leitor.set_password(PASSWORD)
            db.session.add_all([super_user, leitor])
            db.session.commit()
        self._login(USERNAME, PASSWORD)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, username, password):
        response = self.client.post('/login', data={'username': username, 'password': password},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def test_botao_reler_arquivo_aparece_na_listagem(self):
        page = self.client.get('/admin/unities').get_data(as_text=True)
        self.assertIn('Reler arquivo', page)
        self.assertIn('/admin/unities/sync', page)

    def test_sync_cria_unidades_e_redireciona_para_listagem(self):
        response = self.client.post('/admin/unities/sync', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn(f"Criadas: {len(self.esperadas)}", page)
        with self.app.app_context():
            self.assertEqual(db.session.query(Unity).count(), len(self.esperadas))

    def test_sync_e_idempotente(self):
        self.client.post('/admin/unities/sync')
        response = self.client.post('/admin/unities/sync', follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn(f"Atualizadas: {len(self.esperadas)}", page)
        self.assertIn("Criadas: 0", page)
        with self.app.app_context():
            self.assertEqual(db.session.query(Unity).count(), len(self.esperadas))

    def test_sync_exige_permissao_de_criar_unidade(self):
        # /login não troca de usuário com sessão ativa — deslogar primeiro.
        self.client.get('/logout')
        self._login('leitor.teste', PASSWORD)
        response = self.client.post('/admin/unities/sync')
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
