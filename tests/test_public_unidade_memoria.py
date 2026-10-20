"""Memória da unidade escolhida no portal público (/cronograma, /buscar-aula).

A escolha de unidade (?unity= na URL, pelo seletor ou pela detecção de
unidade próxima) fica memorizada na sessão do visitante: navegar entre as
páginas públicas pelo menu — cujos links não carregam ?unity= — não reseta
mais a seleção. Uma unidade desativada depois da escolha (ou um ?unity=
inválido) cai para o fallback da primeira ativa, sem erro.
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Unity


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class PublicUnidadeMemoriaTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()
            # Duas unidades: AAA é o fallback (primeira ativa por nome)
            db.session.add_all([
                Unity(name='Unidade AAA', code='AAA', is_active=True),
                Unity(name='Unidade BBB', code='BBB', is_active=True),
            ])
            db.session.commit()
            self.bbb_id = Unity.query.filter_by(code='BBB').first().id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _unidade_na_pagina(self, page):
        """Nome da unidade no rótulo do seletor (botão do dropdown)."""
        marcador = '</i>Unidade '
        inicio = page.index(marcador) + len(marcador)
        return page[inicio:page.index('<', inicio)].strip()

    def test_escolha_persiste_ao_trocar_de_pagina(self):
        page = self.client.get(f'/cronograma?unity={self.bbb_id}').get_data(as_text=True)
        self.assertEqual(self._unidade_na_pagina(page), 'BBB')

        # Menu público não carrega ?unity=: a sessão mantém a escolha
        page = self.client.get('/buscar-aula').get_data(as_text=True)
        self.assertEqual(self._unidade_na_pagina(page), 'BBB')
        page = self.client.get('/cronograma').get_data(as_text=True)
        self.assertEqual(self._unidade_na_pagina(page), 'BBB')

    def test_primeira_visita_cai_na_primeira_ativa(self):
        page = self.client.get('/cronograma').get_data(as_text=True)
        self.assertEqual(self._unidade_na_pagina(page), 'AAA')

    def test_escolha_troca_quando_url_traz_outra_unidade(self):
        self.client.get(f'/cronograma?unity={self.bbb_id}')
        page = self.client.get('/buscar-aula?unity=1').get_data(as_text=True)
        self.assertEqual(self._unidade_na_pagina(page), 'AAA')
        page = self.client.get('/cronograma').get_data(as_text=True)
        self.assertEqual(self._unidade_na_pagina(page), 'AAA')

    def test_parametro_invalido_nao_estraga_a_escolha(self):
        self.client.get(f'/cronograma?unity={self.bbb_id}')
        page = self.client.get('/cronograma?unity=99999').get_data(as_text=True)
        self.assertEqual(self._unidade_na_pagina(page), 'BBB')
        page = self.client.get('/buscar-aula').get_data(as_text=True)
        self.assertEqual(self._unidade_na_pagina(page), 'BBB')

    def test_unidade_desativada_cai_para_fallback(self):
        self.client.get(f'/cronograma?unity={self.bbb_id}')
        with self.app.app_context():
            bbb = db.session.get(Unity, self.bbb_id)
            bbb.is_active = False
            db.session.commit()

        # Com uma ativa só o seletor nem renderiza: a unidade aparece no
        # estado vazio ("... na unidade ..."). A visita seguinte também cai
        # no fallback — a escolha morta saiu da sessão.
        for _ in range(2):
            page = self.client.get('/cronograma').get_data(as_text=True)
            self.assertIn('Unidade AAA', page)
            self.assertNotIn('Unidade BBB', page)


if __name__ == '__main__':
    unittest.main()
