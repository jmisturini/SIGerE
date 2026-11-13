"""Testes da divisão da página de Salas e do filtro de intervalo de datas.

A listagem (/classrooms/) virou vitrine: só os cartões, sem bloco de
filtros. A pesquisa (/classrooms/search) carrega o bloco de filtros e
fica limpa até um filtro ser aplicado — sem filtro, nenhum cartão. O
filtro aceita um intervalo De/Até: a sala precisa estar livre nos
períodos escolhidos em TODOS os dias do intervalo; uma única reserva
aprovada em qualquer dia/período já a exclui. Fim antes do início é
trocado; sem data final, vale dia único.
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.blueprints.classrooms import _rotulo_disponibilidade_pdf
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role,
                        RoomCategory, Unity, User)
from werkzeug.datastructures import MultiDict

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class ClassroomsPesquisaTestCase(unittest.TestCase):
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

            perms = [
                Permission(code='system:export', module='system', action='export'),
                Permission(code='room:create', module='room', action='create'),
            ]
            db.session.add_all(perms)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            gestor = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()

            self.sala1 = Classroom(name='Sala Um', code='S1', capacity=30,
                                   unity_id=self.unity.id, category_id=category.id)
            self.sala2 = Classroom(name='Sala Dois', code='S2', capacity=30,
                                   unity_id=self.unity.id, category_id=category.id)
            db.session.add_all([self.sala1, self.sala2])
            db.session.commit()
            self.unity_id = self.unity.id
            self.gestor_id = gestor.id
            self.sala1_id = self.sala1.id
            self.sala2_id = self.sala2.id

        response = self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _dia(self, deslocamento=1):
        return date.today() + timedelta(days=deslocamento)

    def _reservar(self, sala_id, dia, start, end):
        with self.app.app_context():
            db.session.add(Reservation(
                user_id=self.gestor_id, classroom_id=sala_id, title='Aula Teste',
                date=dia, start_time=start, end_time=end,
                status='approved', unity_id=self.unity_id))
            db.session.commit()

    def _pesquisar(self, inicio, fim=None, *periodos):
        """GET da pesquisa com o intervalo De/Até e os períodos marcados."""
        query = f'available_date={inicio.isoformat()}'
        if fim:
            query += f'&available_date_end={fim.isoformat()}'
        for periodo in periodos:
            query += f'&available_period={periodo}'
        return self.client.get(f'/classrooms/search?{query}')

    def test_listagem_so_tem_cartoes(self):
        response = self.client.get('/classrooms/')
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Sala Um', html)
        self.assertIn('Sala Dois', html)
        self.assertIn('Adicionar Sala', html)
        # A vitrine não carrega o bloco de filtros nem o botão de PDF
        self.assertNotIn('filterForm', html)
        self.assertNotIn('available_date', html)
        self.assertNotIn('Exportar PDF', html)

    def test_pesquisa_renderiza_bloco_de_filtros(self):
        response = self.client.get('/classrooms/search')
        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('filterForm', html)
        self.assertIn('name="available_date"', html)
        self.assertIn('name="available_date_end"', html)
        # Sem filtros a página fica limpa: nenhum cartão, só o convite
        self.assertNotIn('Sala Um', html)
        self.assertNotIn('Sala Dois', html)
        self.assertIn('Pesquise uma sala', html)

    def test_pesquisa_com_filtro_mostra_resultado(self):
        # Categoria é um filtro por si só: os cartões voltam a aparecer
        with self.app.app_context():
            category_id = db.session.get(RoomCategory, db.session.get(Classroom, self.sala1_id).category_id).id
        response = self.client.get(f'/classrooms/search?category={category_id}')
        html = response.get_data(as_text=True)
        self.assertIn('Sala Um', html)
        self.assertIn('Sala Dois', html)

    def test_url_antiga_com_filtro_redireciona_para_pesquisa(self):
        # Bookmark da listagem antiga com filtro continua válido: 302 para
        # a pesquisa com a query string intacta, repetidos incluídos.
        response = self.client.get(
            f'/classrooms/?available_date={self._dia().isoformat()}'
            '&available_period=morning&available_period=afternoon')
        self.assertEqual(response.status_code, 302)
        location = response.headers['Location']
        self.assertIn('/classrooms/search?', location)
        self.assertIn(f'available_date={self._dia().isoformat()}', location)
        self.assertIn('available_period=morning', location)
        self.assertIn('available_period=afternoon', location)

    def test_vitrine_sem_filtro_nao_redireciona(self):
        response = self.client.get('/classrooms/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Sala Um', response.get_data(as_text=True))

    def test_vazio_por_categoria_cita_o_tipo(self):
        # Sem resultado num filtro só de categoria, o vazio fala do tipo —
        # não cita períodos/datas que o usuário não selecionou.
        with self.app.app_context():
            vazia = RoomCategory(name='Categoria Vazia', code='CV')
            db.session.add(vazia)
            db.session.commit()
            category_id = vazia.id
        html = self.client.get(
            f'/classrooms/search?category={category_id}').get_data(as_text=True)
        self.assertIn('Nenhuma sala do tipo', html)
        self.assertIn('Categoria Vazia', html)
        self.assertNotIn('Nenhuma sala livre nos períodos', html)

    def test_intervalo_exclui_ocupada_em_qualquer_dia(self):
        # Sala Um ocupada na manhã do 3º dia do intervalo
        self._reservar(self.sala1_id, self._dia(3), time(9, 0), time(11, 0))

        html = self._pesquisar(self._dia(1), self._dia(5), 'morning').get_data(as_text=True)
        self.assertNotIn('Sala Um', html)
        self.assertIn('Sala Dois', html)

        # Dia único antes da ocupação: a sala volta a aparecer
        html = self._pesquisar(self._dia(1), self._dia(1), 'morning').get_data(as_text=True)
        self.assertIn('Sala Um', html)

    def test_so_inicio_e_dia_unico(self):
        self._reservar(self.sala1_id, self._dia(3), time(9, 0), time(11, 0))

        # No próprio dia da reserva: excluída
        html = self._pesquisar(self._dia(3), None, 'morning').get_data(as_text=True)
        self.assertNotIn('Sala Um', html)

        # Em outro dia, sem data final: não filtra nada
        html = self._pesquisar(self._dia(1), None, 'morning').get_data(as_text=True)
        self.assertIn('Sala Um', html)

    def test_fim_antes_do_inicio_e_trocado(self):
        self._reservar(self.sala1_id, self._dia(1), time(9, 0), time(11, 0))

        # Intervalo invertido na URL cobre o dia da reserva após a troca
        html = self._pesquisar(self._dia(3), self._dia(1), 'morning').get_data(as_text=True)
        self.assertNotIn('Sala Um', html)

    def test_mensagem_mostra_o_intervalo(self):
        html = self._pesquisar(self._dia(1), self._dia(5), 'morning').get_data(as_text=True)
        self.assertIn('Mostrando salas disponíveis entre', html)
        self.assertIn(f'{self._dia(1):%d/%m/%Y}', html)
        self.assertIn(f'{self._dia(5):%d/%m/%Y}', html)

    def test_mensagem_mostra_o_intervalo_trocado_na_ordem_cronologica(self):
        html = self._pesquisar(self._dia(5), self._dia(1), 'morning').get_data(as_text=True)
        inicio_txt = f'{self._dia(1):%d/%m/%Y}'
        fim_txt = f'{self._dia(5):%d/%m/%Y}'
        self.assertLess(html.index(inicio_txt), html.index(fim_txt))

    def test_export_pdf_aceita_o_intervalo(self):
        self._reservar(self.sala1_id, self._dia(3), time(9, 0), time(11, 0))
        response = self._pesquisar(self._dia(1), self._dia(5), 'morning')
        # Mesma query string da pesquisa serve para o PDF (o botão Exportar
        # repassa a query string inteira)
        response = self.client.get(f'/classrooms/export_pdf?{response.request.query_string.decode()}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, 'application/pdf')


class RotuloDisponibilidadePdfTestCase(unittest.TestCase):
    """Rótulo 'Livres...' da meta do PDF: existe só com períodos marcados e
    descreve o intervalo efetivamente aplicado, nunca o valor cru da URL."""

    def test_sem_periodo_nao_afirma_livres(self):
        # Regressão (CodeRabbit): data + categoria sem período não consulta
        # reservas na listagem — o PDF não pode afirmar que estão livres.
        args = MultiDict([('available_date', '2026-11-16'),
                          ('available_date_end', '2026-11-20'),
                          ('category', '3')])
        self.assertIsNone(_rotulo_disponibilidade_pdf(args))

    def test_intervalo_com_periodo(self):
        args = MultiDict([('available_date', '2026-11-16'),
                          ('available_date_end', '2026-11-20'),
                          ('available_period', 'morning')])
        self.assertEqual(_rotulo_disponibilidade_pdf(args),
                         'Livres entre 16/11/2026 e 20/11/2026 pela manhã')

    def test_dia_unico_com_periodo(self):
        args = MultiDict([('available_date', '2026-11-16'),
                          ('available_period', 'evening')])
        self.assertEqual(_rotulo_disponibilidade_pdf(args),
                         'Livres em 16/11/2026 à noite')

    def test_varios_periodos_no_rotulo(self):
        args = MultiDict([('available_date', '2026-11-16'),
                          ('available_period', 'morning'),
                          ('available_period', 'afternoon')])
        self.assertEqual(_rotulo_disponibilidade_pdf(args),
                         'Livres em 16/11/2026 nos períodos de Manhã e Tarde')

    def test_data_invalida_mostra_o_dia_aplicado(self):
        # O filtro aplica o dia corrente quando o início é inválido — o
        # rótulo segue o filtro real, não o valor cru da URL.
        args = MultiDict([('available_date', 'nao-e-data'),
                          ('available_period', 'morning')])
        self.assertEqual(_rotulo_disponibilidade_pdf(args),
                         f'Livres em {date.today():%d/%m/%Y} pela manhã')

    def test_fim_antes_do_inicio_no_rotulo(self):
        args = MultiDict([('available_date', '2026-11-20'),
                          ('available_date_end', '2026-11-16'),
                          ('available_period', 'morning')])
        self.assertEqual(_rotulo_disponibilidade_pdf(args),
                         'Livres entre 16/11/2026 e 20/11/2026 pela manhã')


if __name__ == '__main__':
    unittest.main()
