"""Testes de regressão do controle de acesso por permissões.

Cobre a matriz papel × rota nas rotas representativas de cada módulo:
quem tem a permissão entra (200), quem não tem recebe 403 — e o papel
Administrador enxerga a tela de pedidos de VT (vt:read). Cobre ainda a
aposentadoria de permissões removidas do catálogo pelo sync e o bloqueio
por módulo desligado na unidade (@require_module).
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.commands import _seed_permissions, sync_permissions_impl
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Permission, Reservation, Role, RoomCategory,
                        Unity, User)

SENHA = 'SenhaForte123'

# Um usuário por papel padrão + um professor com o add-on Módulo Cozinha.
USUARIOS = {
    'super_admin': 'super@escola.edu',
    'admin': 'admin@escola.edu',
    'coordinator': 'analista@escola.edu',
    'room_manager': 'gestor@escola.edu',
    'teacher': 'prof@escola.edu',
    'employee': 'assistente@escola.edu',
    'teacher+kitchen': 'gastro@escola.edu',
}


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class PermissionsAccessTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            unity = Unity(name='Unidade Teste', code='UT')
            db.session.add(unity)
            db.session.commit()

            # Banco recém-criado: semeia permissões e papéis padrão.
            _seed_permissions()
            db.session.commit()

            kitchen_role = Role.query.filter_by(name='kitchen').first()
            for papel, email in USUARIOS.items():
                nome_papel = 'teacher' if papel == 'teacher+kitchen' else papel
                user = User(
                    email=email, full_name=f'Usuário {papel}',
                    role='room', profile_type='teacher', unities=[unity],
                    role_id=Role.query.filter_by(name=nome_papel).first().id,
                    force_password_change=False, is_active_user=True,
                )
                if papel == 'teacher+kitchen':
                    user.extra_roles.append(kitchen_role)
                user.set_password(SENHA)
                db.session.add(user)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _entrar_como(self, papel):
        self.client.get('/logout')
        response = self.client.post('/login',
                                    data={'email': USUARIOS[papel], 'password': SENHA},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _asserta(self, papel, rota, esperado):
        self._entrar_como(papel)
        response = self.client.get(rota)
        self.assertEqual(response.status_code, esperado,
                         f'{papel} em {rota}: esperado {esperado}, '
                         f'obtido {response.status_code}')

    # ---------- Matriz papel × rota ----------

    def test_super_admin_acessa_tudo(self):
        for rota in ('/admin/users', '/admin/unities', '/admin/roles',
                     '/payments/overtime/list', '/vt/pedidos', '/kitchen/fichas'):
            self._asserta('super_admin', rota, 200)

    def test_admin_gerencia_usuarios_e_ve_pedidos_vt(self):
        # vt:read no papel Administrador: quem configura o módulo (empresas
        # e pedido público) também abre a tela operacional dos pedidos.
        self._asserta('admin', '/admin/users', 200)
        self._asserta('admin', '/admin/vt-empresas', 200)
        self._asserta('admin', '/vt/pedidos', 200)

    def test_admin_nao_gerencia_hora_extra(self):
        # Hora Extra e Vale Alimentação são do Gestor: o Administrador
        # padrão não recebe payment:* nem meal:*.
        self._asserta('admin', '/payments/overtime/list', 403)
        self._asserta('admin', '/payments/meal-allowance', 403)

    def test_analista_aprova_reservas_e_lanca_hora_extra(self):
        self._asserta('coordinator', '/reservations/my', 200)
        self._asserta('coordinator', '/payments/overtime/create', 200)
        self._asserta('coordinator', '/payments/meal-allowance', 200)

    def test_analista_nao_ve_admin_nem_vt_nor_hora_extra_lista(self):
        self._asserta('coordinator', '/admin/users', 403)
        self._asserta('coordinator', '/vt/pedidos', 403)
        # Sem payment:read, o Analista não abre a listagem de hora extra.
        self._asserta('coordinator', '/payments/overtime/list', 403)

    def test_gestor_gerencia_reservas_e_hora_extra(self):
        self._asserta('room_manager', '/payments/overtime/list', 200)
        self._asserta('room_manager', '/payments/meal-allowance', 200)
        self._asserta('room_manager', '/reservations/all', 200)

    def test_gestor_nao_gerencia_papeis_nem_usuarios(self):
        self._asserta('room_manager', '/admin/roles', 403)
        self._asserta('room_manager', '/admin/users', 403)

    def test_professor_e_assistente_somente_reservas(self):
        for papel in ('teacher', 'employee'):
            self._asserta(papel, '/reservations/my', 200)
            self._asserta(papel, '/admin/users', 403)
            self._asserta(papel, '/payments/overtime/list', 403)
            self._asserta(papel, '/kitchen/fichas', 403)

    def test_papel_adicional_cozinha(self):
        # Professor + Módulo Cozinha entra na cozinha; professor sem o
        # add-on não.
        self._asserta('teacher+kitchen', '/kitchen/fichas', 200)
        self._asserta('teacher', '/kitchen/fichas', 403)

    def test_anonimo_vai_para_login(self):
        self.client.get('/logout')
        response = self.client.get('/admin/users')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    # ---------- @require_module: módulo desligado na unidade ----------

    def test_financeiro_desligado_bloqueia_hora_extra(self):
        with self.app.app_context():
            unity = Unity.query.first()
            unity.finance_enabled = False
            db.session.commit()
        self._asserta('coordinator', '/payments/overtime/create', 403)
        self._asserta('room_manager', '/payments/overtime/list', 403)

    def test_cozinha_desligada_bloqueia_fichas(self):
        with self.app.app_context():
            unity = Unity.query.first()
            unity.kitchen_enabled = False
            db.session.commit()
        self._asserta('teacher+kitchen', '/kitchen/fichas', 403)

    # ---------- Escopo da aprovação (reservation:approve) ----------

    def _criar_pendencia(self, email_criador, email_docente):
        """Cria sala e reserva pendente direto no banco; devolve o id."""
        with self.app.app_context():
            criador = User.query.filter_by(email=email_criador).first()
            docente = User.query.filter_by(email=email_docente).first()
            # Códigos com sufixo: category/room têm code único no banco e o
            # teste cria mais de uma reserva.
            sufixo = RoomCategory.query.count() + 1
            category = RoomCategory(name=f'Categoria Aprovação {sufixo}',
                                    code=f'CA{sufixo}')
            db.session.add(category)
            db.session.flush()
            room = Classroom(name=f'Sala Aprovação {sufixo}', code=f'SAP{sufixo}',
                             capacity=10, unity_id=Unity.query.first().id,
                             category_id=category.id)
            db.session.add(room)
            db.session.flush()
            reserva = Reservation(
                user_id=criador.id, classroom_id=room.id, teacher_id=docente.id,
                unity_id=room.unity_id, title='Pendência de Teste',
                date=date.today() + timedelta(days=1),
                start_time=time(9, 0), end_time=time(10, 0), status='pending')
            db.session.add(reserva)
            db.session.commit()
            return reserva.id

    def test_analista_nao_aprova_pendencia_de_terceiro(self):
        """A rota de aprovação reforça o mesmo escopo do detalhe: sem
        reservation:read_all, o Analista só aprova com vínculo (criador ou
        professor designado) — POST direto em pendência de terceiro recebe
        403 e a reserva segue pendente."""
        reserva_id = self._criar_pendencia('prof@escola.edu', 'prof@escola.edu')
        self._entrar_como('coordinator')
        response = self.client.post(f'/reservations/{reserva_id}/approve')
        self.assertEqual(response.status_code, 403)
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, reserva_id).status,
                             'pending')

    def test_gestor_aprova_pendencia_de_terceiro(self):
        """Com reservation:read_all, o Gestor aprova qualquer pendência."""
        reserva_id = self._criar_pendencia('prof@escola.edu', 'prof@escola.edu')
        self._entrar_como('room_manager')
        response = self.client.post(f'/reservations/{reserva_id}/approve',
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, reserva_id).status,
                             'approved')

    def test_analista_aprova_pendencia_com_vinculo(self):
        """O vínculo dá o acesso: pendência criada pelo próprio Analista —
        ou em que ele é o docente designado — pode ser aprovada por ele."""
        propria_id = self._criar_pendencia('analista@escola.edu',
                                           'prof@escola.edu')
        designada_id = self._criar_pendencia('prof@escola.edu',
                                             'analista@escola.edu')
        self._entrar_como('coordinator')
        for reserva_id in (propria_id, designada_id):
            response = self.client.post(f'/reservations/{reserva_id}/approve',
                                        follow_redirects=True)
            self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, propria_id).status,
                             'approved')
            self.assertEqual(db.session.get(Reservation, designada_id).status,
                             'approved')

    # ---------- Aposentadoria de permissões pelo sync ----------

    def test_catalogo_nao_tem_permissoes_aposentadas(self):
        aposentadas = ('payment:read_own', 'reservation:edit_own')
        with self.app.app_context():
            for code in aposentadas:
                self.assertIsNone(Permission.query.filter_by(code=code).first(),
                                  f'{code} deveria ter sido aposentada pelo sync')
                self.assertNotIn(code, _permissoes_de_todos_os_papeis(),
                                 f'{code} não deveria estar em nenhum papel')

    def test_sync_aposenta_permissao_de_banco_antigo(self):
        """Banco criado antes da aposentadoria: a permissão órfã e seus
        vínculos com papéis somem ao rodar o sync."""
        with self.app.app_context():
            fantasma = Permission(code='payment:read_own', module='payment',
                                  action='read_own', description='Legado')
            coordinator = Role.query.filter_by(name='coordinator').first()
            coordinator.permissions.append(fantasma)
            db.session.commit()
            self.assertIsNotNone(
                Permission.query.filter_by(code='payment:read_own').first())

            sync_permissions_impl(verbose=False)

            self.assertIsNone(
                Permission.query.filter_by(code='payment:read_own').first())
            self.assertEqual(
                [p.code for p in coordinator.permissions
                 if p.code == 'payment:read_own'], [])


def _permissoes_de_todos_os_papeis():
    """União das permissões de todos os papéis padrão (helper do teste)."""
    from app.commands import ROLES_CONFIG
    uniao = set()
    for config in ROLES_CONFIG.values():
        uniao.update(config['permissions'])
    return uniao


if __name__ == '__main__':
    unittest.main()
