"""Testes do comando `flask seed-unidades`.

O comando cadastra as unidades do Senac SC a partir do JSON extraído do
portal (docs/unidades-senac-sc.json): cria as ausentes, atualiza as
existentes e ignora registros sem `cadastro_sugerido`.
"""
import json
import os
import tempfile
import unittest

from app import create_app
from app.commands import UNIDADES_JSON_PADRAO
from app.config import Config
from app.extensions import db
from app.models import Unity


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
            self.assertTrue(ara.is_active)

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


if __name__ == '__main__':
    unittest.main()
