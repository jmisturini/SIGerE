"""Pedido público de Vale-Transporte (/vt/pedido) e suas respostas.

A página pública replica o formulário "Pedido de Vale-Transporte"
(Microsoft Forms) com acesso anônimo identificado apenas pelo e-mail:
"Deseja VT = Não" encerra o pedido; "Sim" exige unidade, vínculo e os
blocos de empresa/vales/trajeto (a segunda empresa só quando o
colaborador declara usar 2). Cobre o POST público, a validação da
ramificação, a listagem restrita (vt:read + módulo Financeiro) e a
exportação .xlsx.
"""
import io
import os
import tempfile
import unittest

from openpyxl import load_workbook

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, Unity, User, VtRequest

EMAIL = 'gestor-vt@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class VtPedidoPublicoTestCase(unittest.TestCase):
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
                     for c in ('vt:read', 'vt:export')]
            gestor_role = Role(name='gestor-vt', label='Gestor de VT',
                               permissions=perms)
            db.session.add(gestor_role)
            db.session.flush()

            gestor = User(
                email=EMAIL, full_name='Gestor VT', role='room',
                profile_type='employee', unity_id=self.unity.id,
                role_id=gestor_role.id, force_password_change=False,
                is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)
            db.session.commit()

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
        self.assertNotIn('E-mail ou senha inválidos', response.get_data(as_text=True))

    def _payload(self, **overrides):
        payload = {
            'email': 'colaborador@senac.sc.br',
            'full_name': 'Colaborador Teste',
            'registration': '123456',
            'optant': 'Não',
        }
        payload.update(overrides)
        return payload

    def _payload_sim_uma_empresa(self, **overrides):
        base = dict(
            optant='Sim',
            unity='Faculdade',
            link='Técnico - Administrativo',
            company_count='1',
            company_a_name='Jotur - R$ 7,24',
            company_a_passes='22',
            company_a_route='Ida e Volta')
        base.update(overrides)
        return self._payload(**base)

    def _pedidos(self):
        with self.app.app_context():
            return [dict(email=p.email, optant=p.optant, unity=p.unity,
                         link=p.link, company_count=p.company_count,
                         company_a_name=p.company_a_name,
                         company_a_passes=p.company_a_passes,
                         company_a_route=p.company_a_route,
                         company_b_name=p.company_b_name)
                    for p in VtRequest.query.all()]

    # ---------- Página pública ----------

    def test_formulario_publico_sem_login(self):
        """A página do pedido é acessível anônima, sem a barra lateral do
        painel, e traz as perguntas com o botão de envio desabilitado."""
        response = self.client.get('/vt/pedido')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('Pedido de Vale-Transporte', page)
        self.assertIn('name="email"', page)
        self.assertIn('name="optant"', page)
        self.assertIn('name="company_a_name"', page)
        self.assertIn('sem-sidebar', page)
        self.assertNotIn('<nav class="sidebar">', page)
        self.assertIn('disabled', page)
        self.assertIn('name="link"', page)

    def test_outras_paginas_mantem_sidebar(self):
        """O esconderijo da sidebar vale só para a página do pedido."""
        response = self.client.get('/login')
        page = response.get_data(as_text=True)
        self.assertIn('<nav class="sidebar">', page)

    def test_busca_colaborador_por_email(self):
        """Auto-preenchimento: e-mail de conta ativa devolve nome e
        matrícula (busca sem diferenciar maiúsculas); e-mail desconhecido
        devolve found=false."""
        response = self.client.get(
            '/vt/pedido/colaborador?email=GESTOR-VT@escola.edu')
        self.assertEqual(response.status_code, 200)
        dados = response.get_json()
        self.assertTrue(dados['found'])
        self.assertEqual(dados['full_name'], 'Gestor VT')

        response = self.client.get(
            '/vt/pedido/colaborador?email=desconhecido@senac.sc.br')
        self.assertEqual(response.get_json(), {'found': False,
                                               'full_name': None,
                                               'registration': None})

    # ---------- POST público ----------

    def test_post_nao_registra_so_identificacao(self):
        """"Não" para o mês: pedido salvo sem nenhuma informação de empresa."""
        response = self.client.post('/vt/pedido', data=self._payload(),
                                    follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))

        pedidos = self._pedidos()
        self.assertEqual(len(pedidos), 1)
        self.assertEqual(pedidos[0]['optant'], 'Não')
        self.assertEqual(pedidos[0]['company_count'], 0)
        self.assertIsNone(pedidos[0]['company_a_name'])

    def test_post_sim_uma_empresa(self):
        response = self.client.post('/vt/pedido',
                                    data=self._payload_sim_uma_empresa(),
                                    follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))

        pedido = self._pedidos()[0]
        self.assertEqual(pedido['optant'], 'Sim')
        self.assertEqual(pedido['unity'], 'Faculdade')
        self.assertEqual(pedido['company_count'], 1)
        self.assertEqual(pedido['company_a_name'], 'Jotur - R$ 7,24')
        self.assertEqual(pedido['company_a_passes'], 22)
        self.assertEqual(pedido['company_a_route'], 'Ida e Volta')
        self.assertIsNone(pedido['company_b_name'])

    def test_post_sim_duas_empresas(self):
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            company_count='2',
            company_b_name='Biguaçu - R$ 10,23',
            company_b_passes='10',
            company_b_route='Somente Volta'), follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))

        pedido = self._pedidos()[0]
        self.assertEqual(pedido['company_count'], 2)
        self.assertEqual(pedido['company_b_name'], 'Biguaçu - R$ 10,23')

    def test_post_sim_incompleto_rejeitado(self):
        """"Sim" na Faculdade sem vínculo/empresas: formulário volta com
        erros e nada é gravado — o POST forjado não furta a ramificação."""
        response = self.client.post('/vt/pedido', data=self._payload(
            optant='Sim', unity='Faculdade'))
        page = response.get_data(as_text=True)
        self.assertIn('Selecione o vínculo.', page)
        self.assertIn('Selecione o número de empresas de ônibus.', page)
        self.assertIn('Selecione a empresa de ônibus.', page)
        self.assertEqual(self._pedidos(), [])

    def test_post_sim_sem_unidade_rejeitado(self):
        response = self.client.post('/vt/pedido', data=self._payload(optant='Sim'))
        self.assertIn('Selecione a unidade.', response.get_data(as_text=True))
        self.assertEqual(self._pedidos(), [])

    def test_unidade_restaurante_assume_tecnico_administrativo(self):
        """Fora da Faculdade o vínculo não é perguntado: o pedido sai como
        Técnico-Administrativo mesmo sem o campo no POST (o que o JS faz ao
        desabilitar o bloco)."""
        payload = self._payload_sim_uma_empresa(
            unity='Restaurante - ALESC/Palácio Barriga Verde')
        payload.pop('link')
        response = self.client.post('/vt/pedido', data=payload,
                                    follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))
        pedido = self._pedidos()[0]
        self.assertEqual(pedido['link'], 'Técnico - Administrativo')

    def test_vinculo_forjado_com_restaurante_e_corrigido(self):
        """POST forjado com outro vínculo nas unidades do Restaurante/
        Lanchonete é sobrescrito para Técnico-Administrativo."""
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            unity='Lanchonete - ALESC/Unidade Administrativa',
            link='Professor(a)'), follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))
        self.assertEqual(self._pedidos()[0]['link'], 'Técnico - Administrativo')

    def test_post_sim_segunda_empresa_faltando_rejeitado(self):
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            company_count='2'), follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Selecione a segunda empresa de ônibus.', page)
        self.assertEqual(self._pedidos(), [])

    def test_post_email_invalido_rejeitado(self):
        response = self.client.post('/vt/pedido',
                                    data=self._payload(email='sem-arroba'),
                                    follow_redirects=True)
        self.assertIn('Endereço de e-mail inválido.', response.get_data(as_text=True))
        self.assertEqual(self._pedidos(), [])

    # ---------- Listagem e exportação (restritas) ----------

    def test_listagem_exige_login(self):
        response = self.client.get('/vt/pedidos')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_listagem_mostra_pedidos(self):
        self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa())
        self.client.post('/vt/pedido', data=self._payload(
            email='outro@senac.sc.br', full_name='Outro Colaborador'))

        self._login()
        response = self.client.get('/vt/pedidos')
        page = response.get_data(as_text=True)
        self.assertIn('Colaborador Teste', page)
        self.assertIn('colaborador@senac.sc.br', page)
        self.assertIn('Jotur - R$ 7,24', page)
        self.assertIn('Outro Colaborador', page)
        self.assertIn('2 pedido(s)', page)

    def test_listagem_filtro_optant(self):
        self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa())
        self.client.post('/vt/pedido', data=self._payload(
            email='outro@senac.sc.br', full_name='Outro Colaborador'))

        self._login()
        response = self.client.get('/vt/pedidos?optant=Sim')
        page = response.get_data(as_text=True)
        self.assertIn('Colaborador Teste', page)
        self.assertNotIn('Outro Colaborador', page)

    def test_exportacao_xlsx(self):
        self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa())
        self._login()
        response = self.client.get('/vt/pedidos/exportar')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response.headers['Content-Type'])

        workbook = load_workbook(io.BytesIO(response.data))
        rows = list(workbook.active.iter_rows(values_only=True))
        self.assertEqual(rows[0][:4], ('Data', 'E-mail', 'Nome', 'Matrícula'))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][2], 'Colaborador Teste')
        self.assertEqual(rows[1][8], 'Jotur - R$ 7,24')


if __name__ == '__main__':
    unittest.main()
