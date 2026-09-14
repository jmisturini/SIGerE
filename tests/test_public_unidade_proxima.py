"""Seletor de unidade do portal público com detecção pela geolocalização.

As páginas /cronograma e /buscar-aula oferecem a opção "Detectar pela minha
localização" quando há mais de uma unidade ativa com coordenadas
(weather_latitude/weather_longitude) cadastradas — ver
app/templates/_unidade_publica.html e app/static/js/unidade-proxima.js.
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


class PublicUnidadeProximaTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()
        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _criar_unidades(self, *codigos, com_coords=True):
        with self.app.app_context():
            for i, codigo in enumerate(codigos):
                db.session.add(Unity(
                    name=f'Unidade {codigo}', code=codigo, is_active=True,
                    weather_latitude=(-27.6 - i / 10) if com_coords else None,
                    weather_longitude=(-48.5 - i / 10) if com_coords else None,
                ))
            db.session.commit()

    def test_cronograma_com_varias_unidades_oferece_deteccao(self):
        self._criar_unidades('AAA', 'BBB')
        page = self.client.get('/cronograma').get_data(as_text=True)
        self.assertIn('data-unity-detect', page)
        self.assertIn('Detectar pela minha localização', page)
        self.assertIn('unidade-proxima.js', page)
        # Coordenadas vão para o cliente, que calcula a unidade mais próxima.
        self.assertIn('SIGERE_UNIDADES_PUBLICAS', page)
        self.assertIn('-27.6', page)

    def test_cronograma_sem_coordenadas_nao_oferece_deteccao(self):
        self._criar_unidades('AAA', 'BBB', com_coords=False)
        page = self.client.get('/cronograma').get_data(as_text=True)
        self.assertNotIn('data-unity-detect', page)
        # A escolha manual pela lista continua disponível.
        self.assertIn('Unidade AAA', page)

    def test_cronograma_com_uma_unidade_nao_renderiza_seletor(self):
        self._criar_unidades('AAA')
        page = self.client.get('/cronograma').get_data(as_text=True)
        self.assertNotIn('data-unity-detect', page)
        self.assertNotIn('SIGERE_UNIDADES_PUBLICAS', page)

    def test_buscar_aula_renderiza_seletor_e_preserva_contexto(self):
        self._criar_unidades('AAA', 'BBB')
        page = self.client.get('/buscar-aula?unity=2&q=calculo').get_data(as_text=True)
        self.assertIn('data-unity-detect', page)
        # Campo oculto do formulário mantém a unidade escolhida na busca.
        self.assertIn('<input type="hidden" name="unity" value="2">', page)
        # Trocar a unidade pelo seletor preserva a consulta e a data atuais.
        self.assertIn('q=calculo', page)


if __name__ == '__main__':
    unittest.main()
