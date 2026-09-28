"""Testes do módulo de notificações de atividades próximas.

Cobre:
- o serviço de varredura: marcos de antecedência, idempotência, destinatários
  (professor, criador, aprovadores e grupos personalizados), status e unidade;
- o comando `flask notify-scan` (inclusive --dry-run);
- o painel admin: configuração por unidade e CRUD de grupos com escopo;
- o centro de notificações do usuário: listagem, sino (badge), marcar lida.
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Notification, NotificationGroup, Permission,
                        Role, RoomCategory, Unity, UnityNotificationConfig, User)
from app.services.notifications import parse_lead_days, varrer_reservas

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class NotificationsTestCase(unittest.TestCase):
    """Base: app + unidade com sala, admin (gestor), professor, criador e um
    funcionário extra; configuração de notificação ativa com marcos 7,1,0."""

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

            perms = [Permission(code=c, module=c.split(':')[0], action=c.split(':')[1])
                     for c in ('notification:manage', 'notification:groups',
                               'reservation:approve', 'reservation:create')]
            db.session.add_all(perms)
            role_gestor = Role(name='gestor', label='Gestor', permissions=perms)
            db.session.add(role_gestor)
            db.session.flush()

            self.gestor = User(email=EMAIL, full_name='Gestor Teste', role='room',
                               profile_type='employee', unities=[self.unity],
                               role_id=role_gestor.id,
                               force_password_change=False, is_active_user=True)
            self.gestor.set_password(PASSWORD)
            self.professor = User(email='prof@escola.edu', full_name='Paulo Professor',
                                  role='room', profile_type='teacher', is_teacher=True,
                                  unities=[self.unity],
                                  force_password_change=False, is_active_user=True)
            self.professor.set_password(PASSWORD)
            self.criador = User(email='criador@escola.edu', full_name='Carla Criadora',
                                role='room', profile_type='employee', unities=[self.unity],
                                force_password_change=False, is_active_user=True)
            self.criador.set_password(PASSWORD)
            self.extra = User(email='extra@escola.edu', full_name='Eva Extra',
                              role='viewer', profile_type='employee', unities=[self.unity],
                              force_password_change=False, is_active_user=True)
            self.extra.set_password(PASSWORD)
            db.session.add_all([self.gestor, self.professor, self.criador, self.extra])
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='sala_aula', abbr='SA')
            db.session.add(category)
            db.session.flush()
            self.sala = Classroom(name='Sala 1', code='S1', capacity=30,
                                  unity_id=self.unity.id, category_id=category.id)
            db.session.add(self.sala)
            db.session.flush()

            self.config = UnityNotificationConfig(unity_id=self.unity.id,
                                                  lead_days='7,1,0')
            db.session.add(self.config)
            db.session.commit()

            self.ids = {'professor': self.professor.id, 'criador': self.criador.id,
                        'extra': self.extra.id, 'gestor': self.gestor.id,
                        'sala': self.sala.id, 'unity': self.unity.id,
                        'config': self.config.id}

        self._login()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email=EMAIL, password=PASSWORD):
        # /login redireciona quem já está autenticado: deslogar antes de trocar
        self.client.get('/logout')
        response = self.client.post('/login', data={'email': email, 'password': password},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _criar_reserva(self, *, em_dias=5, status='approved', titulo='Aula de Teste'):
        """Reserva aprovada padrão: criador = Carla, professor = Paulo."""
        def gravar():
            from app.models import Reservation
            with self.app.app_context():
                reservation = Reservation(
                    user_id=self.ids['criador'],
                    classroom_id=self.ids['sala'],
                    teacher_id=self.ids['professor'],
                    unity_id=self.ids['unity'],
                    title=titulo,
                    date=date.today() + timedelta(days=em_dias),
                    start_time=time(9, 0), end_time=time(11, 0),
                    status=status,
                )
                db.session.add(reservation)
                db.session.commit()
                return reservation.id
        return gravar()

    def _contar(self, **filtros):
        with self.app.app_context():
            return Notification.query.filter_by(**filtros).count()

    def _destinatarios(self):
        with self.app.app_context():
            return sorted(n.user_id for n in Notification.query.all())


class TestParseLeadDays(unittest.TestCase):
    def test_normaliza_e_ordena(self):
        self.assertEqual(parse_lead_days('1,7,0,7'), [7, 1, 0])
        self.assertEqual(parse_lead_days(' 3 , 14 '), [14, 3])

    def test_ignora_lixo(self):
        self.assertEqual(parse_lead_days('7,abc,,1'), [7, 1])
        self.assertEqual(parse_lead_days(''), [])
        self.assertEqual(parse_lead_days(None), [])

    def test_aceita_zero_e_recusa_negativo(self):
        self.assertEqual(parse_lead_days('0'), [0])
        self.assertEqual(parse_lead_days('-3,5'), [5])


class TestVarredura(NotificationsTestCase):
    def test_cria_para_professor_e_criador_no_marco(self):
        # Reserva em 5 dias, marcos 7,1,0: só o marco de 7 dias está vencido.
        self._criar_reserva()
        with self.app.app_context():
            stats = varrer_reservas()
        self.assertEqual(stats['criadas'], 2)          # professor + criador
        self.assertEqual(stats['existentes'], 0)
        self.assertEqual(self._contar(milestone='7d'), 2)
        self.assertEqual(self._contar(milestone='1d'), 0)
        self.assertEqual(self._contar(milestone='0d'), 0)
        self.assertEqual(self._destinatarios(),
                         sorted([self.ids['professor'], self.ids['criador']]))

    def test_idempotente_nao_duplica(self):
        self._criar_reserva()
        with self.app.app_context():
            varrer_reservas()
            stats = varrer_reservas()
        self.assertEqual(stats['criadas'], 0)
        self.assertEqual(stats['existentes'], 2)
        self.assertEqual(self._contar(), 2)

    def test_janela_atrasada_dispara_marcos_vencidos_de_uma_vez(self):
        # Reserva amanhã: marcos de 7 e 1 dia já venceram; o do dia, não.
        self._criar_reserva(em_dias=1)
        with self.app.app_context():
            varrer_reservas()
        self.assertEqual(self._contar(milestone='7d'), 2)
        self.assertEqual(self._contar(milestone='1d'), 2)
        self.assertEqual(self._contar(milestone='0d'), 0)

    def test_reserva_no_dia_avisa_hoje(self):
        self._criar_reserva(em_dias=0)
        with self.app.app_context():
            varrer_reservas()
        self.assertEqual(self._contar(milestone='0d'), 2)
        with self.app.app_context():
            titulo = Notification.query.first().title
            self.assertTrue(titulo.startswith('Hoje:'))

    def test_reserva_cancelada_ou_pendente_nao_avisam(self):
        self._criar_reserva(status='cancelled')
        self._criar_reserva(status='pending', titulo='Outra aula')
        with self.app.app_context():
            stats = varrer_reservas()
        self.assertEqual(stats['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_config_desativada_nao_avisa(self):
        self._criar_reserva()
        with self.app.app_context():
            UnityNotificationConfig.query.update({'is_enabled': False})
            db.session.commit()
        with self.app.app_context():
            self.assertEqual(varrer_reservas()['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_grupo_personalizado_recebe_e_sem_duplicar(self):
        self._criar_reserva()
        with self.app.app_context():
            grupo = NotificationGroup(name='Equipe Apoio', unity_id=self.ids['unity'])
            grupo.members = [db.session.get(User, self.ids['extra']),
                             db.session.get(User, self.ids['professor'])]  # professor também está no grupo
            db.session.add(grupo)
            config = db.session.get(UnityNotificationConfig, self.ids['config'])
            config.groups = [grupo]
            db.session.commit()
            varrer_reservas()
        # extra entra pelo grupo; professor recebe UMA notificação (grupo + fixo)
        self.assertEqual(self._contar(user_id=self.ids['extra'], milestone='7d'), 1)
        self.assertEqual(self._contar(user_id=self.ids['professor'], milestone='7d'), 1)
        self.assertEqual(self._contar(), 3)

    def test_aprovadores_recebem_quando_ligado(self):
        self._criar_reserva()
        with self.app.app_context():
            config = db.session.get(UnityNotificationConfig, self.ids['config'])
            config.notify_approvers = True
            db.session.commit()
            varrer_reservas()
        # gestor tem reservation:approve e está no escopo da unidade
        self.assertEqual(self._contar(user_id=self.ids['gestor']), 1)

    def test_professor_inativo_nao_recebe(self):
        self._criar_reserva()
        with self.app.app_context():
            User.query.filter_by(id=self.ids['professor']).update({'is_active_user': False})
            db.session.commit()
            varrer_reservas()
        self.assertEqual(self._destinatarios(), [self.ids['criador']])


class TestComandoNotifyScan(NotificationsTestCase):
    def test_comando_cria_e_dry_run_nao_grava(self):
        self._criar_reserva()
        resultado = self.app.test_cli_runner().invoke(args=['notify-scan', '--dry-run'])
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('seriam criadas: 2', resultado.output)
        self.assertEqual(self._contar(), 0)

        resultado = self.app.test_cli_runner().invoke(args=['notify-scan'])
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('criadas: 2', resultado.output)
        self.assertEqual(self._contar(), 2)

        # Segunda execução: nada novo (idempotente)
        resultado = self.app.test_cli_runner().invoke(args=['notify-scan'])
        self.assertIn('criadas: 0', resultado.output)
        self.assertEqual(self._contar(), 2)


class TestPainelAdmin(NotificationsTestCase):
    def test_config_salva_destinatarios_e_marcos(self):
        resposta = self.client.post('/admin/notificacoes/configuracao', data={
            'is_enabled': 'on',
            'lead_days': '3,1',
            'notify_teacher': 'on',
            # criador e aprovadores desmarcados (checkbox ausente = False)
        }, follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('salvas', resposta.get_data(as_text=True))
        with self.app.app_context():
            config = db.session.get(UnityNotificationConfig, self.ids['config'])
            self.assertEqual(config.lead_days, '3,1')
            self.assertTrue(config.notify_teacher)
            self.assertFalse(config.notify_creator)
            self.assertFalse(config.notify_approvers)

    def test_config_rejeita_marcos_invalidos(self):
        resposta = self.client.post('/admin/notificacoes/configuracao', data={
            'is_enabled': 'on', 'lead_days': 'abc,',
        }, follow_redirects=True)
        self.assertIn(b'ao menos uma anteced', resposta.data)
        with self.app.app_context():
            config = db.session.get(UnityNotificationConfig, self.ids['config'])
            self.assertEqual(config.lead_days, '7,1,0')  # intacto

    def test_config_exige_permissao(self):
        with self.app.app_context():
            User.query.filter_by(id=self.ids['gestor']).update({'role_id': None})
            db.session.commit()
        resposta = self.client.get('/admin/notificacoes/configuracao')
        self.assertEqual(resposta.status_code, 403)

    def test_grupo_criar_editar_excluir(self):
        resposta = self.client.post('/admin/notificacoes/grupos/nova', data={
            'name': 'Equipe Apoio',
            'members': [str(self.ids['extra']), str(self.ids['professor'])],
        }, follow_redirects=True)
        self.assertIn('criado', resposta.get_data(as_text=True))

        with self.app.app_context():
            grupo = NotificationGroup.query.filter_by(name='Equipe Apoio').first()
            self.assertIsNotNone(grupo)
            self.assertEqual(sorted(m.id for m in grupo.members),
                             sorted([self.ids['extra'], self.ids['professor']]))
            grupo_id = grupo.id

        # Nome duplicado é recusado
        resposta = self.client.post('/admin/notificacoes/grupos/nova', data={
            'name': 'Equipe Apoio', 'members': [str(self.ids['extra'])],
        }, follow_redirects=True)
        self.assertIn('Já existe um grupo', resposta.get_data(as_text=True))

        # Edita: troca nome e membros
        resposta = self.client.post(f'/admin/notificacoes/grupos/{grupo_id}/editar', data={
            'name': 'Equipe Renomeada', 'members': [str(self.ids['extra'])],
        }, follow_redirects=True)
        self.assertIn('atualizado', resposta.get_data(as_text=True))
        with self.app.app_context():
            grupo = db.session.get(NotificationGroup, grupo_id)
            self.assertEqual(grupo.name, 'Equipe Renomeada')
            self.assertEqual([m.id for m in grupo.members], [self.ids['extra']])

        # Exclui
        resposta = self.client.post(f'/admin/notificacoes/grupos/{grupo_id}/excluir',
                                    follow_redirects=True)
        self.assertIn('exclu', resposta.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(db.session.get(NotificationGroup, grupo_id))


class TestCentroNotificacoes(NotificationsTestCase):
    def _notificar(self, user_id, titulo='Amanhã: Aula de Teste'):
        def gravar():
            with self.app.app_context():
                notificacao = Notification(user_id=user_id, milestone='1d',
                                           title=titulo, body='S1 · 01/10/2026 · 09:00–11:00',
                                           url='/calendar/?initialDate=2026-10-01')
                db.session.add(notificacao)
                db.session.commit()
                return notificacao.id
        return gravar()

    def test_listagem_mostra_notificacao(self):
        notificacao_id = self._notificar(self.ids['criador'])
        self._login('criador@escola.edu')
        resposta = self.client.get('/notificacoes/')
        self.assertEqual(resposta.status_code, 200)
        html = resposta.get_data(as_text=True)
        self.assertIn('Amanh', html)
        self.assertIn('/calendar/?initialDate=2026-10-01', html)
        # não vê notificação de outro usuário
        self.assertNotIn('Outra pessoa', html)

    def test_sino_mostra_badge_com_nao_lidas(self):
        self._notificar(self.ids['criador'])
        self._login('criador@escola.edu')
        resposta = self.client.get('/dashboard')
        html = resposta.get_data(as_text=True)
        self.assertIn('notif-badge', html)
        # O badge renderiza a contagem (Jinja insere quebras ao redor do número)
        self.assertRegex(html, r'notif-badge[\s\S]*?>\s*1\s*<')

    def test_marcar_lida_e_poll(self):
        notificacao_id = self._notificar(self.ids['criador'])
        self._login('criador@escola.edu')
        resposta = self.client.get('/notificacoes/api/nao-lidas')
        self.assertEqual(resposta.get_json()['count'], 1)

        resposta = self.client.post(f'/notificacoes/{notificacao_id}/lida',
                                    follow_redirects=False)
        self.assertEqual(resposta.status_code, 302)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Notification, notificacao_id).read_at)
        resposta = self.client.get('/notificacoes/api/nao-lidas')
        self.assertEqual(resposta.get_json()['count'], 0)

    def test_marcar_todas(self):
        self._notificar(self.ids['criador'])
        self._notificar(self.ids['criador'], titulo='Hoje: Outra aula')
        self._login('criador@escola.edu')
        resposta = self.client.post('/notificacoes/marcar-todas', follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.client.get('/notificacoes/api/nao-lidas').get_json()['count'], 0)

    def test_notificacao_de_outro_usuario_vira_404(self):
        notificacao_id = self._notificar(self.ids['extra'])
        self._login('criador@escola.edu')
        resposta = self.client.post(f'/notificacoes/{notificacao_id}/lida')
        self.assertEqual(resposta.status_code, 404)

    def test_requer_login(self):
        self.client.get('/logout')
        resposta = self.client.get('/notificacoes/')
        self.assertEqual(resposta.status_code, 302)  # redireciona para login


if __name__ == '__main__':
    unittest.main()
