"""Testes do módulo de notificações de atividades próximas.

Cobre:
- a configuração por reserva: interruptor (padrão desativado) no formulário de
  criar/editar, marcos de aviso (24h/1h antes do início e "no dia") e
  destinatários explícitos (usuários individuais e grupos personalizados);
- o serviço de varredura: marcos por horas e ancorado no dia, janela aberta
  (o mais iminente vencido dispara), idempotência, status, atividade já
  iniciada e reservas sem configuração;
- os avisos de mudança de status: aprovação/cancelamento avisam o criador
  (ação do próprio criador e reaprovação não duplicam), inclusive na
  exclusão de série;
- o espelho por e-mail: dreno da fila pelo sent_at, opt-out no perfil,
  falha de SMTP e no-op sem SMTP configurado, comando `flask notify-email`;
- as preferências do usuário no perfil: silenciar tudo ou por tipo de sala;
- o comando `flask notify-scan` (inclusive --dry-run);
- o painel admin: aviso de sobrecarga de professor (única configuração de
  unidade que resta) e CRUD de grupos com escopo;
- o centro de notificações do usuário: listagem, sino (badge e dropdown
  /api/recentes), marcar lida, limpar as lidas.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Notification, NotificationGroup,
                        Permission, Reservation, ReservationNotificationConfig,
                        Role, RoomCategory, Unity, UnityNotificationConfig,
                        User, UserNotificationPref)
from app.services.mailer import drenar_fila_email
from app.services.notifications import varrer_pendentes, varrer_reservas

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


def _data_futura(em_dias):
    """Data futura aceita pelas rotas de reserva: avança enquanto cair em
    domingo, dia que check_schedule_restrictions recusa — sem isso os testes
    que enviam formulário falham quando hoje + em_dias é domingo (toda
    terça-feira, no padrão em_dias=5)."""
    data = date.today() + timedelta(days=em_dias)
    while data.weekday() == 6:
        data += timedelta(days=1)
    return data


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class NotificationsTestCase(unittest.TestCase):
    """Base: app + unidade com sala, admin (gestor), professor, criador e um
    funcionário extra; grupos e curso para o formulário de reserva."""

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
                               'reservation:approve', 'reservation:create',
                               'reservation:read_own', 'reservation:cancel_all',
                               'reservation:read_all', 'reservation:delete_all')]
            db.session.add_all(perms)
            role_gestor = Role(name='gestor', label='Gestor', permissions=perms)
            db.session.add(role_gestor)
            # Quem cria reservas no formulário precisa de reservation:create
            # (e read_own para ver os detalhes das próprias).
            perms_criador = [p for p in perms
                             if p.code in ('reservation:create', 'reservation:read_own')]
            role_criador = Role(name='solicitante', label='Solicitante',
                                permissions=perms_criador)
            db.session.add(role_criador)
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
                                role_id=role_criador.id,
                                force_password_change=False, is_active_user=True)
            self.criador.set_password(PASSWORD)
            self.extra = User(email='extra@escola.edu', full_name='Eva Extra',
                              role='viewer', profile_type='employee', unities=[self.unity],
                              force_password_change=False, is_active_user=True)
            self.extra.set_password(PASSWORD)
            db.session.add_all([self.gestor, self.professor, self.criador, self.extra])
            db.session.flush()

            self.category = RoomCategory(name='Sala de Aula', code='sala_aula', abbr='SA')
            self.lab = RoomCategory(name='Laboratório', code='lab', abbr='LB')
            db.session.add_all([self.category, self.lab])
            db.session.flush()
            self.sala = Classroom(name='Sala 1', code='S1', capacity=30,
                                  unity_id=self.unity.id, category_id=self.category.id)
            db.session.add(self.sala)
            db.session.flush()

            self.curso = Course(name='Curso Teste', code='CT',
                                unity_id=self.unity.id, is_active=True)
            db.session.add(self.curso)
            db.session.commit()

            self.ids = {'professor': self.professor.id, 'criador': self.criador.id,
                        'extra': self.extra.id, 'gestor': self.gestor.id,
                        'sala': self.sala.id, 'unity': self.unity.id,
                        'curso': self.curso.id, 'categoria': self.category.id,
                        'lab': self.lab.id}

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

    def _criar_reserva(self, *, em_dias=5, hora=9, status='approved',
                       titulo='Aula de Teste', notificar=True, notify_7d=False,
                       notify_24h=True, notify_1h=False, notify_dia=False,
                       notify_criador=False,
                       usuarios=('professor', 'criador'),
                       grupos=(), dono_id=None):
        """Reserva aprovada padrão: criador = Carla, professor = Paulo.

        notificar=True já ativa as notificações da reserva (opt-in) e grava a
        configuração com os destinatários informados — os testes da varredura
        exercitam o caminho com avisos ligados; os testes do opt-in criam com
        notificar=False para começar do padrão (interruptor desligado)."""
        dono_id = dono_id or self.ids['criador']

        def gravar():
            with self.app.app_context():
                reservation = Reservation(
                    user_id=dono_id,
                    classroom_id=self.ids['sala'],
                    teacher_id=self.ids['professor'],
                    unity_id=self.ids['unity'],
                    title=titulo,
                    date=date.today() + timedelta(days=em_dias),
                    start_time=time(hora, 0),
                    end_time=time(hora + 2, 0) if hora <= 21 else time(23, 59),
                    status=status,
                    notify_enabled=notificar,
                )
                db.session.add(reservation)
                if notificar:
                    config = ReservationNotificationConfig(
                        notify_7d=notify_7d, notify_24h=notify_24h,
                        notify_1h=notify_1h, notify_dia=notify_dia,
                        notify_criador=notify_criador)
                    db.session.add(config)
                    config.reservation = reservation
                    if usuarios:
                        config.users = [db.session.get(User, self.ids[u])
                                        for u in usuarios]
                    if grupos:
                        config.groups = [db.session.get(NotificationGroup, g)
                                         for g in grupos]
                db.session.commit()
                return reservation.id
        return gravar()

    def _grupo(self, nome='Equipe Apoio', members=('extra',)):
        def gravar():
            with self.app.app_context():
                grupo = NotificationGroup(name=nome, unity_id=self.ids['unity'])
                grupo.members = [db.session.get(User, self.ids[m]) for m in members]
                db.session.add(grupo)
                db.session.commit()
                return grupo.id
        return gravar()

    def _silenciar(self, user_id, mute_all=False, categorias=()):
        def gravar():
            with self.app.app_context():
                pref = UserNotificationPref(user_id=user_id, mute_all=mute_all)
                if categorias:
                    pref.muted_categories = [db.session.get(RoomCategory, c)
                                             for c in categorias]
                db.session.add(pref)
                db.session.commit()
        return gravar

    def _contar(self, **filtros):
        with self.app.app_context():
            return Notification.query.filter_by(**filtros).count()

    def _destinatarios(self):
        with self.app.app_context():
            return sorted(n.user_id for n in Notification.query.all())

    def _notificar(self, user_id, titulo='Em 24 horas: Aula de Teste'):
        """Notificação crua na fila (como a varredura/sobrecarga gravariam)."""
        def gravar():
            with self.app.app_context():
                notificacao = Notification(user_id=user_id, milestone='24h',
                                           title=titulo, body='S1 · 01/10/2026 · 09:00–11:00',
                                           url='/calendar/?initialDate=2026-10-01')
                db.session.add(notificacao)
                db.session.commit()
                return notificacao.id
        return gravar()


class TestVarredura(NotificationsTestCase):
    """A varredura dispara o marco mais iminente já vencido (24h ou 1h antes
    do início) para os destinatários configurados na própria reserva."""

    def test_cria_no_marco_de_24h(self):
        # Reserva em 2 dias às 9h; "agora" é 23h antes do início: o marco de
        # 24h está vencido e o de 1h ainda não.
        self._criar_reserva(em_dias=2)
        agora = datetime.combine(date.today() + timedelta(days=1), time(10, 0))
        with self.app.app_context():
            stats = varrer_reservas(agora=agora)
        self.assertEqual(stats['criadas'], 2)          # professor + criador
        self.assertEqual(stats['existentes'], 0)
        self.assertEqual(self._contar(milestone='24h'), 2)
        self.assertEqual(self._contar(milestone='1h'), 0)
        self.assertEqual(self._destinatarios(),
                         sorted([self.ids['professor'], self.ids['criador']]))
        with self.app.app_context():
            titulo = Notification.query.first().title
        self.assertTrue(titulo.startswith('Em 24 horas:'))

    def test_marco_1h_mais_iminente_quando_ambos_vencidos(self):
        # Reserva amanhã às 9h; "agora" é 8h30 do mesmo dia: 24h e 1h estão
        # vencidos, mas dispara só o mais iminente (1h) — o de 24h saiu antes
        # e dispará-lo de novo seria aviso redundante.
        self._criar_reserva(em_dias=1, notify_1h=True)
        agora = datetime.combine(date.today() + timedelta(days=1), time(8, 30))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._contar(milestone='24h'), 0)
        self.assertEqual(self._contar(milestone='1h'), 2)
        with self.app.app_context():
            titulo = Notification.query.first().title
        self.assertTrue(titulo.startswith('Em 1 hora:'))

    def test_idempotente_nao_duplica(self):
        self._criar_reserva(em_dias=2)
        agora = datetime.combine(date.today() + timedelta(days=1), time(10, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
            stats = varrer_reservas(agora=agora)
        self.assertEqual(stats['criadas'], 0)
        self.assertEqual(stats['existentes'], 2)
        self.assertEqual(self._contar(), 2)

    def test_reserva_ja_iniciada_nao_avisa(self):
        self._criar_reserva(em_dias=0, hora=8)
        agora = datetime.combine(date.today(), time(9, 30))
        with self.app.app_context():
            self.assertEqual(varrer_reservas(agora=agora)['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_sem_configuracao_nao_avisa(self):
        # Interruptor ligado sem configuração salva (reserva antiga herdada
        # da migração, por exemplo): nada a disparar até alguém configurar.
        reservation_id = self._criar_reserva()
        with self.app.app_context():
            reservation = db.session.get(Reservation, reservation_id)
            db.session.delete(reservation.notification_config)
            db.session.commit()
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            self.assertEqual(varrer_reservas(agora=agora)['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_marcos_desmarcados_nao_avisa(self):
        self._criar_reserva(notificar=True, notify_24h=False, notify_1h=False)
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            self.assertEqual(varrer_reservas(agora=agora)['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_reserva_cancelada_ou_pendente_nao_avisam(self):
        self._criar_reserva(status='cancelled')
        self._criar_reserva(status='pending', titulo='Outra aula')
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            stats = varrer_reservas(agora=agora)
        self.assertEqual(stats['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_grupo_e_usuario_individual_deduplicados(self):
        grupo_id = self._grupo('Equipe Apoio', members=('extra', 'professor'))
        # extra entra como usuário individual E pelo grupo; professor só pelo
        # grupo — cada um recebe UMA notificação.
        self._criar_reserva(usuarios=('extra',), grupos=[grupo_id])
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._contar(user_id=self.ids['extra'], milestone='24h'), 1)
        self.assertEqual(self._contar(user_id=self.ids['professor'], milestone='24h'), 1)
        self.assertEqual(self._contar(), 2)

    def test_usuario_inativo_nao_recebe(self):
        self._criar_reserva(usuarios=('extra',))
        with self.app.app_context():
            User.query.filter_by(id=self.ids['extra']).update({'is_active_user': False})
            db.session.commit()
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._contar(), 0)

    def test_silenciado_total_nao_recebe(self):
        # Preferência no perfil: desativar todas — o usuário some dos avisos.
        self._criar_reserva(usuarios=('extra', 'criador'))
        self._silenciar(self.ids['extra'], mute_all=True)()
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._destinatarios(), [self.ids['criador']])

    def test_silenciado_por_tipo_de_sala(self):
        # Silencia apenas o tipo "Sala de Aula" (categoria da sala da reserva):
        # não recebe este aviso; quem silenciou outro tipo continua recebendo.
        self._criar_reserva(usuarios=('extra', 'criador'))
        self._silenciar(self.ids['extra'], categorias=[self.ids['categoria']])()
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._destinatarios(), [self.ids['criador']])


class TestNotificacoesPorReserva(NotificationsTestCase):
    """Opt-in por reserva no formulário: padrão desativado; criar/editar
    gravam a configuração (marcos + destinatários) e o detalhe mostra o estado."""

    def _dados_reserva(self, em_dias=5, **extra):
        dados = {
            'classroom': self.ids['sala'],
            'course': self.ids['curso'],
            'subject': 0,
            'teacher': self.ids['professor'],
            'title': 'Aula via Formulário',
            'description': '',
            'date': _data_futura(em_dias).isoformat(),
            'start_time': '09:00',
            'end_time': '11:00',
        }
        dados.update(extra)
        return dados

    def test_padrao_desativado_e_varredura_ignora(self):
        self._login('criador@escola.edu')
        resposta = self.client.post('/reservations/create',
                                    data=self._dados_reserva(),
                                    follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        with self.app.app_context():
            reservation = Reservation.query.first()
            self.assertFalse(reservation.notify_enabled)
            self.assertIsNone(reservation.notification_config)
            stats = varrer_reservas()
        self.assertEqual(stats['reservas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_criar_com_notificacoes_ativadas(self):
        self._login('criador@escola.edu')
        resposta = self.client.post('/reservations/create', data=self._dados_reserva(
            notify_enabled='on', notify_24h='on',
            notify_users=[str(self.ids['extra'])],
        ), follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('agendada com sucesso', resposta.get_data(as_text=True))
        with self.app.app_context():
            reservation = Reservation.query.first()
            self.assertTrue(reservation.notify_enabled)
            config = reservation.notification_config
            self.assertIsNotNone(config)
            self.assertTrue(config.notify_24h)
            self.assertFalse(config.notify_1h)
            self.assertEqual([u.id for u in config.users], [self.ids['extra']])
            self.assertEqual(config.groups, [])
        # Avisam só os destinatários escolhidos (extra), no marco de 24h —
        # véspera da reserva, depois da marca (início 09:00) e antes da de 1h.
        agora = datetime.combine(_data_futura(5) - timedelta(days=1), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._destinatarios(), [self.ids['extra']])

    def test_criar_sem_marco_e_recusado(self):
        self._login('criador@escola.edu')
        resposta = self.client.post('/reservations/create', data=self._dados_reserva(
            notify_enabled='on', notify_users=[str(self.ids['extra'])],
        ), follow_redirects=True)
        self.assertIn('ao menos um aviso', resposta.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(Reservation.query.first())

    def test_criar_com_somente_o_marco_no_dia(self):
        # O marco "no dia" também satisfaz a exigência de ao menos um aviso.
        self._login('criador@escola.edu')
        resposta = self.client.post('/reservations/create', data=self._dados_reserva(
            notify_enabled='on', notify_dia='on',
            notify_users=[str(self.ids['extra'])],
        ), follow_redirects=True)
        self.assertIn('agendada com sucesso', resposta.get_data(as_text=True))
        with self.app.app_context():
            config = Reservation.query.first().notification_config
            self.assertTrue(config.notify_dia)
            self.assertFalse(config.notify_24h)
            self.assertFalse(config.notify_1h)
            self.assertEqual(config.marcos_ativos, ['No dia da atividade (07:00)'])

    def test_criar_com_criador_como_unico_destinatario(self):
        # O checkbox do criador (marcado por padrão no formulário) satisfaz a
        # exigência de destinatário sozinho — sem usuários nem grupos.
        self._login('criador@escola.edu')
        resposta = self.client.post('/reservations/create', data=self._dados_reserva(
            notify_enabled='on', notify_24h='on', notify_criador='on',
        ), follow_redirects=True)
        self.assertIn('agendada com sucesso', resposta.get_data(as_text=True))
        with self.app.app_context():
            config = Reservation.query.first().notification_config
            self.assertTrue(config.notify_criador)
            self.assertEqual(config.users, [])
            self.assertEqual(config.groups, [])
        # A varredura avisa o criador mesmo sem destinatário explícito.
        agora = datetime.combine(_data_futura(5) - timedelta(days=1), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._destinatarios(), [self.ids['criador']])

    def test_editar_preserva_o_criador_e_o_marco_de_7d(self):
        reservation_id = self._criar_reserva(notificar=False)
        self._login('criador@escola.edu')
        resposta = self.client.post(f'/reservations/{reservation_id}/edit',
                                    data=self._dados_reserva(
                                        notify_enabled='on', notify_7d='on',
                                        notify_criador='on',
                                    ), follow_redirects=True)
        self.assertIn('atualizada com sucesso', resposta.get_data(as_text=True))
        with self.app.app_context():
            config = db.session.get(Reservation, reservation_id).notification_config
            self.assertTrue(config.notify_7d)
            self.assertTrue(config.notify_criador)
            self.assertFalse(config.notify_24h)
            self.assertEqual(config.marcos_ativos, ['7 dias antes'])

    def test_detalhe_mostra_criador_entre_destinatarios(self):
        reservation_id = self._criar_reserva(usuarios=('extra',),
                                             notify_criador=True)
        self._login('criador@escola.edu')
        html = self.client.get(f'/reservations/{reservation_id}').get_data(as_text=True)
        self.assertIn('1 destinatário + o criador', html)

    def test_detalhe_mostra_marco_no_dia(self):
        reservation_id = self._criar_reserva(notificar=True, notify_24h=False,
                                             notify_dia=True, usuarios=('extra',))
        self._login('criador@escola.edu')
        html = self.client.get(f'/reservations/{reservation_id}').get_data(as_text=True)
        self.assertIn('No dia da atividade (07:00)', html)

    def test_criar_sem_destinatario_e_recusado(self):
        self._login('criador@escola.edu')
        resposta = self.client.post('/reservations/create', data=self._dados_reserva(
            notify_enabled='on', notify_1h='on',
        ), follow_redirects=True)
        self.assertIn('ao menos um destinatário', resposta.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(Reservation.query.first())

    def test_editar_ativa_atualiza_e_desativa(self):
        reservation_id = self._criar_reserva(notificar=False)
        self._login('criador@escola.edu')

        # Ativa com 1h e um grupo; config nasce na edição.
        grupo_id = self._grupo()
        resposta = self.client.post(f'/reservations/{reservation_id}/edit',
                                    data=self._dados_reserva(
                                        notify_enabled='on', notify_1h='on',
                                        notify_groups=[str(grupo_id)],
                                    ), follow_redirects=True)
        self.assertIn('atualizada com sucesso', resposta.get_data(as_text=True))
        with self.app.app_context():
            reservation = db.session.get(Reservation, reservation_id)
            self.assertTrue(reservation.notify_enabled)
            config = reservation.notification_config
            self.assertTrue(config.notify_1h)
            self.assertFalse(config.notify_24h)
            self.assertEqual([g.id for g in config.groups], [grupo_id])

        # Desativa: a configuração é removida.
        resposta = self.client.post(f'/reservations/{reservation_id}/edit',
                                    data=self._dados_reserva(),
                                    follow_redirects=True)
        self.assertIn('atualizada com sucesso', resposta.get_data(as_text=True))
        with self.app.app_context():
            reservation = db.session.get(Reservation, reservation_id)
            self.assertFalse(reservation.notify_enabled)
            self.assertIsNone(reservation.notification_config)

    def test_detalhe_mostra_estado_e_atalho(self):
        reservation_id = self._criar_reserva(notificar=False,
                                             dono_id=self.ids['gestor'])
        self._login(EMAIL)
        html = self.client.get(f'/reservations/{reservation_id}').get_data(as_text=True)
        self.assertIn('Notificações desativadas', html)
        self.assertIn('Desativadas</span>', html)

        with self.app.app_context():
            reservation = db.session.get(Reservation, reservation_id)
            reservation.notify_enabled = True
            db.session.add(ReservationNotificationConfig(
                reservation=reservation, notify_24h=True, notify_1h=True))
            db.session.commit()
        html = self.client.get(f'/reservations/{reservation_id}').get_data(as_text=True)
        self.assertIn('Notificações ativadas', html)
        self.assertIn('24 horas antes, 1 hora antes', html)


class TestComandoNotifyScan(NotificationsTestCase):
    def test_comando_cria_e_dry_run_nao_grava(self):
        # Reserva hoje às 23h58: o marco de 24h venceu ontem — a janela aberta
        # garante o disparo independente da hora em que o comando roda (basta
        # não estar no último minuto do dia).
        reservation_id = self._criar_reserva(em_dias=0, hora=23, titulo='Aula Tarde')
        with self.app.app_context():
            reservation = db.session.get(Reservation, reservation_id)
            reservation.start_time = time(23, 58)
            reservation.end_time = time(23, 59)
            db.session.commit()
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
    def test_config_salva_grupos_da_sobrecarga(self):
        with self.app.app_context():
            grupo_sobrecarga = NotificationGroup(name='Sobrecarga',
                                                 unity_id=self.ids['unity'])
            db.session.add(grupo_sobrecarga)
            db.session.commit()
            id_sobrecarga = grupo_sobrecarga.id

        resposta = self.client.post('/admin/notificacoes/configuracao', data={
            'overload_groups': [str(id_sobrecarga)],
        }, follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('salvas', resposta.get_data(as_text=True))
        with self.app.app_context():
            config = UnityNotificationConfig.query.filter_by(
                unity_id=self.ids['unity']).first()
            self.assertIsNotNone(config)
            self.assertEqual([g.name for g in config.overload_groups], ['Sobrecarga'])

    def test_config_rejeita_grupo_de_outra_unidade(self):
        with self.app.app_context():
            outra_unity = Unity(name='Outra', code='OU')
            db.session.add(outra_unity)
            db.session.flush()
            grupo_alheio = NotificationGroup(name='Alheio', unity_id=outra_unity.id)
            db.session.add(grupo_alheio)
            db.session.commit()
            id_alheio = grupo_alheio.id
        resposta = self.client.post('/admin/notificacoes/configuracao', data={
            'overload_groups': [str(id_alheio)],
        }, follow_redirects=True)
        html = resposta.get_data(as_text=True)
        # Rejeitado (erro exibido) e nada salvo.
        self.assertNotIn('salvas', html)
        self.assertTrue('válido' in html or 'inválido' in html)
        with self.app.app_context():
            config = UnityNotificationConfig.query.filter_by(
                unity_id=self.ids['unity']).first()
            self.assertIsNone(config)

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


class TestPreferenciasNoPerfil(NotificationsTestCase):
    """Preferências de notificação no perfil: silenciar tudo ou por tipo de
    sala — e a varredura as respeita."""

    def test_perfil_mostra_secao(self):
        self._login('criador@escola.edu')
        html = self.client.get('/perfil').get_data(as_text=True)
        self.assertIn('Notificações', html)
        self.assertIn('Silenciar por tipo de sala', html)
        self.assertIn('Sala de Aula', html)

    def test_salva_silencio_total_e_por_categoria(self):
        self._login('criador@escola.edu')
        resposta = self.client.post('/perfil', data={
            'full_name': 'Carla Criadora',
            'notify_mute_all': 'on',
        }, follow_redirects=True)
        self.assertIn('atualizado com sucesso', resposta.get_data(as_text=True))
        with self.app.app_context():
            pref = db.session.get(UserNotificationPref, self.ids['criador'])
            self.assertIsNotNone(pref)
            self.assertTrue(pref.mute_all)
            self.assertEqual(pref.muted_categories, [])

        # Desmarca o silêncio total e silencia só o laboratório
        resposta = self.client.post('/perfil', data={
            'full_name': 'Carla Criadora',
            'notify_muted_categories': [str(self.ids['lab'])],
        }, follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        with self.app.app_context():
            pref = db.session.get(UserNotificationPref, self.ids['criador'])
            self.assertFalse(pref.mute_all)
            self.assertEqual([c.id for c in pref.muted_categories], [self.ids['lab']])

    def test_preferencias_sao_aplicadas_na_varredura(self):
        self._criar_reserva(usuarios=('extra', 'criador'))
        self._login('extra@escola.edu')
        self.client.post('/perfil', data={
            'full_name': 'Eva Extra',
            'notify_muted_categories': [str(self.ids['categoria'])],
        }, follow_redirects=True)
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._destinatarios(), [self.ids['criador']])


class TestCentroNotificacoes(NotificationsTestCase):
    def test_listagem_mostra_notificacao(self):
        notificacao_id = self._notificar(self.ids['criador'])
        self._login('criador@escola.edu')
        resposta = self.client.get('/notificacoes/')
        self.assertEqual(resposta.status_code, 200)
        html = resposta.get_data(as_text=True)
        self.assertIn('Em 24 horas', html)
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
        self._notificar(self.ids['criador'], titulo='Em 1 hora: Outra aula')
        self._login('criador@escola.edu')
        resposta = self.client.post('/notificacoes/marcar-todas', follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self.client.get('/notificacoes/api/nao-lidas').get_json()['count'], 0)

    def test_limpar_lidas_remove_somente_lidas(self):
        lida_id = self._notificar(self.ids['criador'])
        self._notificar(self.ids['criador'], titulo='Em 1 hora: Outra aula')
        self._login('criador@escola.edu')
        self.client.post(f'/notificacoes/{lida_id}/lida', follow_redirects=False)

        # Botão aparece com a contagem quando há lidas (global, não só da página)
        html = self.client.get('/notificacoes/').get_data(as_text=True)
        self.assertIn('Limpar lidas (1)', html)

        resposta = self.client.post('/notificacoes/limpar-lidas', follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertIn('removida', resposta.get_data(as_text=True))
        with self.app.app_context():
            self.assertIsNone(db.session.get(Notification, lida_id))
        self.assertEqual(self._contar(user_id=self.ids['criador']), 1)  # a não lida fica

        # Sem lidas restantes, o botão fica desabilitado e sem contagem
        html = self.client.get('/notificacoes/').get_data(as_text=True)
        self.assertIn('outline-danger" disabled', html)
        self.assertNotIn('Limpar lidas (', html)

    def test_limpar_lidas_so_afeta_o_proprio_usuario(self):
        lida_criador = self._notificar(self.ids['criador'])
        lida_extra = self._notificar(self.ids['extra'])
        self._login('criador@escola.edu')
        self.client.post(f'/notificacoes/{lida_criador}/lida')
        self._login('extra@escola.edu')
        self.client.post(f'/notificacoes/{lida_extra}/lida')
        self._login('criador@escola.edu')

        resposta = self.client.post('/notificacoes/limpar-lidas', follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Notification, lida_criador))
            self.assertIsNotNone(db.session.get(Notification, lida_extra))

    def test_notificacao_de_outro_usuario_vira_404(self):
        notificacao_id = self._notificar(self.ids['extra'])
        self._login('criador@escola.edu')
        resposta = self.client.post(f'/notificacoes/{notificacao_id}/lida')
        self.assertEqual(resposta.status_code, 404)

    def test_requer_login(self):
        self.client.get('/logout')
        resposta = self.client.get('/notificacoes/')
        self.assertEqual(resposta.status_code, 302)  # redireciona para login


class TestMarcoNoDia(NotificationsTestCase):
    """O marco "no dia" dispara a partir das 07:00 do próprio dia da
    atividade — não é antecedência em horas; a janela aberta e a regra do
    gatilho mais recente vencido valem como nos demais marcos."""

    def test_cria_no_marco_no_dia(self):
        # Reserva hoje às 10h; "agora" 07:05: o gatilho (07:00) venceu e a
        # atividade ainda não começou.
        self._criar_reserva(em_dias=0, hora=10, notify_24h=False, notify_dia=True)
        agora = datetime.combine(date.today(), time(7, 5))
        with self.app.app_context():
            stats = varrer_reservas(agora=agora)
        self.assertEqual(stats['criadas'], 2)
        self.assertEqual(self._contar(milestone='dia'), 2)
        with self.app.app_context():
            titulo = Notification.query.first().title
        self.assertTrue(titulo.startswith('Hoje:'))

    def test_atividade_da_madrugada_nao_recebe_no_dia(self):
        # Começa 06:00: quando o gatilho (07:00) passa, a atividade já
        # começou — limitação documentada do marco "no dia".
        self._criar_reserva(em_dias=0, hora=6, notify_24h=False, notify_dia=True)
        agora = datetime.combine(date.today(), time(7, 5))
        with self.app.app_context():
            self.assertEqual(varrer_reservas(agora=agora)['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_no_dia_vence_o_24h_quando_ambos_vencidos(self):
        # Reserva hoje às 10h com 24h e "no dia": às 07:05 os dois gatilhos já
        # passaram (o de 24h desde ontem 10h); dispara o de gatilho mais
        # recente — o "no dia" — e o de 24h fica absorvido.
        self._criar_reserva(em_dias=0, hora=10, notify_24h=True, notify_dia=True)
        agora = datetime.combine(date.today(), time(7, 5))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._contar(milestone='dia'), 2)
        self.assertEqual(self._contar(milestone='24h'), 0)

    def test_24h_dispara_antes_do_no_dia(self):
        # Véspera à tarde: só o 24h venceu; o "no dia" fica para o gatilho de
        # 07:00 do dia da atividade.
        self._criar_reserva(em_dias=1, hora=10, notify_24h=True, notify_dia=True)
        agora = datetime.combine(date.today(), time(15, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._contar(milestone='24h'), 2)
        self.assertEqual(self._contar(milestone='dia'), 0)

    def test_cria_no_marco_de_7d(self):
        # Reserva em 9 dias às 10h; "agora" é 8 dias antes: só o marco de 7
        # dias venceu (faltam 8 dias... gatilho = início − 7d, ontem 10h).
        self._criar_reserva(em_dias=9, hora=10, notify_7d=True,
                            notify_24h=False)
        agora = datetime.combine(date.today() + timedelta(days=8), time(11, 0))
        with self.app.app_context():
            stats = varrer_reservas(agora=agora)
        self.assertEqual(stats['criadas'], 2)
        self.assertEqual(self._contar(milestone='7d'), 2)
        with self.app.app_context():
            titulo = Notification.query.first().title
        self.assertTrue(titulo.startswith('Em 7 dias:'))

    def test_7d_absorvido_pelo_24h_mais_iminente(self):
        # 7d e 24h habilitados; "agora" dentro da janela dos dois: dispara o
        # de gatilho mais recente (24h) e o de 7 dias fica absorvido.
        self._criar_reserva(em_dias=8, hora=10, notify_7d=True,
                            notify_24h=True)
        agora = datetime.combine(date.today() + timedelta(days=7), time(11, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._contar(milestone='7d'), 0)
        self.assertEqual(self._contar(milestone='24h'), 2)

    def test_criador_recebe_quando_ativado(self):
        # notify_criador ligado e nenhum destinatário explícito: o criador
        # recebe o aviso da própria reserva.
        self._criar_reserva(usuarios=(), notify_criador=True)
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._destinatarios(), [self.ids['criador']])

    def test_criador_nao_duplica_quando_ja_e_destinatario(self):
        # Criador também escolhido como usuário individual: recebe UMA vez.
        self._criar_reserva(usuarios=('criador',), notify_criador=True)
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            varrer_reservas(agora=agora)
        self.assertEqual(self._contar(user_id=self.ids['criador']), 1)
        self.assertEqual(self._contar(), 1)

    def test_criador_inativo_nao_recebe(self):
        self._criar_reserva(usuarios=(), notify_criador=True)
        with self.app.app_context():
            User.query.filter_by(id=self.ids['criador']).update(
                {'is_active_user': False})
            db.session.commit()
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
        with self.app.app_context():
            self.assertEqual(varrer_reservas(agora=agora)['criadas'], 0)
        self.assertEqual(self._contar(), 0)


class TestMudancaStatus(NotificationsTestCase):
    """Aviso ao criador quando a reserva é aprovada ou cancelada por outra
    pessoa — ação do próprio criador não avisa; reaprovação não duplica."""

    def test_aprovacao_avisa_criador(self):
        reservation_id = self._criar_reserva(status='pending', notificar=False)
        self._login(EMAIL)  # gestor, com reservation:approve
        resposta = self.client.post(f'/reservations/{reservation_id}/approve',
                                    follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        with self.app.app_context():
            aviso = Notification.query.one()
        self.assertEqual(aviso.event_type, 'reservation_approved')
        self.assertEqual(aviso.user_id, self.ids['criador'])
        self.assertEqual(aviso.milestone, 'status')
        self.assertTrue(aviso.title.startswith('Reserva aprovada:'))
        self.assertEqual(aviso.url, f'/reservations/{reservation_id}')

    def test_cancelamento_avisa_criador(self):
        reservation_id = self._criar_reserva(notificar=False)
        self._login(EMAIL)
        resposta = self.client.post(f'/reservations/{reservation_id}/cancel',
                                    follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        with self.app.app_context():
            aviso = Notification.query.one()
        self.assertEqual(aviso.event_type, 'reservation_cancelled')
        self.assertIn('foi cancelada', aviso.body)
        self.assertNotIn('aguardava', aviso.body)

    def test_cancelamento_de_pendente_menciona_aprovacao_pendente(self):
        reservation_id = self._criar_reserva(status='pending', notificar=False)
        self._login(EMAIL)
        self.client.post(f'/reservations/{reservation_id}/cancel', follow_redirects=True)
        with self.app.app_context():
            aviso = Notification.query.one()
        self.assertIn('aguardava aprovação', aviso.body)

    def test_acao_do_proprio_criador_nao_avisa(self):
        reservation_id = self._criar_reserva(notificar=False)
        self._login('criador@escola.edu')
        resposta = self.client.post(f'/reservations/{reservation_id}/cancel',
                                    follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self._contar(), 0)

    def test_reaprovacao_nao_duplica(self):
        reservation_id = self._criar_reserva(status='pending', notificar=False)
        self._login(EMAIL)
        self.client.post(f'/reservations/{reservation_id}/approve', follow_redirects=True)
        # Volta a pendente (ex.: edição acionou a regra de carga docente)...
        with self.app.app_context():
            db.session.get(Reservation, reservation_id).status = 'pending'
            db.session.commit()
        # ...e é aprovada de novo: a unicidade impede o segundo aviso.
        self.client.post(f'/reservations/{reservation_id}/approve', follow_redirects=True)
        self.assertEqual(self._contar(event_type='reservation_approved'), 1)

    def test_cancelamento_de_serie_avisa_o_criador_de_cada_reserva(self):
        # Série de duas reservas do criador; o gestor cancela as duas — cada
        # cancelamento gera um aviso (aqui, dois para o mesmo criador).
        with self.app.app_context():
            r1 = Reservation(user_id=self.ids['criador'], classroom_id=self.ids['sala'],
                             teacher_id=self.ids['professor'], unity_id=self.ids['unity'],
                             title='Aula Série 1', date=_data_futura(5),
                             start_time=time(9, 0), end_time=time(11, 0),
                             status='approved', notify_enabled=False)
            db.session.add(r1)
            db.session.flush()
            r1.repeat_group_id = r1.id  # a origem pertence ao próprio grupo
            r2 = Reservation(user_id=self.ids['criador'], classroom_id=self.ids['sala'],
                             teacher_id=self.ids['professor'], unity_id=self.ids['unity'],
                             title='Aula Série 2', repeat_group_id=r1.id,
                             date=_data_futura(6),
                             start_time=time(9, 0), end_time=time(11, 0),
                             status='approved', notify_enabled=False)
            db.session.add(r2)
            db.session.commit()
            ids = [r1.id, r2.id]
        self._login(EMAIL)
        resposta = self.client.post(f'/reservations/{ids[0]}/series/delete',
                                    data={'mode': 'cancel',
                                          'selected': [str(i) for i in ids]},
                                    follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        with self.app.app_context():
            avisos = Notification.query.all()
        self.assertEqual(len(avisos), 2)
        self.assertTrue(all(a.event_type == 'reservation_cancelled' for a in avisos))
        self.assertEqual({a.user_id for a in avisos}, {self.ids['criador']})


class TestExclusao(NotificationsTestCase):
    """Aviso de exclusão permanente: criado para o criador, com reservation_id
    nulo (a FK apagaria o aviso em cascata junto com a reserva)."""

    def test_exclusao_avisa_criador_sem_referenciar_a_reserva(self):
        reservation_id = self._criar_reserva(notificar=False)
        self._login(EMAIL)  # gestor, com reservation:delete_all
        resposta = self.client.post(f'/reservations/{reservation_id}/delete',
                                    follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        with self.app.app_context():
            aviso = Notification.query.one()
        self.assertEqual(aviso.event_type, 'reservation_deleted')
        self.assertEqual(aviso.user_id, self.ids['criador'])
        self.assertIsNone(aviso.reservation_id)  # sobrevive à exclusão
        self.assertIsNone(aviso.url)             # não há para onde linkar
        self.assertTrue(aviso.title.startswith('Reserva excluída:'))
        self.assertIn('excluída permanentemente', aviso.body)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Reservation, reservation_id))

    def test_exclusao_da_proprio_reserva_do_gestor_nao_avisa(self):
        # A rota de exclusão dura é só para quem tem delete_all: o caso de
        # "ação do próprio criador" é o admin excluindo a reserva dele mesmo.
        reservation_id = self._criar_reserva(notificar=False,
                                             dono_id=self.ids['gestor'])
        self._login(EMAIL)
        resposta = self.client.post(f'/reservations/{reservation_id}/delete',
                                    follow_redirects=True)
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(self._contar(), 0)


class TestLembretePendentes(NotificationsTestCase):
    """Lembretes de reserva pendente aguardando aprovação: avisam os
    aprovadores da unidade 24h e 48h após a criação."""

    def _pendente_antiga(self, *, horas_criada=25, em_dias=5, agora=None):
        """Reserva pendente criada há N horas ANTES de `agora` — o mesmo
        relógio passado à varredura, para não misturar o UTC de created_at
        com a hora local do teste."""
        agora = agora or datetime.now()
        reservation_id = self._criar_reserva(status='pending', notificar=False,
                                             em_dias=em_dias)
        with self.app.app_context():
            reservation = db.session.get(Reservation, reservation_id)
            reservation.created_at = agora - timedelta(hours=horas_criada)
            db.session.commit()
        return reservation_id

    def test_lembrete_apos_24h_avisa_aprovadores(self):
        agora = datetime.now()
        self._pendente_antiga(horas_criada=25, agora=agora)
        with self.app.app_context():
            stats = varrer_pendentes(agora=agora)
        self.assertEqual(stats['criadas'], 1)
        with self.app.app_context():
            aviso = Notification.query.one()
        self.assertEqual(aviso.event_type, 'reservation_pending_reminder')
        self.assertEqual(aviso.user_id, self.ids['gestor'])  # único aprovador
        self.assertEqual(aviso.milestone, '24h')
        self.assertTrue(aviso.title.startswith('Pendente há 1 dia:'))
        self.assertIn('aguarda aprovação', aviso.body)
        self.assertEqual(aviso.url, '/reservations/all?status=pending')

    def test_criador_sem_permissao_de_aprovar_nao_recebe(self):
        agora = datetime.now()
        self._pendente_antiga(horas_criada=25, agora=agora)
        with self.app.app_context():
            varrer_pendentes(agora=agora)
            usuarios_avisados = {n.user_id for n in Notification.query.all()}
        self.assertNotIn(self.ids['criador'], usuarios_avisados)

    def test_sem_lembrete_antes_de_24h(self):
        agora = datetime.now()
        self._pendente_antiga(horas_criada=2, agora=agora)
        with self.app.app_context():
            self.assertEqual(varrer_pendentes(agora=agora)['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_segundo_lembrete_apos_48h(self):
        agora1 = datetime.now()
        self._pendente_antiga(horas_criada=25, agora=agora1)
        with self.app.app_context():
            varrer_pendentes(agora=agora1)
        # 25 horas depois: o lembrete de 48h vence — dispara o mais recente,
        # o de 24h fica absorvido (já saiu antes).
        agora2 = agora1 + timedelta(hours=25)
        with self.app.app_context():
            reservation = db.session.get(Reservation, self._ids_lembrete())
            reservation.created_at = agora2 - timedelta(hours=49)
            db.session.commit()
            stats = varrer_pendentes(agora=agora2)
        self.assertEqual(stats['criadas'], 1)
        self.assertEqual(self._contar(milestone='24h'), 1)
        self.assertEqual(self._contar(milestone='48h'), 1)

    def _ids_lembrete(self):
        """Id da única reserva pendente do teste (para retroagir de novo)."""
        return Reservation.query.filter_by(status='pending').first().id

    def test_reserva_aprovada_ou_passada_nao_lembra(self):
        # Aprovada não está mais pendente; pendente com data passada também
        # não tem mais o que aprovar.
        agora = datetime.now()
        self._criar_reserva(status='approved', notificar=False)
        with self.app.app_context():
            Reservation.query.filter_by(status='approved').update(
                {'created_at': agora - timedelta(hours=30)})
            db.session.commit()
        self._pendente_antiga(horas_criada=30, em_dias=-1, agora=agora)
        with self.app.app_context():
            self.assertEqual(varrer_pendentes(agora=agora)['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_aprovador_silenciado_nao_recebe(self):
        agora = datetime.now()
        self._pendente_antiga(horas_criada=25, agora=agora)
        self._silenciar(self.ids['gestor'], mute_all=True)()
        with self.app.app_context():
            self.assertEqual(varrer_pendentes(agora=agora)['criadas'], 0)
        self.assertEqual(self._contar(), 0)

    def test_idempotente_nao_duplica(self):
        agora = datetime.now()
        self._pendente_antiga(horas_criada=25, agora=agora)
        with self.app.app_context():
            varrer_pendentes(agora=agora)
            stats = varrer_pendentes(agora=agora)
        self.assertEqual(stats['criadas'], 0)
        self.assertEqual(stats['existentes'], 1)
        self.assertEqual(self._contar(), 1)


class TestLimpeza(NotificationsTestCase):
    """Limpeza de notificações antigas (comando notify-cleanup)."""

    def _notificacao_antiga(self, *, user_id, lida_ha_dias=None,
                            reserva_em_dias=None):
        """Notificação crua; lida_ha_dias retroage read_at; reserva_em_dias
        cria a reserva associada com data retroagida/futurada."""
        def gravar():
            with self.app.app_context():
                reservation_id = None
                if reserva_em_dias is not None:
                    reservation = Reservation(
                        user_id=user_id, classroom_id=self.ids['sala'],
                        teacher_id=self.ids['professor'],
                        unity_id=self.ids['unity'], title='Aula Antiga',
                        date=date.today() + timedelta(days=reserva_em_dias),
                        start_time=time(9, 0), end_time=time(11, 0),
                        status='approved', notify_enabled=False)
                    db.session.add(reservation)
                    db.session.flush()
                    reservation_id = reservation.id
                notificacao = Notification(user_id=user_id, milestone='24h',
                                           title='Em 24 horas: Aula Antiga',
                                           body='S1 · 09:00–11:00',
                                           url='/calendar/?initialDate=2026-01-01',
                                           reservation_id=reservation_id)
                if lida_ha_dias is not None:
                    notificacao.read_at = (datetime.now(timezone.utc)
                                           - timedelta(days=lida_ha_dias))
                db.session.add(notificacao)
                db.session.commit()
                return notificacao.id
        return gravar()

    def test_apaga_lidas_antigas_e_reservas_passadas(self):
        # Lida há 91 dias: fora. Lida há 10 dias: fica. Não lida de reserva
        # passada há 40 dias: fora mesmo sem leitura. Não lida de reserva
        # futura: fica. Aviso de exclusão (reservation_id nulo) não lido: fica
        # pela regra das reservas — só sai quando lido e antigo.
        antiga_lida = self._notificacao_antiga(user_id=self.ids['criador'],
                                               lida_ha_dias=91)
        recente_lida = self._notificacao_antiga(user_id=self.ids['criador'],
                                                lida_ha_dias=10)
        passada_nao_lida = self._notificacao_antiga(
            user_id=self.ids['criador'], reserva_em_dias=-40)
        futura_nao_lida = self._notificacao_antiga(
            user_id=self.ids['criador'], reserva_em_dias=5)
        sem_reserva_nao_lida = self._notificacao_antiga(
            user_id=self.ids['criador'])

        resultado = self.app.test_cli_runner().invoke(args=['notify-cleanup'])
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('Lidas há mais de 90 dias apagadas: 1', resultado.output)
        self.assertIn('passadas há mais de 30 dias apagadas: 1', resultado.output)

        with self.app.app_context():
            vivas = {n.id for n in Notification.query.all()}
        self.assertNotIn(antiga_lida, vivas)
        self.assertNotIn(passada_nao_lida, vivas)
        self.assertEqual(vivas, {recente_lida, futura_nao_lida,
                                 sem_reserva_nao_lida})

    def test_dry_run_nao_apaga_nada(self):
        antiga_lida = self._notificacao_antiga(user_id=self.ids['criador'],
                                               lida_ha_dias=91)
        resultado = self.app.test_cli_runner().invoke(
            args=['notify-cleanup', '--dry-run'])
        self.assertEqual(resultado.exit_code, 0)
        self.assertIn('seriam apagadas: 1', resultado.output)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Notification, antiga_lida))


class TestEmailMirror(NotificationsTestCase):
    """Espelho por e-mail: dreno da fila pelo sent_at, opt-out no perfil,
    falha de SMTP e no-op sem SMTP configurado."""

    def _habilitar_smtp(self):
        self.app.config['MAIL_SMTP_HOST'] = 'smtp.teste'
        self.app.config['MAIL_FROM'] = 'sigere@teste.edu'
        self.app.config['BASE_URL'] = 'https://sigere.teste'

    def _desativar_email(self, user_id):
        def gravar():
            with self.app.app_context():
                db.session.add(UserNotificationPref(user_id=user_id,
                                                    email_enabled=False))
                db.session.commit()
        return gravar

    @patch('app.services.mailer.smtplib.SMTP')
    def test_envia_e_carimba_sent_at(self, smtp_cls):
        self._habilitar_smtp()
        self._notificar(self.ids['professor'])
        self._notificar(self.ids['criador'], titulo='Em 1 hora: Outra aula')
        with self.app.app_context():
            stats = drenar_fila_email()
        self.assertEqual(stats['emails'], 2)  # um por destinatário (digest)
        self.assertEqual(stats['notificacoes'], 2)
        self.assertEqual(stats['falhas'], 0)
        smtp_cls.assert_called_once_with('smtp.teste', 587, timeout=30)
        smtp_inst = smtp_cls.return_value.__enter__.return_value
        self.assertEqual(smtp_inst.send_message.call_count, 2)
        destinatarios = {c.args[0]['To']
                         for c in smtp_inst.send_message.call_args_list}
        self.assertEqual(destinatarios, {'prof@escola.edu', 'criador@escola.edu'})
        primeira = smtp_inst.send_message.call_args_list[0].args[0]
        self.assertEqual(primeira['Subject'], 'Em 24 horas: Aula de Teste')
        self.assertIn('Ver no SIGERE: https://sigere.teste/calendar/?initialDate=2026-10-01',
                      primeira.get_content())
        with self.app.app_context():
            self.assertTrue(all(n.sent_at is not None
                                for n in Notification.query.all()))

    @patch('app.services.mailer.smtplib.SMTP')
    def test_digest_agrupa_notificacoes_do_mesmo_usuario(self, smtp_cls):
        # Duas pendências do mesmo usuário saem num único e-mail com as duas.
        self._habilitar_smtp()
        self._notificar(self.ids['professor'])
        self._notificar(self.ids['professor'], titulo='Em 1 hora: Outra aula')
        with self.app.app_context():
            stats = drenar_fila_email()
        self.assertEqual(stats['emails'], 1)
        self.assertEqual(stats['notificacoes'], 2)
        smtp_inst = smtp_cls.return_value.__enter__.return_value
        self.assertEqual(smtp_inst.send_message.call_count, 1)
        msg = smtp_inst.send_message.call_args.args[0]
        self.assertEqual(msg['Subject'], 'SIGERE: 2 notificações novas')
        corpo = msg.get_content()
        self.assertIn('Em 24 horas: Aula de Teste', corpo)
        self.assertIn('Em 1 hora: Outra aula', corpo)
        self.assertIn('https://sigere.teste/perfil', corpo)  # rodapé do opt-out
        with self.app.app_context():
            self.assertTrue(all(n.sent_at is not None
                                for n in Notification.query.all()))

    @patch('app.services.mailer.smtplib.SMTP')
    def test_falha_de_envio_conta_tentativa_e_fica_pendente(self, smtp_cls):
        self._habilitar_smtp()
        notificacao_id = self._notificar(self.ids['professor'])
        smtp_cls.return_value.__enter__.return_value.send_message.side_effect = \
            Exception('SMTP fora do ar')
        with self.app.app_context():
            stats = drenar_fila_email()
        self.assertEqual(stats['emails'], 0)
        self.assertEqual(stats['falhas'], 1)
        with self.app.app_context():
            n = db.session.get(Notification, notificacao_id)
            self.assertIsNone(n.sent_at)
            self.assertEqual(n.send_attempts, 1)

    @patch('app.services.mailer.smtplib.SMTP')
    def test_tentativas_excedidas_saem_da_fila(self, smtp_cls):
        self._habilitar_smtp()
        notificacao_id = self._notificar(self.ids['professor'])
        with self.app.app_context():
            db.session.get(Notification, notificacao_id).send_attempts = 10
            db.session.commit()
            stats = drenar_fila_email()
        self.assertEqual(stats['pendentes'], 0)   # fora da rodada
        self.assertEqual(stats['excedidas'], 1)   # e visíveis no relatório
        smtp_inst = smtp_cls.return_value.__enter__.return_value
        smtp_inst.send_message.assert_not_called()
        with self.app.app_context():
            self.assertIsNone(db.session.get(Notification, notificacao_id).sent_at)

    @patch('app.services.mailer.smtplib.SMTP')
    def test_reenvio_apos_falha_carimba_e_mantem_tentativas(self, smtp_cls):
        self._habilitar_smtp()
        notificacao_id = self._notificar(self.ids['professor'])
        smtp_inst = smtp_cls.return_value.__enter__.return_value
        smtp_inst.send_message.side_effect = Exception('SMTP fora do ar')
        with self.app.app_context():
            drenar_fila_email()
        # Rodada seguinte, SMTP de volta: envia e carimba.
        smtp_inst.send_message.side_effect = None
        with self.app.app_context():
            stats = drenar_fila_email()
        self.assertEqual(stats['emails'], 1)
        with self.app.app_context():
            n = db.session.get(Notification, notificacao_id)
            self.assertIsNotNone(n.sent_at)
            self.assertEqual(n.send_attempts, 1)  # a falha anterior fica registrada

    @patch('app.services.mailer.smtplib.SMTP')
    def test_optout_sai_da_fila_sem_enviar(self, smtp_cls):
        self._habilitar_smtp()
        self._notificar(self.ids['extra'])
        self._desativar_email(self.ids['extra'])()
        with self.app.app_context():
            stats = drenar_fila_email()
        self.assertEqual(stats['puladas'], 1)
        self.assertEqual(stats['emails'], 0)
        smtp_cls.return_value.__enter__.return_value.send_message.assert_not_called()
        # Sai da fila para sempre (sent_at carimbado sem envio).
        with self.app.app_context():
            self.assertIsNotNone(Notification.query.first().sent_at)

    def test_sem_smtp_configurado_nao_faz_nada(self):
        self._notificar(self.ids['professor'])
        with self.app.app_context():
            stats = drenar_fila_email()
        self.assertEqual(stats['puladas'], -1)  # convenção: envio desativado
        with self.app.app_context():
            self.assertIsNone(Notification.query.first().sent_at)

    @patch('app.services.mailer.smtplib.SMTP')
    def test_comando_notify_email_dry_run(self, smtp_cls):
        self._habilitar_smtp()
        self._notificar(self.ids['professor'])
        resultado = self.app.test_cli_runner().invoke(args=['notify-email', '--dry-run'])
        self.assertEqual(resultado.exit_code, 0)
        self.assertIn('seriam enviados: 1', resultado.output)
        smtp_cls.return_value.__enter__.return_value.send_message.assert_not_called()
        with self.app.app_context():
            self.assertIsNone(Notification.query.first().sent_at)

    def test_comando_sem_smtp_avisa_desativado(self):
        self._notificar(self.ids['professor'])
        resultado = self.app.test_cli_runner().invoke(args=['notify-email'])
        self.assertEqual(resultado.exit_code, 0)
        self.assertIn('desativado', resultado.output)


class TestApiRecentes(NotificationsTestCase):
    """Dropdown do sino: preview das últimas notificações do próprio usuário
    e marcação de lida por fetch (JSON em vez de redirect)."""

    def test_devolve_somente_do_proprio_usuario_mais_recentes_primeiro(self):
        self._notificar(self.ids['extra'])
        self._notificar(self.ids['criador'])
        self._notificar(self.ids['criador'], titulo='Em 1 hora: Outra aula')
        self._login('criador@escola.edu')
        resposta = self.client.get('/notificacoes/api/recentes')
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.get_json()
        self.assertEqual(dados['count'], 2)
        self.assertEqual([i['titulo'] for i in dados['itens']],
                         ['Em 1 hora: Outra aula', 'Em 24 horas: Aula de Teste'])
        self.assertTrue(all(i['lida'] is False for i in dados['itens']))
        self.assertIn('initialDate=2026-10-01', dados['itens'][0]['url'])

    def test_marcar_lida_por_fetch_devolve_json(self):
        notificacao_id = self._notificar(self.ids['criador'])
        self._login('criador@escola.edu')
        resposta = self.client.post(f'/notificacoes/{notificacao_id}/lida',
                                    headers={'X-Requested-With': 'fetch'})
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.get_json()
        self.assertTrue(dados['ok'])
        self.assertEqual(dados['count'], 0)

    def test_marcar_todas_por_fetch_devolve_json(self):
        self._notificar(self.ids['criador'])
        self._notificar(self.ids['criador'], titulo='Em 1 hora: Outra aula')
        self._login('criador@escola.edu')
        resposta = self.client.post('/notificacoes/marcar-todas',
                                    headers={'X-Requested-With': 'fetch'})
        self.assertEqual(resposta.status_code, 200)
        dados = resposta.get_json()
        self.assertTrue(dados['ok'])
        self.assertEqual(dados['count'], 0)
        self.assertEqual(self.client.get('/notificacoes/api/nao-lidas').get_json()['count'], 0)

    def test_requer_login(self):
        self.client.get('/logout')
        resposta = self.client.get('/notificacoes/api/recentes')
        self.assertEqual(resposta.status_code, 302)  # redireciona para login


if __name__ == '__main__':
    unittest.main()
