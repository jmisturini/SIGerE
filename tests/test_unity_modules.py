"""Testes da modularização por unidade.

Cada unidade liga/desliga os próprios módulos opcionais (Cozinha e
Financeiro) no painel — botões na listagem de unidades e checkboxes no
formulário. Reservas de Sala é o core do sistema e não pode ser desativado.
"""
import os
import tempfile
import unittest

from app import create_app
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


class UnityModulesTestCase(unittest.TestCase):
    """Base: duas unidades (Alfa sem Cozinha, Beta sem Financeiro) e usuários
    com permissões de cada módulo distribuídos entre elas."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            def perm(code, module, action):
                p = Permission(code=code, module=module, action=action)
                db.session.add(p)
                return p

            curinga = perm('*', 'system', 'all')
            p_unity_read = perm('unity:read', 'unity', 'read')
            p_unity_edit = perm('unity:edit', 'unity', 'edit')
            p_unity_toggle = perm('unity:toggle', 'unity', 'toggle')
            p_unity_modules = perm('unity:modules', 'unity', 'modules')
            p_kitchen = perm('kitchen:read', 'kitchen', 'read')
            p_payment = perm('payment:read', 'payment', 'read')
            p_own = perm('reservation:read_own', 'reservation', 'read_own')
            db.session.flush()

            role_super = Role(name='super_teste', label='Super Teste',
                              permissions=[curinga])
            role_leitor = Role(name='leitor', label='Somente leitura',
                               permissions=[p_unity_read])
            role_admin_unidade = Role(name='admin_unidade', label='Admin da Unidade',
                                      permissions=[p_unity_read, p_unity_edit,
                                                   p_unity_toggle, p_unity_modules])
            role_cozinha = Role(name='cozinha', label='Cozinha',
                                permissions=[p_kitchen])
            role_financeiro = Role(name='financeiro', label='Financeiro',
                                   permissions=[p_payment])
            role_reserva = Role(name='reserva', label='Reservas',
                                permissions=[p_own])
            db.session.add_all([role_super, role_leitor, role_admin_unidade,
                                role_cozinha, role_financeiro, role_reserva])
            db.session.flush()

            def unity(name, code, kitchen=True, finance=True):
                u = Unity(name=name, code=code, is_active=True,
                          kitchen_enabled=kitchen, finance_enabled=finance)
                db.session.add(u)
                return u

            # Alfa: Cozinha desligado | Beta: Financeiro desligado
            self.alfa = unity('Unidade Alfa', 'ALF', kitchen=False)
            self.beta = unity('Unidade Beta', 'BET', finance=False)
            db.session.flush()

            def user(username, role, unity_obj=None):
                u = User(username=username, email=f'{username}@escola.edu',
                         full_name=username.title(), role='viewer',
                         profile_type='employee', role_id=role.id,
                         unity_id=unity_obj.id if unity_obj else None,
                         force_password_change=False, is_active_user=True)
                u.set_password(PASSWORD)
                db.session.add(u)
                return u

            user(USERNAME, role_super)
            user('leitor.teste', role_leitor)
            # Admin vinculado à Alfa (pode gerenciar módulos da própria unidade)
            user('admin.alfa', role_admin_unidade, self.alfa)
            # Conta global com a permissão, mas SEM vínculo com unidade nenhuma
            user('admin.global', role_admin_unidade)
            user('cozinha.alfa', role_cozinha, self.alfa)
            user('cozinha.beta', role_cozinha, self.beta)
            user('financeiro.alfa', role_financeiro, self.alfa)
            user('financeiro.beta', role_financeiro, self.beta)
            user('reserva.alfa', role_reserva, self.alfa)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, username, password=PASSWORD):
        response = self.client.post('/login',
                                    data={'username': username, 'password': password},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _unity_id(self, code):
        with self.app.app_context():
            return db.session.query(Unity).filter_by(code=code).first().id


class TestModeloModulos(UnityModulesTestCase):
    def test_unidade_nova_tem_modulos_ativos(self):
        with self.app.app_context():
            u = Unity(name='Unidade Gama', code='GAM')
            db.session.add(u)
            db.session.commit()
            self.assertTrue(u.kitchen_enabled)
            self.assertTrue(u.finance_enabled)
            self.assertTrue(u.is_module_enabled(Unity.MODULE_KITCHEN))
            self.assertTrue(u.is_module_enabled(Unity.MODULE_FINANCE))

    def test_modulo_core_reservas_nao_pode_ser_desativado(self):
        with self.app.app_context():
            alfa = db.session.query(Unity).filter_by(code='ALF').first()
            # Mesmo com ambos os módulos opcionais desligados, o core fica ativo
            alfa.kitchen_enabled = False
            alfa.finance_enabled = False
            self.assertTrue(alfa.is_module_enabled('reservation'))
            self.assertFalse(alfa.is_module_enabled(Unity.MODULE_KITCHEN))

    def test_estado_por_unidade_e_independente(self):
        with self.app.app_context():
            alfa = db.session.query(Unity).filter_by(code='ALF').first()
            beta = db.session.query(Unity).filter_by(code='BET').first()
            self.assertFalse(alfa.is_module_enabled(Unity.MODULE_KITCHEN))
            self.assertTrue(alfa.is_module_enabled(Unity.MODULE_FINANCE))
            self.assertTrue(beta.is_module_enabled(Unity.MODULE_KITCHEN))
            self.assertFalse(beta.is_module_enabled(Unity.MODULE_FINANCE))


class TestBloqueioDeRotas(UnityModulesTestCase):
    def test_cozinha_bloqueada_na_unidade_sem_modulo(self):
        self._login('cozinha.alfa')
        self.assertEqual(self.client.get('/kitchen/fichas').status_code, 403)

    def test_cozinha_funciona_na_unidade_com_modulo(self):
        self._login('cozinha.beta')
        self.assertEqual(self.client.get('/kitchen/fichas').status_code, 200)

    def test_financeiro_bloqueado_na_unidade_sem_modulo(self):
        self._login('financeiro.beta')
        self.assertEqual(self.client.get('/payments/overtime/list').status_code, 403)
        self.assertEqual(self.client.get('/vt/').status_code, 403)

    def test_financeiro_funciona_na_unidade_com_modulo(self):
        self._login('financeiro.alfa')
        self.assertEqual(self.client.get('/payments/overtime/list').status_code, 200)

    def test_reservas_core_funciona_mesmo_com_modulos_desligados(self):
        self._login('reserva.alfa')
        self.assertEqual(self.client.get('/reservations/my').status_code, 200)

    def test_menu_esconde_cozinha_desligada(self):
        self._login('financeiro.alfa')
        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertIn('Financeiro', page)          # módulo ligado na unidade
        self.assertNotIn('Ficha Técnica', page)    # cozinha desligada

    def test_menu_esconde_financeiro_desligado(self):
        self._login('cozinha.beta')
        page = self.client.get('/kitchen/fichas').get_data(as_text=True)
        self.assertIn('Cozinha', page)             # módulo ligado na unidade
        self.assertNotIn('Hora Extra', page)       # financeiro desligado


class TestTogglePeloPainel(UnityModulesTestCase):
    def test_listagem_nao_exibe_botoes_de_modulos(self):
        """A coluna de módulos saiu da listagem para economizar espaço: os
        botões ficam apenas na página de edição da unidade."""
        self._login(USERNAME)
        page = self.client.get('/admin/unities').get_data(as_text=True)
        self.assertNotIn('/modules/kitchen/toggle', page)
        self.assertNotIn('/modules/finance/toggle', page)

    def test_pagina_de_edicao_exibe_botoes_para_o_super_admin(self):
        self._login(USERNAME)
        alfa_id = self._unity_id('ALF')
        page = self.client.get(f'/admin/unities/{alfa_id}/edit').get_data(as_text=True)
        self.assertIn('Módulos da Unidade', page)
        self.assertIn(f'/admin/unities/{alfa_id}/modules/kitchen/toggle', page)
        self.assertIn(f'/admin/unities/{alfa_id}/modules/finance/toggle', page)
        self.assertIn('Reservas de Salas', page)   # core listado como sempre ativo
        # Checkboxes só existem na criação; na edição quem manda são os botões
        self.assertNotIn('kitchen_enabled', page)

    def test_super_admin_troca_modulo_de_qualquer_unidade(self):
        self._login(USERNAME)
        alfa_id = self._unity_id('ALF')
        response = self.client.post(f'/admin/unities/{alfa_id}/modules/finance/toggle',
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Módulo Financeiro desativado', response.get_data(as_text=True))
        with self.app.app_context():
            alfa = db.session.get(Unity, alfa_id)
            self.assertFalse(alfa.finance_enabled)
            self.assertFalse(alfa.kitchen_enabled)  # só o módulo alvo muda

        response = self.client.post(f'/admin/unities/{alfa_id}/modules/finance/toggle',
                                    follow_redirects=True)
        self.assertIn('Módulo Financeiro ativado', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertTrue(db.session.get(Unity, alfa_id).finance_enabled)

    def test_admin_vinculado_gerencia_apenas_a_propria_unidade(self):
        self._login('admin.alfa')
        alfa_id = self._unity_id('ALF')
        beta_id = self._unity_id('BET')
        # Própria unidade: permitido
        response = self.client.post(f'/admin/unities/{alfa_id}/modules/finance/toggle',
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('Módulo Financeiro desativado', response.get_data(as_text=True))
        with self.app.app_context():
            self.assertFalse(db.session.get(Unity, alfa_id).finance_enabled)
        # Outra unidade: bloqueado mesmo com a permissão unity:modules
        response = self.client.post(f'/admin/unities/{beta_id}/modules/kitchen/toggle')
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertTrue(db.session.get(Unity, beta_id).kitchen_enabled)

    def test_conta_global_sem_vinculo_nao_gerencia_modulos(self):
        """Permissão unity:modules sem vínculo com a unidade não basta:
        apenas o administrador da própria unidade ou o super-admin alterna."""
        self._login('admin.global')
        alfa_id = self._unity_id('ALF')
        response = self.client.post(f'/admin/unities/{alfa_id}/modules/kitchen/toggle')
        self.assertEqual(response.status_code, 403)

    def test_botoes_somente_na_unidade_vinculada(self):
        self._login('admin.alfa')
        alfa_id = self._unity_id('ALF')
        propria = self.client.get(f'/admin/unities/{alfa_id}/edit').get_data(as_text=True)
        self.assertIn(f'/admin/unities/{alfa_id}/modules/kitchen/toggle', propria)
        # Outra unidade nem carrega: está escondida do admin vinculado
        beta_id = self._unity_id('BET')
        self.assertEqual(self.client.get(f'/admin/unities/{beta_id}/edit').status_code, 404)

    def test_toggle_exige_permissao(self):
        self._login('leitor.teste')
        alfa_id = self._unity_id('ALF')
        self.assertEqual(
            self.client.post(f'/admin/unities/{alfa_id}/modules/kitchen/toggle').status_code,
            403)

    def test_toggle_de_modulo_inexistente_ou_core_da_404(self):
        self._login(USERNAME)
        alfa_id = self._unity_id('ALF')
        self.assertEqual(
            self.client.post(f'/admin/unities/{alfa_id}/modules/reservation/toggle').status_code,
            404)
        self.assertEqual(
            self.client.post(f'/admin/unities/{alfa_id}/modules/inexistente/toggle').status_code,
            404)

    def test_formulario_de_unidade_salva_modulos(self):
        self._login(USERNAME)
        response = self.client.post('/admin/unities/create', data={
            'name': 'Unidade Gama', 'code': 'GAM',
            'finance_enabled': 'y',  # kitchen_enabled ausente = desligado
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            gama = db.session.query(Unity).filter_by(code='GAM').first()
            self.assertIsNotNone(gama)
            self.assertFalse(gama.kitchen_enabled)
            self.assertTrue(gama.finance_enabled)

    def test_formulario_de_edicao_nao_altera_modulos(self):
        """O POST de edição não pode ligar/desligar módulos: quem manda são
        os botões da página, que exigem vínculo com a unidade. A Beta começa
        com Cozinha ativa e Financeiro desativado — o form não pode mudar
        nenhum dos dois."""
        self._login(USERNAME)
        beta_id = self._unity_id('BET')
        response = self.client.post(f'/admin/unities/{beta_id}/edit', data={
            'name': 'Unidade Beta', 'code': 'BET', 'is_active': 'y',
            # kitchen_enabled/finance_enabled ausentes = desligados no form
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            beta = db.session.get(Unity, beta_id)
            self.assertTrue(beta.kitchen_enabled)   # continuou ativa
            self.assertFalse(beta.finance_enabled)  # continuou desativado


class TestVisibilidadeDeUnidades(UnityModulesTestCase):
    """Na página de unidades, o administrador vinculado a uma unidade vê
    apenas a sua — as demais ficam escondidas, inclusive no acesso direto
    por URL (404). Super-admin e contas globais continuam vendo todas."""

    def test_admin_vinculado_ve_apenas_a_propria_unidade(self):
        self._login('admin.alfa')
        page = self.client.get('/admin/unities').get_data(as_text=True)
        self.assertIn('Unidade Alfa', page)
        self.assertNotIn('Unidade Beta', page)

    def test_super_admin_ve_todas_as_unidades(self):
        self._login(USERNAME)
        page = self.client.get('/admin/unities').get_data(as_text=True)
        self.assertIn('Unidade Alfa', page)
        self.assertIn('Unidade Beta', page)

    def test_conta_global_sem_vinculo_ve_todas_as_unidades(self):
        self._login('admin.global')
        page = self.client.get('/admin/unities').get_data(as_text=True)
        self.assertIn('Unidade Alfa', page)
        self.assertIn('Unidade Beta', page)

    def test_edicao_de_outra_unidade_fica_escondida(self):
        self._login('admin.alfa')
        beta_id = self._unity_id('BET')
        self.assertEqual(self.client.get(f'/admin/unities/{beta_id}/edit').status_code, 404)
        # A própria unidade continua acessível, com os botões de módulos
        alfa_id = self._unity_id('ALF')
        propria = self.client.get(f'/admin/unities/{alfa_id}/edit')
        self.assertEqual(propria.status_code, 200)
        self.assertIn(f'/admin/unities/{alfa_id}/modules/kitchen/toggle',
                      propria.get_data(as_text=True))

    def test_ativar_desativar_outra_unidade_fica_escondido(self):
        self._login('admin.alfa')
        beta_id = self._unity_id('BET')
        self.assertEqual(self.client.post(f'/admin/unities/{beta_id}/toggle').status_code, 404)


if __name__ == '__main__':
    unittest.main()
