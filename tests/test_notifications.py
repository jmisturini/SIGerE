"""Testes do módulo de notificações de atividades próximas.

Cobre:
- a configuração por reserva: interruptor (padrão desativado) no formulário de
  criar/editar, marcos de antecedência (24h/1h antes do início) e destinatários
  explícitos (usuários individuais e grupos personalizados);
- o serviço de varredura: marcos por horas, janela aberta (o mais iminente
  vencido dispara), idempotência, status, atividade já iniciada e reservas sem
  configuração;
- as preferências do usuário no perfil: silenciar tudo ou por tipo de sala;
- o comando `flask notify-scan` (inclusive --dry-run);
- o painel admin: aviso de sobrecarga de professor (única configuração de
  unidade que resta) e CRUD de grupos com escopo;
- o centro de notificações do usuário: listagem, sino (badge), marcar lida,
  limpar as lidas.
"""
import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Notification, NotificationGroup,
                        Permission, Reservation, ReservationNotificationConfig,
                        Role, RoomCategory, Unity, UnityNotificationConfig,
                        User, UserNotificationPref)
from app.services.notifications import varrer_reservas

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


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
                               'reservation:read_own')]
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
                       titulo='Aula de Teste', notificar=True, notify_24h=True,
                       notify_1h=False, usuarios=('professor', 'criador'),
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
                        notify_24h=notify_24h, notify_1h=notify_1h)
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
            'date': (date.today() + timedelta(days=em_dias)).isoformat(),
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
        # Avisam só os destinatários escolhidos (extra), no marco de 24h.
        agora = datetime.combine(date.today() + timedelta(days=4), time(12, 0))
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
    def _notificar(self, user_id, titulo='Em 24 horas: Aula de Teste'):
        def gravar():
            with self.app.app_context():
                notificacao = Notification(user_id=user_id, milestone='24h',
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


if __name__ == '__main__':
    unittest.main()
