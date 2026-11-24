"""Testes do lock por (docente, data) — dimensão docente da corrida TOCTOU.

O slot_locks cobre só (sala, data): duas gravações simultâneas em salas
DIFERENTES, mesmo docente e mesma janela, passavam ambas pela checagem de
professor e gravavam sobreposição (ou estouravam o limite diário) — issue
#234. O teacher_locks fecha a dimensão: mesmo mecanismo do slot_locks
(RLock por chave + advisory transacional no PostgreSQL), adquirido por todos
os escritores SEMPRE depois dos locks de sala (ordem única: quem segura
docente nunca espera por sala — ciclo impossível).

Cobertura: exclusão mútua real entre threads no mesmo (docente, data), datas
diferentes não se bloqueiam, reserva sem docente não trava nada, a
revalidação de aprovação conta só aprovadas (duas pendências sobrepostas do
mesmo docente não podem se bloquear para sempre), o fluxo de aprovação
recusa docente sobreposto aprovado concorrentemente e todo aborto dentro de
um bloco de travas solta o que segurava antes de montar a resposta.
"""
import os
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Permission, Reservation, Role,
                        RoomCategory, Unity, User)
from app.services import scheduling
from app.services.scheduling import check_teacher_conflict, teacher_locks

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'

# Corpo do "outro processo" da edição concorrente (rodado via `python -c`):
# muda SÓ os horários da reserva e COMMITA, com os valores tipados como o app
# grava (Core, objetos time — texto cru gravaria outro formato na coluna).
_EDICAO_CONCURRENTE = """
import sys
from datetime import time
from sqlalchemy import (Column, Integer, MetaData, Table, Time, create_engine,
                        update)
from sqlalchemy.orm import Session

reservas = Table(
    'reservations', MetaData(),
    Column('id', Integer, primary_key=True),
    Column('start_time', Time), Column('end_time', Time))
uri, reserva_id = sys.argv[1], int(sys.argv[2])
motor = create_engine(uri)
with Session(motor) as sessao:
    sessao.execute(
        update(reservas).where(reservas.c.id == reserva_id)
        .values(start_time=time(10, 0), end_time=time(11, 0)))
    sessao.commit()
motor.dispose()
"""


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class TeacherLocksTestCase(unittest.TestCase):
    def setUp(self):
        # Dicionários de lock são globais ao módulo: limpar entre casos
        # (nenhum teste segura lock além do próprio corpo).
        scheduling._slot_locks.clear()
        scheduling._teacher_locks.clear()
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

            perms = [Permission(code='reservation:create', module='reservation', action='create'),
                     Permission(code='reservation:read_own', module='reservation', action='read_own'),
                     Permission(code='reservation:approve', module='reservation', action='approve')]
            db.session.add_all(perms)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=perms)
            db.session.add(role)
            db.session.flush()

            gestor = User(
                email=EMAIL, full_name='Gestor Teste',
                role='room', profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            gestor.set_password(PASSWORD)
            db.session.add(gestor)
            db.session.flush()

            professor = User(
                email='professor@escola.edu', full_name='Professor Silva',
                role='room', profile_type='teacher', unities=[self.unity],
                force_password_change=False, is_active_user=True,
            )
            professor.set_password(PASSWORD)
            db.session.add(professor)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()

            sala1 = Classroom(name='Sala 1', code='S1', capacity=30,
                              unity_id=self.unity.id, category_id=category.id)
            sala2 = Classroom(name='Sala 2', code='S2', capacity=30,
                              unity_id=self.unity.id, category_id=category.id)
            db.session.add_all([sala1, sala2])
            db.session.flush()

            course = Course(name='Curso Teste', code='CT',
                            unity_id=self.unity.id, is_active=True)
            db.session.add(course)
            db.session.commit()
            self.room1_id = sala1.id
            self.room2_id = sala2.id
            self.course_id = course.id
            self.teacher_id = professor.id
            self.unity_id = self.unity.id
            self.dia = date.today() + timedelta(days=1)
            if self.dia.weekday() == 6:  # domingo é bloqueado
                self.dia += timedelta(days=1)

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

    def _payload(self, dia, room_id):
        return {
            'classroom': str(room_id),
            'course': str(self.course_id),
            'subject': '0', 'teacher': str(self.teacher_id),
            'title': 'Aula de teste',
            'description': '',
            'date': dia.strftime('%Y-%m-%d'),
            'start_time': '09:00', 'end_time': '10:00',
        }

    def _criar(self, dia, room_id):
        """Cria pelo formulário e devolve o id (docente fixo, 09:00–10:00)."""
        resposta = self.client.post('/reservations/create',
                                    data=self._payload(dia, room_id),
                                    follow_redirects=True)
        with self.app.app_context():
            reserva = Reservation.query.filter_by(
                date=dia, classroom_id=room_id,
                start_time=datetime.strptime('09:00', '%H:%M').time()
            ).order_by(Reservation.id.desc()).first()
            return resposta, (reserva.id if reserva else None)


class TestTeacherLocksUnit(TeacherLocksTestCase):
    """O lock puro, sem passar pelos fluxos HTTP."""

    def test_serializa_gravacoes_do_mesmo_docente_e_data(self):
        # B tenta entrar com A segurando o lock: fica bloqueado até A sair —
        # é exatamente a janela checagem→gravação que a corrida explorava.
        ordem = []
        a_entrou = threading.Event()
        pode_sair = threading.Event()

        def corpo_a():
            # Contexto por thread (como em requisições reais): o app context
            # não atravessa Thread.start().
            with self.app.app_context(), \
                    teacher_locks([(self.teacher_id, self.dia)]):
                ordem.append('A dentro')
                a_entrou.set()
                pode_sair.wait(timeout=5)
                ordem.append('A saiu')

        def corpo_b():
            a_entrou.wait(timeout=5)
            ordem.append('B tentou')
            with self.app.app_context(), \
                    teacher_locks([(self.teacher_id, self.dia)]):
                ordem.append('B dentro')

        with self.app.app_context():
            a = threading.Thread(target=corpo_a)
            b = threading.Thread(target=corpo_b)
            a.start()
            b.start()
            self.assertTrue(a_entrou.wait(timeout=5))
            # Dá tempo de B chegar ao acquire e BLOQUEAR (se o lock não
            # excluir, B entra antes de A sair e a ordem final falha).
            b.join(timeout=0.2)
            pode_sair.set()
            a.join(timeout=5)
            b.join(timeout=5)
        self.assertEqual(ordem, ['A dentro', 'B tentou', 'A saiu', 'B dentro'])

    def test_datas_diferentes_nao_se_bloqueiam(self):
        ordem = []
        a_entrou = threading.Event()
        pode_sair = threading.Event()
        outro_dia = self.dia + timedelta(days=1)

        def corpo_a():
            with self.app.app_context(), \
                    teacher_locks([(self.teacher_id, self.dia)]):
                ordem.append('A dentro')
                a_entrou.set()
                # Sem timeout (CodeRabbit #243): com timeout, A podia soltar
                # o lock antes do assertFalse e o teste passava mesmo com
                # uma chave que ignorasse a data. O finally abaixo garante
                # o set() mesmo se um assert falhar.
                pode_sair.wait()

        def corpo_b():
            a_entrou.wait(timeout=5)
            with self.app.app_context(), \
                    teacher_locks([(self.teacher_id, outro_dia)]):
                ordem.append('B dentro')

        with self.app.app_context():
            a = threading.Thread(target=corpo_a)
            b = threading.Thread(target=corpo_b)
            a.start()
            b.start()
            try:
                self.assertTrue(a_entrou.wait(timeout=5))
                b.join(timeout=5)   # B entra AINDA COM A segurando o lock
                # B tem de ter TERMINADO antes de A soltar: join(timeout)
                # retorna silencioso no timeout — sem este assert, uma
                # implementação com chave só de docente (ignorando a data)
                # faria B bloquear até A sair e o assert final passaria
                # igual (CodeRabbit #243).
                self.assertFalse(b.is_alive())
                self.assertEqual(ordem, ['A dentro', 'B dentro'])
            finally:
                pode_sair.set()
                a.join(timeout=5)
                b.join(timeout=5)
        self.assertEqual(ordem, ['A dentro', 'B dentro'])

    def test_sem_docente_nao_trava_nada(self):
        with self.app.app_context():
            with teacher_locks([(None, self.dia)]):
                pass
            # Nenhuma chave criada no dicionário de locks.
            self.assertEqual(scheduling._teacher_locks, {})

    def test_docentes_e_datas_em_ordem_canonica(self):
        # Lote com vários pares: as chaves chegam a _travar_chaves na MESMA
        # sequência ordenada, independentemente da ordem de entrada — o
        # contrato anti-deadlock. Registrar a sequência (e não olhar o
        # dicionário do registry, que não prova a ordem de aquisição).
        pares = [(3, date(2026, 12, 3)), (1, date(2026, 12, 1)),
                 (2, date(2026, 12, 2))]
        chamadas = []
        real = scheduling._travar_chaves

        @contextmanager
        def gravadora(keys, tabela_locks, prefixo_advisory):
            chamadas.append((prefixo_advisory, list(keys)))
            with real(keys, tabela_locks, prefixo_advisory):
                yield

        with patch.object(scheduling, '_travar_chaves', gravadora):
            with self.app.app_context():
                with teacher_locks(pares), teacher_locks(list(reversed(pares))):
                    pass
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(chamadas[0][0], 'docente')
        self.assertEqual(chamadas[0][1], sorted(chamadas[0][1]))
        self.assertEqual(chamadas[0], chamadas[1])
        self.assertEqual(
            sorted(scheduling._teacher_locks),
            sorted(scheduling._teacher_key(t, d) for t, d in pares))


class TestSomenteAprovadas(TeacherLocksTestCase):
    """A revalidação da APROVAÇÃO conta só aprovadas: duas pendências
    sobrepostas do mesmo docente se bloqueariam para sempre se contassem
    pendentes (cada aprovação esperaria a outra)."""

    def test_somente_aprovadas_ignora_pendente(self):
        with self.app.app_context():
            u = self.teacher_id
            pendente_a = Reservation(
                user_id=u, classroom_id=self.room1_id, teacher_id=u,
                title='Pendente A', date=self.dia,
                start_time=datetime.strptime('09:00', '%H:%M').time(),
                end_time=datetime.strptime('10:00', '%H:%M').time(),
                status='pending', unity_id=self.unity_id)
            pendente_b = Reservation(
                user_id=u, classroom_id=self.room2_id, teacher_id=u,
                title='Pendente B', date=self.dia,
                start_time=datetime.strptime('09:00', '%H:%M').time(),
                end_time=datetime.strptime('10:00', '%H:%M').time(),
                status='pending', unity_id=self.unity_id)
            db.session.add_all([pendente_a, pendente_b])
            db.session.commit()
            _id_a, id_b = pendente_a.id, pendente_b.id

        with self.app.app_context():
            # Padrão (criação/edição): pendente também sinaliza conflito.
            self.assertIsNotNone(check_teacher_conflict(
                self.teacher_id, self.dia,
                datetime.strptime('09:00', '%H:%M').time(),
                datetime.strptime('10:00', '%H:%M').time(),
                exclude_id=id_b))
            # Revalidação de aprovação: só aprovadas — a pendente irmã não
            # bloqueia.
            self.assertIsNone(check_teacher_conflict(
                self.teacher_id, self.dia,
                datetime.strptime('09:00', '%H:%M').time(),
                datetime.strptime('10:00', '%H:%M').time(),
                exclude_id=id_b, somente_aprovadas=True))


class TestAprovacaoRevalidaDocente(TeacherLocksTestCase):
    """Aprovar revalida o docente dentro do lock: outra reserva do docente
    que foi APROVADA na janela enquanto esta pendia (em outra sala) impede a
    aprovação — sem isso, duas aprovações concorrentes materializavam a
    sobreposição que o slot lock (sala) não enxergava. E, se a reserva foi
    EDITADA enquanto a aprovação estava a caminho (docente/sala/data mudaram
    entre o load e o lock), a aprovação ABORTA: aprovar com chave velha
    materializaria sobreposição que a checagem do docente novo nunca viu."""
    """Aprovar revalida o docente dentro do lock: outra reserva do docente
    que foi APROVADA na janela enquanto esta pendia (em outra sala) impede a
    aprovação — sem isso, duas aprovações concorrentes materializavam a
    sobreposição que o slot lock (sala) não enxergava."""

    def test_aprovacao_recusa_docente_sobreposto_e_depois_passa(self):
        dia = self.dia
        _, id_a = self._criar(dia, self.room1_id)   # nasce aprovada
        _, id_b = self._criar(dia, self.room2_id)   # nasce PENDENTE: docente
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, id_a).status, 'approved')
            self.assertEqual(db.session.get(Reservation, id_b).status, 'pending')

        # Aprovar B: o docente tem A aprovada na mesma janela (outra sala) —
        # recusa e a pendência permanece.
        resposta = self.client.post(f'/reservations/{id_b}/approve',
                                    follow_redirects=True)
        self.assertIn('docente', resposta.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, id_b).status, 'pending')

        # Cancelada a aprovada, a aprovação passa (o gestor criou A: é dono).
        self.client.post(f'/reservations/{id_a}/cancel', follow_redirects=True)
        self.client.post(f'/reservations/{id_b}/approve', follow_redirects=True)
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, id_b).status, 'approved')

    @patch('app.blueprints.reservations.slot_locks')
    def test_aprovacao_aborta_se_a_reserva_foi_editada_sob_o_lock(self, mock_slot):
        # Race edit↔approve: a aprovação escolhe as chaves de lock no LOAD;
        # uma edição concorrente troca o docente antes do lock. Reler sob o
        # lock mostra a mudança e a aprovação ABORTA — aprovar com a chave
        # velha aprovaria o docente NOVO sem a checagem dele (o sugerido de
        # travar chaves antigas na edição não fecha: dois approves com
        # chaves diferentes não serializam entre si).
        from contextlib import contextmanager
        from sqlalchemy import text as sql_text
        from app.models import User as UserModel
        real_slot_locks = scheduling.slot_locks

        with self.app.app_context():
            unity = db.session.get(Unity, self.unity_id)
            professor2 = UserModel(
                email='professor2@escola.edu', full_name='Professor Costa',
                role='room', profile_type='teacher', unities=[unity],
                force_password_change=False, is_active_user=True)
            professor2.set_password(PASSWORD)
            db.session.add(professor2)
            db.session.commit()
            teacher2_id = professor2.id

        dia = self.dia
        _, id_a = self._criar(dia, self.room1_id)   # nasce aprovada
        _, id_b = self._criar(dia, self.room2_id)   # nasce PENDENTE: docente

        @contextmanager
        def com_edicao_concorrente(classroom_id, dates):
            with real_slot_locks(classroom_id, dates):
                # A troca de docente aparece SOB o lock do approve — mas SEM
                # commit: um commit expiraria os atributos do identity map
                # (a leitura seguinte recarregaria mesmo sem refresh, e o
                # teste deixaria de cobrir o refresh). Sem commit, o UPDATE
                # é visível na MESMA conexão e o identity map segue com os
                # valores obsoletos do load — o único caminho para o gate
                # enxergar a mudança é o db.session.refresh do route.
                db.session.execute(
                    sql_text('UPDATE reservations SET teacher_id = :t '
                             'WHERE id = :i'),
                    {'t': teacher2_id, 'i': id_b})
                yield

        mock_slot.side_effect = com_edicao_concorrente
        resposta = self.client.post(f'/reservations/{id_b}/approve',
                                    follow_redirects=True)
        self.assertIn('editada durante a aprovação',
                      resposta.get_data(as_text=True))
        # O abort não comita: o UPDATE simulado rollbacka com a requisição —
        # a pendência segue com o docente original, intacta.
        with self.app.app_context():
            reserva = db.session.get(Reservation, id_b)
            self.assertEqual(reserva.status, 'pending')   # não aprovou
            self.assertEqual(reserva.teacher_id, self.teacher_id)

        # Retry com o estado consolidado: a checagem de docente (só
        # aprovadas) recusa enquanto A segue aprovada sobreposta; cancelada
        # A, a aprovação passa.
        mock_slot.side_effect = None
        self.client.post(f'/reservations/{id_b}/approve', follow_redirects=True)
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, id_b).status,
                             'pending')
        self.client.post(f'/reservations/{id_a}/cancel', follow_redirects=True)
        self.client.post(f'/reservations/{id_b}/approve', follow_redirects=True)
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, id_b).status,
                             'approved')

    @patch('app.blueprints.reservations.slot_locks')
    def test_aprovacao_aborta_se_reserva_foi_cancelada_sob_o_lock(self, mock_slot):
        # O gate de pendência roda ANTES do lock — um cancelamento que
        # acontece nesse intervalo faria o approve ressuscitar uma reserva
        # cancelada. A rechecagem de status dentro da seção crítica fecha o
        # buraco (mesma família do abort por edição).
        from contextlib import contextmanager
        from sqlalchemy import text as sql_text
        real_slot_locks = scheduling.slot_locks

        dia = self.dia
        _, id_a = self._criar(dia, self.room1_id)   # nasce aprovada
        _, id_b = self._criar(dia, self.room2_id)   # nasce PENDENTE: docente

        @contextmanager
        def com_cancelamento_concorrente(classroom_id, dates):
            with real_slot_locks(classroom_id, dates):
                # Sem commit, pelo mesmo motivo do teste de edição: o
                # identity map precisa seguir obsoleto para o refresh ser
                # o único caminho de o gate enxergar a mudança.
                db.session.execute(
                    sql_text("UPDATE reservations SET status = 'cancelled' "
                             'WHERE id = :i'),
                    {'i': id_b})
                yield

        mock_slot.side_effect = com_cancelamento_concorrente
        resposta = self.client.post(f'/reservations/{id_b}/approve',
                                    follow_redirects=True)
        self.assertIn('mudou de situação', resposta.get_data(as_text=True))
        # Rollback com a requisição: a pendência volta ao estado anterior.
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, id_b).status,
                             'pending')

    @patch('app.blueprints.reservations.slot_locks')
    def test_aprovacao_valida_horario_mudado_sob_o_lock(self, mock_slot):
        # Edição que muda SÓ o horário ANTES da re-leitura: sala/docente/data
        # ficam iguais e a checagem de chaves travadas passa — a re-leitura
        # enxerga o horário novo e VALIDA a janela dele (10:00-11:00, sem
        # conflito), e o approve prossegue. O UPDATE é TYPED (Core, com
        # objetos time): texto cru '10:00' difere do binding
        # '10:00:00.000000' e faria o CAS falhar por FORMATO, não por
        # mudança (CodeRabbit #243). Mudança ENTRE re-leitura e CAS é o
        # teste seguinte.
        from contextlib import contextmanager
        from datetime import time as time_cls
        from sqlalchemy import update
        real_slot_locks = scheduling.slot_locks

        dia = self.dia
        _, id_a = self._criar(dia, self.room1_id)   # nasce aprovada
        _, id_b = self._criar(dia, self.room2_id)   # nasce PENDENTE: docente

        @contextmanager
        def com_ajuste_de_horario(classroom_id, datas):
            with real_slot_locks(classroom_id, datas):
                # Sem commit: o approve comita o flip junto com o horário
                # novo na MESMA transação — o re-read (populate_existing)
                # enxerga o update desta mesma conexão.
                db.session.execute(
                    update(Reservation).where(Reservation.id == id_b)
                    .values(start_time=time_cls(10, 0), end_time=time_cls(11, 0)))
                yield

        mock_slot.side_effect = com_ajuste_de_horario
        resposta = self.client.post(f'/reservations/{id_b}/approve',
                                    follow_redirects=True)
        self.assertIn('Reserva aprovada.', resposta.get_data(as_text=True))
        with self.app.app_context():
            reserva = db.session.get(Reservation, id_b)
            self.assertEqual(reserva.status, 'approved')  # CAS casou 10:00==10:00
            self.assertEqual(reserva.start_time.strftime('%H:%M'), '10:00')

    @patch('app.blueprints.reservations.check_teacher_conflict')
    def test_aprovacao_aborta_se_horario_mudar_entre_releitura_e_cas(self, mock_check):
        # Ordem REVERSA da janela (a do teste anterior muda antes da
        # re-leitura): a mudança entra ENTRE a re-leitura com row lock e o
        # CAS — interceptada na checagem de docente, que roda nesse exato
        # intervalo. O CAS condicionado aos horários é o que pega.
        from sqlalchemy import text as sql_text
        real_check = scheduling.check_teacher_conflict

        dia = self.dia
        # O patch cobre o CREATE também (CodeRabbit #243): sem delegar ao
        # real, o MagicMock fazia AMBAS nascerem pendentes e o cancelamento
        # abaixo cancelava uma pendente — o cenário declarado (cancelar a
        # APROVADA) nunca existiu. Delega durante a criação e confere os
        # status dos fixtures:
        mock_check.side_effect = real_check
        _, id_a = self._criar(dia, self.room1_id)   # nasce aprovada
        _, id_b = self._criar(dia, self.room2_id)   # nasce PENDENTE: docente
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, id_a).status, 'approved')
            self.assertEqual(db.session.get(Reservation, id_b).status, 'pending')
        # Cancelada a aprovada: sem conflito de docente, a checagem passa e
        # o fluxo CHEGA ao CAS — o gate de docente não pode mascarar o ramo
        # rowcount=0 que este teste exercita.
        self.client.post(f'/reservations/{id_a}/cancel', follow_redirects=True)

        def check_com_mudanca_no_meio(*args, **kwargs):
            resultado = real_check(*args, **kwargs)
            # A edição comita a mudança de horário DEPOIS da re-leitura e
            # ANTES do CAS (sem commit: visível na mesma conexão, invisível
            # ao identity map).
            db.session.execute(
                sql_text("UPDATE reservations SET start_time = '10:00', "
                         "end_time = '11:00' WHERE id = :i"),
                {'i': id_b})
            return resultado

        mock_check.side_effect = check_com_mudanca_no_meio
        resposta = self.client.post(f'/reservations/{id_b}/approve',
                                    follow_redirects=True)
        self.assertIn('editada ou cancelada durante a aprovação',
                      resposta.get_data(as_text=True))
        with self.app.app_context():
            self.assertEqual(db.session.get(Reservation, id_b).status,
                             'pending')

    @patch('app.blueprints.reservations.check_teacher_conflict')
    def test_edicao_de_serie_aborta_se_horario_mudar_entre_releitura_e_cas(self, mock_check):
        # CAS do lote da série (CodeRabbit #243, follow-up): os horários
        # LIDOS entram no WHERE — um edit concorrente que COMMITA horário de
        # um membro entre a re-leitura e a escrita do lote não pode ser
        # sobrescrito em silêncio (o SQLite ignora o FOR UPDATE e as travas
        # de thread não cruzam processos).
        # A edição concorrente é OUTRO PROCESSO (follow-up do #243): grava e
        # commita numa conexão própria — o commit dele não é desfeito pelo
        # rollback da requisição, como seria um UPDATE na mesma sessão.
        real_check = scheduling.check_teacher_conflict

        dia = self.dia
        # O patch cobre o CREATE também: delega ao real durante a criação.
        mock_check.side_effect = real_check
        _, id_b = self._criar(dia, self.room1_id)   # nasce aprovada
        with self.app.app_context():
            reserva = db.session.get(Reservation, id_b)
            reserva.repeat_group_id = id_b    # série de um único membro
            db.session.commit()
            self.assertEqual(reserva.status, 'approved')

        def com_edicao_concorrente(*args, **kwargs):
            # Roda no intervalo re-leitura→CAS do lote (a checagem de docente
            # fica exatamente aí) e só devolve depois do commit do outro
            # processo — o sincronismo é determinístico, sem sleep.
            processo = subprocess.run(
                [sys.executable, '-c', _EDICAO_CONCURRENTE,
                 TestConfig.SQLALCHEMY_DATABASE_URI, str(id_b)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(processo.returncode, 0, processo.stderr)
            return real_check(*args, **kwargs)

        mock_check.side_effect = com_edicao_concorrente
        # Horários em branco: o lote regrava os horários LIDOS (09:00–10:00,
        # já velhos) junto com o título novo.
        resposta = self.client.post(f'/reservations/{id_b}/series/edit',
                                    data={'selected': [str(id_b)],
                                          'title': 'Título do lote'},
                                    follow_redirects=True)
        self.assertIn('editadas durante a alteração',
                      resposta.get_data(as_text=True))
        with self.app.app_context():
            reserva = db.session.get(Reservation, id_b)
            # O que o outro processo commitou prevalece — o lote não gravou
            # nada (nem o horário velho, nem o título).
            self.assertEqual(reserva.start_time.strftime('%H:%M'), '10:00')
            self.assertEqual(reserva.end_time.strftime('%H:%M'), '11:00')
            self.assertEqual(reserva.status, 'approved')   # CAS rowcount 0
            self.assertEqual(reserva.title, 'Aula de teste')


class TestAbortosSoltamAsTravas(TeacherLocksTestCase):
    """Todo aborto DENTRO de um bloco de travas solta o que segurava antes de
    montar a resposta (rodada do OCR no #243). Até o teardown, o FOR UPDATE
    das re-leituras e os advisory locks transacionais do PostgreSQL ficavam
    retidos nos abortos, bloqueando edits/aproves concorrentes nas mesmas
    chaves; e no edit o `return render_template(...)` era avaliado com o
    stack ainda aberto (o finally só roda DEPOIS do return), retendo os
    RLocks de processo durante o template inteiro.

    O SQLite dos testes ignora o FOR UPDATE e não tem advisory lock: o
    contrato é observado pela chamada de rollback dentro do pedido e pela
    posse dos RLocks no instante da renderização."""

    def _contando_rollbacks(self):
        """Registra as chamadas a Session.rollback. O teardown fecha a sessão
        por remove(), sem passar por rollback() — o que é contado aqui
        aconteceu dentro do tratamento do pedido."""
        from sqlalchemy.orm import Session
        return patch.object(Session, 'rollback', autospec=True,
                            side_effect=Session.rollback)

    def _renderizando(self, pedido):
        """Roda `pedido()` com o render_template das rotas de reserva
        trocado por um espião e devolve (resposta, posse). Cada item de
        `posse` diz se algum RLock de sala/docente pertencia à thread naquele
        instante — RLock é reentrante na própria thread, então readquirir não
        prova nada; a posse é que importa."""
        from app.blueprints import reservations as rotas
        render_real = rotas.render_template
        posse = []

        def render_espiao(*args, **kwargs):
            posse.append(any(trava._is_owned() for trava in (
                list(scheduling._slot_locks.values())
                + list(scheduling._teacher_locks.values()))))
            return render_real(*args, **kwargs)

        with patch('app.blueprints.reservations.render_template',
                   side_effect=render_espiao):
            resposta = pedido()
        return resposta, posse

    def test_aborto_do_edit_renderiza_depois_de_soltar_as_travas(self):
        dia = self.dia
        self._criar(dia, self.room1_id)                       # aprovada
        _, id_b = self._criar(dia, self.room2_id)             # PENDENTE
        resposta, posse = self._renderizando(lambda: self.client.post(
            f'/reservations/{id_b}/edit',
            data=self._payload(dia, self.room1_id),
            follow_redirects=True))
        self.assertIn('Conflito de sala', resposta.get_data(as_text=True))
        self.assertEqual(posse, [False])   # uma renderização, sem trava alguma

    @patch('app.blueprints.reservations.slot_locks')
    def test_aborto_do_approve_faz_rollback_antes_do_redirect(self, mock_slot):
        from sqlalchemy import text as sql_text
        real_slot_locks = scheduling.slot_locks
        dia = self.dia
        self._criar(dia, self.room1_id)                       # aprovada
        _, id_b = self._criar(dia, self.room2_id)             # PENDENTE

        @contextmanager
        def com_cancelamento_concorrente(classroom_id, dates):
            with real_slot_locks(classroom_id, dates):
                db.session.execute(
                    sql_text("UPDATE reservations SET status = 'cancelled' "
                             'WHERE id = :i'), {'i': id_b})
                yield

        mock_slot.side_effect = com_cancelamento_concorrente
        with self._contando_rollbacks() as rollback:
            resposta = self.client.post(f'/reservations/{id_b}/approve',
                                        follow_redirects=True)
        self.assertIn('mudou de situação', resposta.get_data(as_text=True))
        self.assertGreaterEqual(rollback.call_count, 1)

    @patch('app.blueprints.reservations.slot_locks')
    def test_aborto_do_lote_da_serie_faz_rollback_antes_do_redirect(self, mock_slot):
        from sqlalchemy import text as sql_text
        real_slot_locks = scheduling.slot_locks
        dia = self.dia
        _, id_b = self._criar(dia, self.room1_id)             # aprovada
        with self.app.app_context():
            db.session.get(Reservation, id_b).repeat_group_id = id_b
            db.session.commit()

        @contextmanager
        def com_cancelamento_concorrente(classroom_id, dates):
            with real_slot_locks(classroom_id, dates):
                db.session.execute(
                    sql_text("UPDATE reservations SET status = 'cancelled' "
                             'WHERE id = :i'), {'i': id_b})
                yield

        mock_slot.side_effect = com_cancelamento_concorrente
        with self._contando_rollbacks() as rollback:
            resposta = self.client.post(
                f'/reservations/{id_b}/series/edit',
                data={'selected': [str(id_b)], 'title': 'Título do lote'},
                follow_redirects=True)
        self.assertIn('editadas ou canceladas', resposta.get_data(as_text=True))
        self.assertGreaterEqual(rollback.call_count, 1)
        with self.app.app_context():
            # O rollback do aborto desfaz a escrita da "concorrência".
            self.assertEqual(db.session.get(Reservation, id_b).status,
                             'approved')

    def test_aborto_do_create_solta_as_travas_antes_de_renderizar(self):
        # Mesmo contrato do edit: o create renderiza o formulário de novo no
        # aborto — o rollback solta os locks do banco e o fechamento do stack
        # os RLocks de processo, ambos antes do template.
        dia = self.dia
        self._criar(dia, self.room1_id)          # aprovada: ocupa a janela
        with self._contando_rollbacks() as rollback:
            resposta, posse = self._renderizando(lambda: self.client.post(
                '/reservations/create', data=self._payload(dia, self.room1_id),
                follow_redirects=True))
        self.assertIn('Conflito de sala', resposta.get_data(as_text=True))
        self.assertGreaterEqual(rollback.call_count, 1)
        self.assertEqual(posse, [False])

    def test_aborto_da_repeticao_unica_faz_rollback_antes_do_redirect(self):
        dia = self.dia
        _, id_a = self._criar(dia, self.room1_id)
        domingo = dia + timedelta(days=(6 - dia.weekday()) % 7)
        with self._contando_rollbacks() as rollback:
            resposta = self.client.post(
                f'/reservations/{id_a}/repeat_schedule',
                data={'new_date': domingo.isoformat(),
                      'end_date': domingo.isoformat(),
                      'same_day': 'true', 'skip_weekend': 'false'},
                follow_redirects=True)
        self.assertIn('domingos', resposta.get_data(as_text=True))
        self.assertGreaterEqual(rollback.call_count, 1)


if __name__ == '__main__':
    unittest.main()
