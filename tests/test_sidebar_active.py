"""Testes do destaque (classe active) do menu lateral.

A aba correspondente à página visitada deve ficar sinalizada — ex.: Unidades
não pode deixar o destaque no Painel Admin.
"""
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Permission, Role, TeacherMealAllowance, Unity, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SidebarActiveTestCase(unittest.TestCase):
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

            codigos = ('unity:read', 'system:dashboard', 'user:read')
            perms = [Permission(code=c, module=c.split(':')[0], action=c.split(':')[1])
                     for c in codigos]
            db.session.add_all(perms)
            role = Role(name='gestor', label='Gestor', permissions=perms)
            db.session.add(role)
            db.session.flush()

            user = User(email=EMAIL, full_name='Gestor Teste', role='room',
                        profile_type='employee', unities=[self.unity],
                        role_id=role.id, force_password_change=False,
                        is_active_user=True)
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()
            self.unity_id = self.unity.id

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

    def _navlink(self, page, titulo):
        """Classe do link de navegação cujo title seja `titulo`.

        O Painel Admin vive na topbar (classe topbar-painel); os demais
        itens, na sidebar (classe nav-link).
        """
        import re
        m = re.search(r'<a class="(?:nav-link|topbar-painel) ([^"]*)" title="' + titulo + '"', page)
        return m.group(1) if m else None

    def test_unidades_vive_dentro_do_painel_admin(self):
        """Sem item próprio na sidebar, Unidades destaca o Painel Admin."""
        page = self.client.get('/admin/unities').get_data(as_text=True)
        self.assertIsNone(self._navlink(page, 'Unidades'))
        self.assertEqual(self._navlink(page, 'Painel Admin'), 'active')

    def test_painel_admin_ativo_na_pagina_de_usuarios(self):
        page = self.client.get('/admin/users').get_data(as_text=True)
        self.assertEqual(self._navlink(page, 'Painel Admin'), 'active')

    def test_painel_admin_ativo_no_dashboard(self):
        page = self.client.get('/admin/').get_data(as_text=True)
        self.assertEqual(self._navlink(page, 'Painel Admin'), 'active')
        # O dashboard é o hub: card de Unidades visível para quem tem unity:read.
        self.assertIn('Unidades', page)

    def test_dashboard_acessivel_sem_system_dashboard(self):
        """Quem só tem unity:read acessa o Painel Admin (hub) e vê o card
        de Unidades — mas nada de que não tenha permissão."""
        with self.app.app_context():
            user = User.query.filter_by(email=EMAIL).first()
            user.role_obj.permissions = [Permission.query.filter_by(code='unity:read').first()]
            db.session.commit()
        self.client.get('/logout')
        self.client.post('/login', data={'email': EMAIL, 'password': PASSWORD},
                         follow_redirects=True)
        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('Unidades', page)
        self.assertNotIn('Tokens da API', page)

    # --- Vale Alimentação (payments.*_meal_allowance) vs. Hora Extra ---

    FINANCEIRO = ('payment:read', 'payment:create', 'meal:read', 'meal:edit')

    def _conceder(self, codigos):
        """Substitui as permissões do papel do usuário de teste."""
        with self.app.app_context():
            user = User.query.filter_by(email=EMAIL).first()
            perms = []
            for codigo in codigos:
                perm = Permission.query.filter_by(code=codigo).first()
                if perm is None:
                    perm = Permission(code=codigo, module=codigo.split(':')[0],
                                      action=codigo.split(':')[1])
                    db.session.add(perm)
                perms.append(perm)
            user.role_obj.permissions = perms
            db.session.commit()

    def test_vale_alimentacao_destaca_financeiro_rh(self):
        """A página do Vale Alimentação destaca o item unificado
        Financeiro/RH (onde o módulo virou card). Os links internos
        (Consultar H. Extras) não moram mais na sidebar."""
        self._conceder(self.FINANCEIRO)
        page = self.client.get('/payments/meal-allowance').get_data(as_text=True)
        self.assertEqual(self._navlink(page, 'Financeiro/RH'), 'active')
        self.assertIsNone(self._navlink(page, 'Hora Extra'))
        self.assertIsNone(self._navlink(page, 'Consultar H. Extras'))

    def test_editar_vale_alimentacao_tambem_destaca(self):
        """Editar um lançamento do Vale Alimentação (payments.edit_meal_
        allowance começa com payments.edit) continua na seção."""
        self._conceder(self.FINANCEIRO)
        with self.app.app_context():
            professor = User(email='professor@escola.edu',
                             full_name='Professor Silva', role='room',
                             profile_type='teacher',
                             unities=[db.session.get(Unity, self.unity_id)],
                             force_password_change=False, is_active_user=True)
            professor.set_password(PASSWORD)
            db.session.add(professor)
            db.session.flush()
            entry = TeacherMealAllowance(teacher_id=professor.id, days=5,
                                         unity_id=self.unity_id)
            db.session.add(entry)
            db.session.commit()
            entry_id = entry.id

        page = self.client.get(f'/payments/meal-allowance/{entry_id}/edit') \
            .get_data(as_text=True)
        self.assertEqual(self._navlink(page, 'Financeiro/RH'), 'active')

    def test_hora_extra_continua_sendo_destacada(self):
        """Guarda contra correção exagerada: na consulta de Hora Extra o
        destaque continua no item Financeiro/RH (seção do módulo)."""
        self._conceder(self.FINANCEIRO)
        page = self.client.get('/payments/overtime/list').get_data(as_text=True)
        self.assertEqual(self._navlink(page, 'Financeiro/RH'), 'active')

    # --- Centrais de seção (hubs; modelo do Observatório) ---

    def test_hub_salas_reservas_renderiza(self):
        """A central da seção abre com três cards-portais (Salas, Reservas,
        Relatórios) e os blocos de conteúdos respectivos, revelados no
        cliente — os destinos respeitam a permissão."""
        self._conceder(('reservation:read_all',))
        page = self.client.get('/salas-e-reservas')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('Central de Salas e Reservas', html)
        # Cards-portais (3) com alvos data-hub-alvo e blocos correspondentes
        self.assertEqual(html.count('data-hub-alvo='), 3)
        self.assertIn('id="hub-reservas"', html)
        self.assertIn('id="hub-relatorios"', html)
        self.assertIn('/reservations/all', html)
        self.assertNotIn('/reservations/create', html)  # sem reservation:create
        self.assertIn('/relatorios/geral', html)

    def test_hub_financeiro_rh_renderiza_com_portais(self):
        """/financeiro-rh abre a central unificada: com payment:* e meal:read
        aparecem os portais de Hora Extra e Vale Alimentação (não os de VT,
        sem vt:read). Os shims antigos mandam para cá."""
        self._conceder(self.FINANCEIRO)
        for shim_url in ('/financeiro', '/rh', '/payments/overtime'):
            shim = self.client.get(shim_url, follow_redirects=False)
            self.assertEqual(shim.status_code, 302, shim_url)
            self.assertTrue(shim.location.endswith('/financeiro-rh'), shim_url)
        page = self.client.get('/financeiro-rh')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('Central de Financeiro/RH', html)
        self.assertEqual(html.count('data-hub-alvo='), 2)  # Hora Extra + VA
        self.assertIn('id="hub-hora-extra"', html)
        self.assertIn('/payments/overtime/create', html)
        self.assertIn('/payments/overtime/list', html)
        self.assertIn('/payments/meal-allowance', html)
        self.assertNotIn('/vt/pedidos', html)  # sem vt:read

    def test_hub_reservas_shim_redireciona_para_a_secao(self):
        """/reservations/ é compatibilidade: manda para a central da seção
        (Salas e Reservas), onde os cards do módulo vivem."""
        self._conceder(('reservation:read_all',))
        shim = self.client.get('/reservations/', follow_redirects=False)
        self.assertEqual(shim.status_code, 302)
        self.assertTrue(shim.location.endswith('/salas-e-reservas'))
        page = self.client.get('/salas-e-reservas')
        self.assertIn('Central de Salas e Reservas',
                      page.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
