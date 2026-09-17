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
from decimal import Decimal

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import (Permission, Role, Unity, User, VtEmpresa,
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

            # Global (sem unidade) para o teste das empresas compartilhadas.
            global_user = User(
                email='global@escola.edu', full_name='Conta Global',
                role='admin', profile_type='employee',
                role_id=gestor_role.id, force_password_change=False,
                is_active_user=True,
            )
            global_user.set_password(PASSWORD)
            db.session.add(global_user)
            db.session.commit()

            # 'Jotur' pertence à unidade; 'Estrela' é compartilhada (NULL).
            self.jotur_id = self._criar_empresa('Jotur', ['7,24', '10,10'])
            self.estrela_id = self._criar_empresa('Estrela', ['7,38'], unity_id=None)

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
            empresa.valores = [VtEmpresaValor(valor=Decimal(t.replace(',', '.')))
                               for t in tarifas]
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
        self.assertIn('R$ 7,24', page)
        self.assertIn('R$ 10,10', page)
        self.assertIn('Ativa', page)
        # A compartilhada aparece com o selo, mas sem botões de edição.
        self.assertIn('Compartilhada', page)
        self.assertNotIn(f'/admin/vt-empresas/{self.estrela_id}/edit', page)

    def test_admin_de_unidade_edita_so_as_proprias(self):
        """A empresa compartilhada é 404 para o admin de unidade."""
        response = self.client.get(f'/admin/vt-empresas/{self.estrela_id}/edit')
        self.assertEqual(response.status_code, 404)

    def test_conta_global_edita_compartilhada(self):
        self._login('global@escola.edu')
        response = self.client.get(f'/admin/vt-empresas/{self.estrela_id}/edit')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('7,38', page)
        self.assertIn('Estrela', page)

    def test_mesmo_nome_em_outra_unidade_permitido(self):
        """Nome já usado só por OUTRA unidade não bloqueia o cadastro aqui."""
        with self.app.app_context():
            outra = Unity(name='Unidade Sul', code='US')
            db.session.add(outra)
            db.session.commit()
            empresa = VtEmpresa(nome='Sul Transportes', is_active=True,
                                unity_id=outra.id)
            empresa.valores = [VtEmpresaValor(valor=Decimal('8.00'))]
            db.session.add(empresa)
            db.session.commit()

        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Sul Transportes', 'valores': '8,50',
        }, follow_redirects=True)
        self.assertIn('Sul Transportes criada com sucesso',
                      response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 4)

    # ---------- Criação ----------

    def test_criar_empresa(self):
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Consórcio Fênix',
            'valores': '7,20\n7,38',
            'is_active': 'y',
        }, follow_redirects=True)
        page = response.get_data(as_text=True)
        self.assertIn('Consórcio Fênix criada com sucesso', page)
        self.assertIn('R$ 7,20', page)

        # A empresa nova aparece nas opções do formulário público.
        publico = self.client.get('/vt/pedido')
        self.assertIn('Consórcio Fênix', publico.get_data(as_text=True))

    def test_criar_empresa_duplicada_rejeitada(self):
        # O flash aparece na re-renderização do próprio POST.
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'jotur', 'valores': '7,24',
        }, follow_redirects=True)
        self.assertIn('Já existe uma empresa com este nome',
                      response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 2)  # só Jotur e Estrela (setUp)

    def test_criar_empresa_sem_tarifa_rejeitada(self):
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Sem Tarifa', 'valores': '',
        }, follow_redirects=True)
        self.assertIn('Informe pelo menos uma tarifa', response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 2)

    def test_criar_empresa_tarifa_invalida_rejeitada(self):
        response = self.client.post('/admin/vt-empresas/create', data={
            'nome': 'Inválida', 'valores': '7,24\nabc',
        }, follow_redirects=True)
        # As aspas do texto chegam escapadas no HTML (&#34;abc&#34;).
        self.assertIn('Tarifa inválida', response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 2)

    # ---------- Edição ----------

    def test_editar_empresa(self):
        response = self.client.post(f'/admin/vt-empresas/{self.jotur_id}/edit', data={
            'nome': 'Jotur Transportes',
            'valores': '7,38\n12,08',
            'is_active': 'y',
        }, follow_redirects=True)
        self.assertIn('Jotur Transportes atualizada', response.get_data(as_text=True))

        with self.app.app_context():
            empresa = db.session.get(VtEmpresa, self.jotur_id)
            self.assertEqual(empresa.nome, 'Jotur Transportes')
            self.assertEqual([v.valor_texto for v in empresa.valores],
                             ['7,38', '12,08'])

        # O formulário público reflete a tarifa nova e abandona a antiga.
        publico = self.client.get('/vt/pedido')
        page = publico.get_data(as_text=True)
        self.assertIn('Jotur Transportes', page)
        self.assertNotIn('R$ 7,24', page)

    def test_editar_para_nome_de_outra_rejeitado(self):
        self._criar_empresa('Biguaçu', ['7,24'])
        response = self.client.post(f'/admin/vt-empresas/{self.jotur_id}/edit', data={
            'nome': 'Biguaçu', 'valores': '7,24',
        }, follow_redirects=True)
        self.assertIn('Já existe outra empresa com este nome',
                      response.get_data(as_text=True))

    def test_empresa_inativa_sai_do_formulario_publico(self):
        self.client.post(f'/admin/vt-empresas/{self.jotur_id}/edit', data={
            'nome': 'Jotur', 'valores': '7,24',
        }, follow_redirects=True)  # sem is_active: desmarca o checkbox

        page = self.client.get('/vt/pedido').get_data(as_text=True)
        self.assertNotIn('Jotur', page)

    # ---------- Exclusão ----------

    def test_excluir_empresa(self):
        response = self.client.post(f'/admin/vt-empresas/{self.jotur_id}/delete',
                                    follow_redirects=True)
        self.assertIn('Empresa Jotur excluída', response.get_data(as_text=True))
        self.assertEqual(self._contagem(), 1)  # resta a compartilhada Estrela


if __name__ == '__main__':
    unittest.main()
