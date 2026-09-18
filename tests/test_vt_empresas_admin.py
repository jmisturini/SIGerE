"""Administração das empresas de ônibus do pedido de VT (/admin/vt-empresas).

CRUD do cadastro de empresas e tarifas vigentes usado pelo formulário
público (/vt/pedido) — antes fixo em código. Cobre a exigência da
permissão vt:empresas, criação/edição/exclusão, nome duplicado, tarifa
inválida e a integração com o formulário público (empresa nova aparece
nas opções; empresa inativa sai).
"""
import os
import tempfile
import unittest
from datetime import date
from decimal import Decimal

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import (Permission, Role, Unity, User, VtConfig, VtEmpresa,
                        VtEmpresaValor)

EMAIL = 'gestor-empresas@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class VtEmpresasAdminTestCase(unittest.TestCase):
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
                     for c in ('vt:empresas',)]
            gestor_role = Role(name='gestor-empresas', label='Gestor de Empresas',
                               permissions=perms)
            db.session.add(gestor_role)
            db.session.flush()

            gestor = User(
                email=EMAIL, full_name='Gestor Empresas', role='room',
                profile_type='employee', unity_id=self.unity.id,
                role_id=gestor_role.id, force_password_change=False,
                is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)

            db.session.commit()

            # 'Jotur' pertence à unidade; 'Estrela' é compartilhada (NULL).
            self.jotur_id = self._criar_empresa(
                'Jotur', [('Patamar 2', '7,24'), ('Patamar 1', '3,62')])
            self.estrela_id = self._criar_empresa(
                'Estrela', [('Patamar 1', '7,38')])

        self._login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _criar_empresa(self, nome, tarifas, unity_id='__none__'):
        with self.app.app_context():
            empresa = VtEmpresa(
                nome=nome, is_active=True,
                unity_id=self.unity.id if unity_id == '__none__' else unity_id)
            empresa.valores = [VtEmpresaValor(identificacao=i,
                                              valor=Decimal(v.replace(',', '.')))
                               for i, v in tarifas]
            db.session.add(empresa)
            db.session.commit()
            return empresa.id

    def _login(self, email=EMAIL):
        # Encerra a sessão anterior: logar já autenticado só redireciona,
        # sem trocar o usuário.
        self.client.get('/logout')
        response = self.client.post('/login', data={'email': email, 'password': PASSWORD},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('E-mail ou senha inválidos', response.get_data(as_text=True))

    def _contagem(self):
        with self.app.app_context():
            return VtEmpresa.query.count()

    # ---------- Permissão ----------

    def test_listagem_exige_permissao(self):
        """Sem vt:empresas, a página é 403 mesmo com outras permissões VT."""
        with self.app.app_context():
            role = Role.query.filter_by(name='gestor-empresas').first()
            role.permissions = [Permission.query.filter_by(code='vt:read').first()]
            db.session.commit()
        response = self.client.get('/admin/vt-empresas')
        self.assertEqual(response.status_code, 403)

    # ---------- Listagem ----------

    def test_listagem_mostra_empresas_e_tarifas(self):
        response = self.client.get('/admin/vt-empresas')
        page = response.get_data(as_text=True)
        self.assertIn('Jotur', page)
        self.assertIn('Patamar 2 — R$ 7,24', page)
        self.assertIn('Patamar 1 — R$ 3,62', page)
        self.assertIn('Ativa', page)
        # Todas as empresas listadas pertencem à unidade e são editáveis.
        self.assertIn(f'/admin/vt-empresas/{self.jotur_id}/edit', page)
        self.assertIn(f'/admin/vt-empresas/{self.estrela_id}/edit', page)

    def test_empresa_de_outra_unidade_invisivel(self):
        """Empresa de outra unidade: 404 na edição e ausente na listagem."""
        with self.app.app_context():
            outra = Unity(name='Unidade Sul', code='US')
            db.session.add(outra)
            db.session.commit()
            sul_id = outra.id
        outra_id = self._criar_empresa('Sul Transportes',
                                       [('Patamar 1', '8,00')],
                                       unity_id=sul_id)

        page = self.client.get('/admin/vt-empresas').get_data(as_text=True)
        self.assertNotIn('Sul Transportes', page)
        response = self.client.get(f'/admin/vt-empresas/{outra_id}/edit')
        self.assertEqual(response.status_code, 404)
        response = self.client.post(f'/admin/vt-empresas/{outra_id}/delete',
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 404)

    def test_mesmo_nome_em_outra_unidade_permitido(self):
        """Nome já usado só por OUTRA unidade não bloqueia o cadastro aqui."""
        with self.app.app_context():
            outra = Unity(name='Unidade Sul', code='US')
            db.session.add(outra)
            db.session.commit()
            empresa = VtEmpresa(nome='Sul Transportes', is_active=True,
                                unity_id=outra.id)
            empresa.valores = [VtEmpresaValor(identificacao='Patamar 1',
                                              valor=Decimal('8.00'))]
            db.session.add(empresa)
            db.session.commit()

        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Sul Transportes',
            'identificacao': ['Patamar 1'],
            'valor': ['8,50'],
        }, follow_redirects=True)
        self.assertIn('Sul Transportes criada com sucesso',
                      response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 4)

    # ---------- Criação ----------

    def test_formulario_criacao_sem_autofill(self):
        """O formulário de empresa desabilita o autocomplete: os campos de
        tarifa têm nomes genéricos (identificacao/valor) e o navegador
        repetia neles valores armazenados de envios anteriores ao abrir o
        cadastro de uma empresa nova."""
        page = self.client.get('/admin/vt-empresas/create').get_data(as_text=True)
        self.assertIn('<form method="POST" novalidate id="form-empresa" autocomplete="off">',
                      page)
        # Formulário + 2 campos da linha inicial + 2 do modelo clonável.
        self.assertGreaterEqual(page.count('autocomplete="off"'), 5)

    def test_criar_empresa(self):
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Consórcio Fênix',
            'identificacao': ['Patamar 1', 'Patamar 6'],
            'valor': ['7,20', '12,25'],
            'is_active': 'y',
        }, follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Consórcio Fênix criada com sucesso', page)
        self.assertIn('Patamar 1 — R$ 7,20', page)
        self.assertIn('Patamar 6 — R$ 12,25', page)

        # A empresa nova aparece nas opções do formulário público, com as
        # linhas de tarifa (identificação + valor).
        publico = self.client.get('/vt/pedido')
        page_publico = publico.get_data(as_text=True)
        self.assertIn('Consórcio Fênix', page_publico)
        self.assertIn('Patamar 1 — R$ 7,20', page_publico)

    def test_criar_empresa_duplicada_rejeitada(self):
        # O flash aparece na re-renderização do próprio POST.
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'jotur', 'identificacao': ['Patamar 1'], 'valor': ['7,24'],
        }, follow_redirects=True)
        self.assertIn('Já existe uma empresa com este nome',
                      response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 2)  # só Jotur e Estrela (setUp)

    def test_criar_empresa_sem_tarifa_rejeitada(self):
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Sem Tarifa', 'identificacao': [], 'valor': [],
        }, follow_redirects=True)
        self.assertIn('Adicione pelo menos uma tarifa',
                      response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 2)

    def test_criar_empresa_tarifa_invalida_rejeitada(self):
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Inválida', 'identificacao': ['Patamar 1'], 'valor': ['abc'],
        }, follow_redirects=True)
        self.assertIn('Valor de tarifa inválido', response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 2)

    def test_criar_empresa_sem_identificacao_rejeitada(self):
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Sem Identificacao', 'identificacao': [''], 'valor': ['7,24'],
        }, follow_redirects=True)
        self.assertIn('Informe a identificação de cada tarifa',
                      response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 2)

    def test_criar_empresa_identificacao_repetida_rejeitada(self):
        """Repetição é detectada ignorando maiúsculas/minúsculas."""
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Repetida', 'identificacao': ['Patamar 1', 'patamar 1'],
            'valor': ['7,24', '7,50'],
        }, follow_redirects=True)
        self.assertIn('mais de uma tarifa', response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 2)

    # ---------- Edição ----------

    def test_editar_empresa(self):
        response = self.client.post(f'/admin/vt-empresas/{self.jotur_id}/edit', data={
            'nome': 'Jotur Transportes',
            'identificacao': ['Patamar 3', 'Patamar 1'],
            'valor': ['7,38', '3,69'],
            'is_active': 'y',
        }, follow_redirects=True)
        self.assertIn('Jotur Transportes atualizada', response.get_data(as_text=True))

        with self.app.app_context():
            empresa = db.session.get(VtEmpresa, self.jotur_id)
            self.assertEqual(empresa.nome, 'Jotur Transportes')
            # A listagem ordena por valor (relationship), não pela ordem digitada.
            self.assertEqual({(v.identificacao, v.valor_texto) for v in empresa.valores},
                             {('Patamar 3', '7,38'), ('Patamar 1', '3,69')})

        # O formulário público reflete a tarifa nova e abandona a antiga.
        publico = self.client.get('/vt/pedido')
        page = publico.get_data(as_text=True)
        self.assertIn('Jotur Transportes', page)
        self.assertNotIn('R$ 7,24', page)

    def test_editar_para_nome_de_outra_rejeitado(self):
        self._criar_empresa('Biguaçu', [('Patamar 5', '7,24')])
        response = self.client.post(f'/admin/vt-empresas/{self.jotur_id}/edit', data={
            'nome': 'Biguaçu', 'identificacao': ['Patamar 5'], 'valor': ['7,24'],
        }, follow_redirects=True)
        self.assertIn('Já existe outra empresa com este nome',
                      response.get_data(as_text=True))

    def test_empresa_inativa_sai_do_formulario_publico(self):
        self.client.post(f'/admin/vt-empresas/{self.jotur_id}/edit', data={
            'nome': 'Jotur', 'identificacao': ['Patamar 2'], 'valor': ['7,24'],
        }, follow_redirects=True)  # sem is_active: desmarca o checkbox

        page = self.client.get('/vt/pedido').get_data(as_text=True)
        self.assertNotIn('Jotur', page)

    # ---------- Configuração do pedido ----------

    def test_configuracao_salva_e_exibe(self):
        """Página de configuração salva números base de vales e a data de
        fechamento para a unidade ativa."""
        response = self.client.post('/admin/vt-configuracao', data={
            'vales_somente_ida': '2',
            'vales_ida_e_volta': '4',
            'fecha_em': '2026-12-31',
        }, follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Configurações do pedido de VT salvas', page)
        self.assertIn('Aberto até', page)
        self.assertIn('31/12/2026', page)

        with self.app.app_context():
            config = VtConfig.query.filter_by(unity_id=self.unity.id).first()
            self.assertEqual(config.vales_somente_ida, 2)
            self.assertEqual(config.vales_ida_e_volta, 4)
            self.assertEqual(str(config.fecha_em), '2026-12-31')

    def test_configuracao_vales_parciais_rejeitados(self):
        """Informar só um dos números base é rejeitado (valem em par)."""
        response = self.client.post('/admin/vt-configuracao', data={
            'vales_somente_ida': '2',
        }, follow_redirects=True)
        self.assertIn('Informe os dois números base de vales',
                      response.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(VtConfig.query.filter_by(
                unity_id=self.unity.id).first())

    def test_configuracao_fechado_no_pedido_publico(self):
        """Ponta a ponta: configuração com fechamento no passado bloqueia o
        formulário público da unidade."""
        with self.app.app_context():
            db.session.add(VtConfig(unity_id=self.unity.id,
                                    fecha_em=date(2026, 1, 1)))
            db.session.commit()
        page = self.client.get(f'/vt/pedido?unity={self.unity.id}').get_data(as_text=True)
        self.assertIn('Formulário encerrado', page)

    # ---------- Exclusão ----------

    def test_excluir_empresa(self):
        response = self.client.post(f'/admin/vt-empresas/{self.jotur_id}/delete',
                                    follow_redirects=True)
        self.assertIn('Empresa Jotur excluída', response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 1)  # resta a compartilhada Estrela


if __name__ == '__main__':
    unittest.main()
