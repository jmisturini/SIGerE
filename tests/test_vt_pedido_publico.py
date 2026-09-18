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
from datetime import date, timedelta
from decimal import Decimal

from openpyxl import load_workbook

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import (Permission, Role, Unity, User, VtConfig, VtEmpresa,
                        VtEmpresaValor, VtRequest)

EMAIL = 'gestor-vt@escola.edu'
PASSWORD = 'SenhaForte123'

# Mesmas empresas/tarifas que a migration c8d4a1e6f2b9 semeia no banco real
# (com trajeto por linha de tarifa — a migration f9c1a4e7b2d6 as deixa com
# trajeto NULL, aqui o teste já cadastra completo).
EMPRESAS_INICIAIS = {
    'Consórcio Fênix': [('Patamar 1', '7,20')],
    'Jotur': [('Patamar 2', '7,24'), ('Patamar 1', '3,62')],
    'Biguaçu': [('Patamar 5', '10,23'), ('Patamar 1', '5,12')],
    'Estrela': [('Patamar 3', '7,38')],
}


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
            self.unity_id = self.unity.id
            _seed_permissions()
            db.session.commit()

            perms = [Permission.query.filter_by(code=c).first()
                     for c in ('vt:read', 'vt:export')]
            gestor_role = Role(name='gestor-vt', label='Gestor de VT',
                               permissions=perms)
            db.session.add(gestor_role)
            db.session.flush()

            # Colaboradores com cadastro no sistema (para identificação
            # automática pelo e-mail): funcionário e professor.
            maria = User(email='maria@escola.edu', full_name='Maria Identificada',
                         registration='555777', role='room',
                         profile_type='employee', unity_id=self.unity.id,
                         force_password_change=False, is_active_user=True)
            maria.set_password(PASSWORD)
            db.session.add(maria)
            professor = User(email='prof@escola.edu', full_name='Prof Identificado',
                             registration='888999', role='teacher',
                             profile_type='teacher', unity_id=self.unity.id,
                             force_password_change=False, is_active_user=True)
            professor.set_password(PASSWORD)
            db.session.add(professor)

            # Empresas do cadastro administrado (/admin/vt-empresas),
            # pertencentes à unidade do teste.
            for nome, tarifas in EMPRESAS_INICIAIS.items():
                empresa = VtEmpresa(nome=nome, is_active=True,
                                    unity_id=self.unity.id)
                empresa.valores = [VtEmpresaValor(identificacao=i,
                                                  valor=Decimal(v.replace(',', '.')))
                                   for i, v in tarifas]
                db.session.add(empresa)
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

    def _linha_id(self, empresa_nome, identificacao):
        """Id da linha de tarifa (empresa + identificação, ex.: Patamar 2) —
        o select de valor do pedido grava o id da linha do cadastro."""
        with self.app.app_context():
            empresa = VtEmpresa.query.filter_by(nome=empresa_nome).first()
            return next(v.id for v in empresa.valores
                        if v.identificacao == identificacao)

    def _payload_sim_uma_empresa(self, **overrides):
        base = dict(
            optant='Sim',
            link='Técnico - Administrativo',
            company_count='1',
            company_a_name='Jotur',
            company_a_value=str(self._linha_id('Jotur', 'Patamar 2')),
            company_a_passes='22',
            company_a_route='Ida e Volta')
        base.update(overrides)
        return self._payload(**base)

    def _pedidos(self):
        with self.app.app_context():
            return [dict(email=p.email, full_name=p.full_name,
                         registration=p.registration,
                         optant=p.optant, unity=p.unity,
                         link=p.link, company_count=p.company_count,
                         company_a_name=p.company_a_name,
                         company_a_value=p.company_a_value,
                         company_a_passes=p.company_a_passes,
                         company_a_route=p.company_a_route,
                         company_b_name=p.company_b_name,
                         company_b_value=p.company_b_value,
                         company_b_route=p.company_b_route)
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
        self.assertIn('name="company_a_value"', page)
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
        self.assertEqual(dados['vinculo'], 'Técnico - Administrativo')

        response = self.client.get('/vt/pedido/colaborador?email=prof@escola.edu')
        self.assertEqual(response.get_json()['vinculo'], 'Professor(a)')

        response = self.client.get(
            '/vt/pedido/colaborador?email=desconhecido@senac.sc.br')
        self.assertEqual(response.get_json(), {'found': False,
                                               'full_name': None,
                                               'registration': None,
                                               'vinculo': None})

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
        # Sem pergunta de unidade: o pedido registra a unidade do link.
        self.assertEqual(pedido['unity'], 'Unidade Teste')
        self.assertEqual(pedido['company_count'], 1)
        self.assertEqual(pedido['company_a_name'], 'Jotur')
        self.assertEqual(float(pedido['company_a_value']), 7.24)
        self.assertEqual(pedido['company_a_passes'], 22)
        # O trajeto vem da linha de tarifa escolhida.
        self.assertEqual(pedido['company_a_route'], 'Ida e Volta')
        self.assertIsNone(pedido['company_b_name'])

    def test_post_sim_duas_empresas(self):
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            company_count='2',
            company_b_name='Biguaçu',
            company_b_value=str(self._linha_id('Biguaçu', 'Patamar 5')),
            company_b_passes='10',
            company_b_route='Ida e Volta'), follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))

        pedido = self._pedidos()[0]
        self.assertEqual(pedido['company_count'], 2)
        self.assertEqual(pedido['company_b_name'], 'Biguaçu')
        self.assertEqual(float(pedido['company_b_value']), 10.23)
        self.assertEqual(pedido['company_b_route'], 'Ida e Volta')

    def test_post_valor_invalido_para_empresa_rejeitado(self):
        """A tarifa precisa ser da empresa escolhida: linha da Fênix com
        Jotur selecionado é rejeitada."""
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            company_a_value=str(self._linha_id('Consórcio Fênix', 'Patamar 1'))))
        self.assertIn('A tarifa selecionada não pertence à empresa escolhida.',
                      response.get_data(as_text=True))
        self.assertEqual(self._pedidos(), [])

    def test_post_sem_valor_rejeitado(self):
        payload = self._payload_sim_uma_empresa()
        payload.pop('company_a_value')
        response = self.client.post('/vt/pedido', data=payload)
        self.assertIn('Selecione o valor do vale.', response.get_data(as_text=True))
        self.assertEqual(self._pedidos(), [])

    def test_post_sim_incompleto_rejeitado(self):
        """"Sim" sem vínculo/empresas: formulário volta com erros e nada é
        gravado — o POST forjado não furta a ramificação."""
        response = self.client.post('/vt/pedido', data=self._payload(optant='Sim'))
        page = response.get_data(as_text=True)
        self.assertIn('Selecione o vínculo.', page)
        self.assertIn('Selecione o número de empresas de ônibus.', page)
        self.assertIn('Selecione a empresa de ônibus.', page)
        self.assertEqual(self._pedidos(), [])

    def test_vinculo_sempre_perguntado(self):
        """Sem a pergunta de unidade, o vínculo é escolhido livremente
        (Professor(a) incluído) em qualquer unidade."""
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            link='Professor(a)'), follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))
        self.assertEqual(self._pedidos()[0]['link'], 'Professor(a)')

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

    def test_pedidos_escopados_por_unidade(self):
        """O pedido fica na unidade do link usado: o enviado para a unidade
        Sul não aparece na listagem da unidade Teste."""
        with self.app.app_context():
            sul = Unity(name='Unidade Sul', code='US')
            db.session.add(sul)
            db.session.commit()
            sul_id = sul.id
        teste_id = self.unity_id

        self.client.post(f'/vt/pedido?unity={sul_id}',
                         data=self._payload_sim_uma_empresa(
                             full_name='Colaborador Sul'))
        self.client.post(f'/vt/pedido?unity={teste_id}', data=self._payload())

        self._login()
        page = self.client.get('/vt/pedidos').get_data(as_text=True)
        self.assertIn('Colaborador Teste', page)
        self.assertNotIn('Colaborador Sul', page)

    def test_empresas_do_formulario_sao_por_unidade(self):
        """Cada link mostra apenas as empresas da própria unidade."""
        with self.app.app_context():
            sul = Unity(name='Unidade Sul', code='US')
            db.session.add(sul)
            db.session.commit()
            sul_id = sul.id
            empresa = VtEmpresa(nome='Empresa Sul', is_active=True,
                                unity_id=sul_id)
            empresa.valores = [VtEmpresaValor(valor=Decimal('9,99'.replace(',', '.')))]
            db.session.add(empresa)
            db.session.commit()

        page_padrao = self.client.get(f'/vt/pedido?unity={self.unity_id}').get_data(as_text=True)
        self.assertNotIn('Empresa Sul', page_padrao)
        self.assertIn('Jotur', page_padrao)  # empresa da própria unidade

        page_sul = self.client.get(f'/vt/pedido?unity={sul_id}').get_data(as_text=True)
        self.assertIn('Empresa Sul', page_sul)
        self.assertIn('Unidade Sul', page_sul)
        self.assertNotIn('Jotur', page_sul)  # empresa da outra unidade

    def test_unidade_invalida_cai_no_fallback(self):
        """?unity inválido usa a primeira unidade ativa."""
        page = self.client.get('/vt/pedido?unity=99999').get_data(as_text=True)
        self.assertIn('Unidade Teste', page)

    def test_email_cadastrado_trava_dados_no_servidor(self):
        """E-mail de conta ativa: nome, matrícula e vínculo vêm do cadastro
        mesmo que o POST tente enviar outros valores."""
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            email='maria@escola.edu',
            full_name='Nome Forjado',
            registration='000000',
            link='Professor(a)'), follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))

        pedido = self._pedidos()[0]
        self.assertEqual(pedido['full_name'], 'Maria Identificada')
        self.assertEqual(pedido['email'], 'maria@escola.edu')

        with self.app.app_context():
            pedido_bd = VtRequest.query.first()
            self.assertEqual(pedido_bd.registration, '555777')
            self.assertEqual(pedido_bd.link, 'Técnico - Administrativo')

    def test_email_de_professor_define_vinculo(self):
        """Professor identificado pelo cadastro tem vínculo Professor(a)."""
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            email='prof@escola.edu'), follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))

        with self.app.app_context():
            pedido_bd = VtRequest.query.first()
            self.assertEqual(pedido_bd.full_name, 'Prof Identificado')
            self.assertEqual(pedido_bd.link, 'Professor(a)')

    def test_vales_acima_de_49_rejeitados(self):
        """O nº de vales é livre, mas sempre menor que 50."""
        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            company_a_passes='50'))
        self.assertIn('Informe um número de vales menor que 50.',
                      response.get_data(as_text=True))
        self.assertEqual(self._pedidos(), [])

    def test_config_fechamento_bloqueia_formulario(self):
        """Com data de fechamento no passado, o formulário exibe a mensagem
        de encerrado e rejeita o POST (nada é gravado)."""
        with self.app.app_context():
            config = VtConfig(unity_id=self.unity_id,
                              fecha_em=date.today() - timedelta(days=1))
            db.session.add(config)
            db.session.commit()

        page = self.client.get('/vt/pedido').get_data(as_text=True)
        self.assertIn('Formulário encerrado', page)
        self.assertNotIn('id="form-pedido"', page)

        response = self.client.post('/vt/pedido', data=self._payload(),
                                    follow_redirects=True)
        self.assertNotIn('Pedido enviado com sucesso',
                         response.get_data(as_text=True))
        self.assertEqual(self._pedidos(), [])

    def test_config_fechamento_futuro_exibe_prazo(self):
        """Data de fechamento no futuro: formulário aberto e prazo exibido."""
        prazo = date.today() + timedelta(days=5)
        with self.app.app_context():
            db.session.add(VtConfig(unity_id=self.unity_id, fecha_em=prazo))
            db.session.commit()

        page = self.client.get('/vt/pedido').get_data(as_text=True)
        self.assertIn('Preenchimento até', page)
        self.assertIn(prazo.strftime('%d/%m/%Y'), page)
        self.assertIn('id="form-pedido"', page)

    def test_config_botao_valor_base(self):
        """Com números base configurados, o formulário oferece o botão
        "Usar valor base" (o valor continua livre para ajuste)."""
        with self.app.app_context():
            db.session.add(VtConfig(unity_id=self.unity_id,
                                    vales_somente_ida=2,
                                    vales_ida_e_volta=4))
            db.session.commit()

        page = self.client.get('/vt/pedido').get_data(as_text=True)
        self.assertIn('Usar valor base', page)
        self.assertIn('name="company_a_passes"', page)

        response = self.client.post('/vt/pedido', data=self._payload_sim_uma_empresa(
            company_a_passes='2', company_a_route='Somente Volta'),
            follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))
        pedido = self._pedidos()[0]
        self.assertEqual(pedido['company_a_route'], 'Somente Volta')
        self.assertEqual(pedido['company_a_passes'], 2)

    def test_sem_config_vales_continuam_manuais(self):
        """Sem configuração de vales, o campo manual segue no formulário,
        sem o botão de valor base."""
        page = self.client.get('/vt/pedido').get_data(as_text=True)
        self.assertIn('name="company_a_passes"', page)
        self.assertNotIn('data-sufixo=', page)

        payload = self._payload_sim_uma_empresa()
        payload.pop('company_a_passes')
        response = self.client.post('/vt/pedido', data=payload)
        self.assertIn('Digite o número de vales necessários.',
                      response.get_data(as_text=True))
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
        self.assertIn('Jotur', page)
        self.assertIn('R$ 7.24 × 22 vale(s)', page)
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


class TestPedidosVT(unittest.TestCase):
    """Página unificada Pedidos VT (/vt/pedidos): layout e funções da antiga
    listagem de Colaboradores — filtros, ordenação, correção individual
    (editar/excluir) e planilha de pagamento por grupo gerada dos pedidos.
    A importação do Pedido de Compra saiu do ar (/vt/ e /vt/colaboradores
    viraram redirecionamentos)."""

    EMAIL_GESTOR = 'gestor-vt@escola.edu'
    EMAIL_EDITOR = 'editor-vt@escola.edu'
    PASSWORD = 'SenhaForte123'

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            # Unidade "Faculdade": com vínculo Técnico - Administrativo o
            # pedido cai no grupo "faculdade" da planilha de pagamento.
            self.unity = Unity(name='Faculdade', code='FAC')
            db.session.add(self.unity)
            db.session.commit()
            self.unity_id = self.unity.id
            _seed_permissions()
            db.session.commit()

            def _role(nome, codigos):
                perms = [Permission.query.filter_by(code=c).first()
                         for c in codigos]
                role = Role(name=nome, label=nome, permissions=perms)
                db.session.add(role)
                db.session.flush()
                return role

            gestor_role = _role('gestor-vt', ('vt:read', 'vt:export'))
            editor_role = _role('editor-vt', ('vt:read', 'vt:edit',
                                              'vt:delete', 'vt:export'))
            for email, role in ((self.EMAIL_GESTOR, gestor_role),
                                (self.EMAIL_EDITOR, editor_role)):
                usuario = User(email=email, full_name=email.split('@')[0],
                               registration=email.split('@')[0],
                               role='room', profile_type='employee',
                               unity_id=self.unity.id, role_id=role.id,
                               force_password_change=False,
                               is_active_user=True)
                usuario.set_password(self.PASSWORD)
                db.session.add(usuario)

            empresa = VtEmpresa(nome='Jotur', is_active=True,
                                unity_id=self.unity.id)
            empresa.valores = [VtEmpresaValor(identificacao='Patamar 2',
                                              valor=Decimal('7.24'))]
            db.session.add(empresa)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email=EMAIL_EDITOR):
        response = self.client.post('/login', data={'email': email,
                                                    'password': self.PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _linha_id(self):
        with self.app.app_context():
            empresa = VtEmpresa.query.filter_by(nome='Jotur').first()
            return empresa.valores[0].id

    def _payload_sim(self, **overrides):
        payload = {
            'email': 'colaborador@senac.sc.br',
            'full_name': 'Colaborador Teste',
            'registration': '123456',
            'optant': 'Sim',
            'link': 'Técnico - Administrativo',
            'company_count': '1',
            'company_a_name': 'Jotur',
            'company_a_value': str(self._linha_id()),
            'company_a_passes': '22',
            'company_a_route': 'Ida e Volta',
        }
        payload.update(overrides)
        return payload

    def _criar_pedido(self, **overrides):
        response = self.client.post('/vt/pedido', data=self._payload_sim(**overrides),
                                    follow_redirects=True)
        self.assertIn('Pedido enviado com sucesso', response.get_data(as_text=True))

    # ---------- Redirecionamentos da importação removida ----------

    def test_importacao_e_colaboradores_redirecionam(self):
        for url in ('/vt/', '/vt/colaboradores'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.location.endswith('/vt/pedidos'))

    # ---------- Listagem no layout de Colaboradores ----------

    def test_listagem_mostra_totais_e_grupos(self):
        self._criar_pedido()
        self._criar_pedido(email='prof@senac.sc.br', full_name='Ana Professora',
                           registration='654321', link='Professor(a)')
        self._criar_pedido(email='nao@senac.sc.br', full_name='Bruno Não Optante',
                           registration='111222', optant='Não')

        self._login(self.EMAIL_GESTOR)
        page = self.client.get('/vt/pedidos').get_data(as_text=True)
        self.assertIn('Pedidos VT', page)
        self.assertIn('Exportar planilha de pagamento', page)
        # Total do pedido Sim: 7,24 × 22 vales.
        self.assertIn('R$ 159.28', page)
        # Badge de empresas com a tarifa no tooltip.
        self.assertIn('R$ 7.24 × 22 vale(s)', page)
        # Contagem de exportáveis por grupo.
        self.assertIn('Técnico-Administrativo (Faculdade): 1', page)
        self.assertIn('Professores: 1', page)
        self.assertIn('2</strong> desejando VT', page)

    def test_listagem_filtros(self):
        self._criar_pedido()
        self._criar_pedido(email='prof@senac.sc.br', full_name='Ana Professora',
                           registration='654321', link='Professor(a)')
        self._criar_pedido(email='nao@senac.sc.br', full_name='Bruno Não Optante',
                           registration='111222', optant='Não')

        self._login(self.EMAIL_GESTOR)

        # Busca por nome/e-mail/matrícula.
        page = self.client.get('/vt/pedidos?q=654321').get_data(as_text=True)
        self.assertIn('Ana Professora', page)
        self.assertNotIn('Colaborador Teste', page)

        # Filtro por vínculo.
        page = self.client.get('/vt/pedidos?link=Professor(a)').get_data(as_text=True)
        self.assertIn('Ana Professora', page)
        self.assertNotIn('Colaborador Teste', page)

        # Esconder não optantes / valor R$ 0,00.
        page = self.client.get('/vt/pedidos?ocultar_sem_vt=1').get_data(as_text=True)
        self.assertNotIn('Bruno Não Optante', page)
        self.assertIn('Colaborador Teste', page)

        # Ordenação por valor total (maior primeiro): 22 vales antes de 2.
        self._criar_pedido(email='pequeno@senac.sc.br', full_name='Zeca Poucos Vales',
                           registration='333444', company_a_passes='2')
        page = self.client.get('/vt/pedidos?sort=valor').get_data(as_text=True)
        self.assertLess(page.index('Colaborador Teste'),
                        page.index('Zeca Poucos Vales'))

    def test_filtro_vinculo_so_oferece_vinculos_atuais(self):
        """O select de vínculo lista apenas os vínculos do formulário atual —
        valores antigos gravados na base (ex.: importações) não viram opção."""
        self._criar_pedido()
        with self.app.app_context():
            db.session.add(VtRequest(email='antigo@senac.sc.br',
                                     full_name='Registro Antigo',
                                     registration='999999', optant='Não',
                                     link='Estagiário'))
            db.session.commit()

        self._login()
        page = self.client.get('/vt/pedidos').get_data(as_text=True)
        self.assertIn('<option value="Técnico - Administrativo"', page)
        self.assertIn('<option value="Professor(a)"', page)
        self.assertNotIn('<option value="Estagiário"', page)

    # ---------- Correção individual ----------

    def test_editar_pedido_prefill_e_gravacao(self):
        self._criar_pedido()
        with self.app.app_context():
            pedido_id = VtRequest.query.first().id

        self._login()
        page = self.client.get(f'/vt/pedidos/{pedido_id}/editar').get_data(as_text=True)
        # A linha de tarifa gravada (valor 7,24) vem pré-selecionada.
        self.assertIn(f'<option selected value="{self._linha_id()}">', page)

        response = self.client.post(f'/vt/pedidos/{pedido_id}/editar',
                                    data=self._payload_sim(company_a_passes='30'),
                                    follow_redirects=True)
        self.assertIn('Pedido de Colaborador Teste atualizado', response.get_data(as_text=True))
        with self.app.app_context():
            pedido = db.session.get(VtRequest, pedido_id)
            self.assertEqual(pedido.company_a_passes, 30)
            self.assertEqual(pedido.total_value, 217.2)

        page = self.client.get('/vt/pedidos').get_data(as_text=True)
        self.assertIn('R$ 217.20', page)

    def test_excluir_pedido(self):
        self._criar_pedido()
        with self.app.app_context():
            pedido_id = VtRequest.query.first().id

        self._login()
        response = self.client.post(f'/vt/pedidos/{pedido_id}/excluir',
                                    follow_redirects=True)
        self.assertIn('Pedido de Colaborador Teste excluído', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(VtRequest.query.count(), 0)

    def test_gestor_sem_permissao_nao_edita_nem_exclui(self):
        """vt:edit/vt:delete são exigidas na correção — o gestor só leitor
        (vt:read + vt:export) recebe 403."""
        self._criar_pedido()
        with self.app.app_context():
            pedido_id = VtRequest.query.first().id

        self._login(self.EMAIL_GESTOR)
        self.assertEqual(
            self.client.get(f'/vt/pedidos/{pedido_id}/editar').status_code, 403)
        self.assertEqual(
            self.client.post(f'/vt/pedidos/{pedido_id}/excluir').status_code, 403)

    # ---------- Planilha de pagamento gerada dos pedidos ----------

    def test_exportar_pagamento_por_grupo(self):
        self._criar_pedido()
        self._criar_pedido(email='prof@senac.sc.br', full_name='Ana Professora',
                           registration='654321', link='Professor(a)')
        self._criar_pedido(email='nao@senac.sc.br', full_name='Bruno Não Optante',
                           registration='111222', optant='Não')

        self._login(self.EMAIL_GESTOR)
        response = self.client.get('/vt/pedidos/exportar-pagamento?group=faculdade')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spreadsheetml', response.headers['Content-Type'])

        workbook = load_workbook(io.BytesIO(response.data))
        worksheet = workbook['Vale Transporte']
        # Linha 5 é a primeira do modelo; apenas o pedido Sim do grupo.
        self.assertEqual(worksheet['A5'].value, 123456)
        self.assertEqual(worksheet['B5'].value, 'Colaborador Teste')
        self.assertAlmostEqual(worksheet['C5'].value, 159.28)
        self.assertIsNone(worksheet['A6'].value)

    def test_exportar_pagamento_sem_elegiveis_avisa(self):
        self._criar_pedido(optant='Não', link='')
        self._login(self.EMAIL_GESTOR)
        response = self.client.get('/vt/pedidos/exportar-pagamento',
                                   follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Nenhum pedido elegível para o grupo selecionado', page)


if __name__ == '__main__':
    unittest.main()
