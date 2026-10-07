"""Testes do Relatório de Salas e Reservas (/relatorios):
período padrão (mês corrente) e por start/end, KPIs e tabelas por status,
sala, curso e docente, acesso restrito a reservation:read_all e botões de
atalho nas páginas de Salas e Todas as Reservas.
"""
import os
import calendar
import tempfile
import unittest
from datetime import date, time

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Classroom, Course, Permission, Reservation, Role,
                        RoomCategory, Unity, User)

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class RelatorioSalasReservasTestCase(unittest.TestCase):
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

            perm = Permission(code='reservation:read_all', module='reservation',
                              action='read_all')
            db.session.add(perm)
            role = Role(name='gestor-teste', label='Gestor Teste', permissions=[perm])
            db.session.add(role)
            db.session.flush()

            self.gestor = User(
                email=EMAIL, full_name='Gestor Teste', role='room',
                profile_type='employee', unities=[self.unity],
                role_id=role.id, force_password_change=False, is_active_user=True,
            )
            self.gestor.set_password(PASSWORD)
            db.session.add(self.gestor)
            db.session.flush()

            # Docente sem permissões: o relatório deve ser barrado (403)
            self.prof = User(email='ana@escola.edu', full_name='Ana Souza',
                             role='room', profile_type='teacher',
                             unities=[self.unity], is_active_user=True,
                             force_password_change=False)
            self.prof.set_password(PASSWORD)
            db.session.add(self.prof)
            db.session.flush()

            category = RoomCategory(name='Sala de Aula', code='SA')
            db.session.add(category)
            db.session.flush()
            self.sala_s1 = Classroom(name='Sala 1', code='S1', capacity=30,
                                     unity_id=self.unity.id, category_id=category.id)
            self.sala_s2 = Classroom(name='Sala 2', code='S2', capacity=30,
                                     unity_id=self.unity.id, category_id=category.id)
            db.session.add_all([self.sala_s1, self.sala_s2])
            db.session.flush()

            self.curso = Course(name='Curso A', code='CA1', unity_id=self.unity.id)
            db.session.add(self.curso)
            db.session.flush()

            hoje = date.today()
            mes_que_vem = date(hoje.year, hoje.month % 12 + 1, 1)

            # Mês corrente: 2 aprovadas na S1 (2h no total, 1 com curso/docente),
            # 1 pendente e 1 cancelada na S2
            self._criar_reserva(self.sala_s1, 'Aula S1', hoje, time(8, 0),
                                time(9, 0), teacher=self.prof, course_id=self.curso.id)
            self._criar_reserva(self.sala_s1, 'Aula S1 depois', hoje, time(14, 0),
                                time(15, 0))
            self._criar_reserva(self.sala_s2, 'Pendente S2', hoje, time(19, 0),
                                time(21, 0), status='pending')
            self._criar_reserva(self.sala_s2, 'Cancelada S2', hoje, time(10, 0),
                                time(11, 0), status='cancelled')
            # Fora do padrão (mês que vem): só entra com start/end explícitos
            self._criar_reserva(self.sala_s1, 'Futura', mes_que_vem, time(8, 0),
                                time(9, 0))

            # ids fixados dentro do contexto (objetos ficam detached depois)
            self.ids = {'sala_s1': self.sala_s1.id, 'sala_s2': self.sala_s2.id}

        self._login()

    def _criar_reserva(self, room, title, when, inicio, fim, status='approved',
                       teacher=None, course_id=None):
        reservation = Reservation(
            user_id=self.gestor.id, classroom_id=room.id, unity_id=self.unity.id,
            title=title, date=when, start_time=inicio, end_time=fim,
            status=status, teacher_id=teacher.id if teacher else None,
            course_id=course_id,
        )
        db.session.add(reservation)
        db.session.commit()
        return reservation.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def _login(self, email=EMAIL, password=PASSWORD):
        response = self.client.post('/login',
                                    data={'email': email, 'password': password},
                                    follow_redirects=True)
        self.assertEqual(response.status_code, 200)

    def _hoje_e_fim_do_mes(self):
        hoje = date.today()
        fim = date(hoje.year, hoje.month, calendar.monthrange(hoje.year, hoje.month)[1])
        return hoje, fim

    # ---------- acesso ----------

    def test_exige_permissao_read_all(self):
        self.client.get('/logout')
        self._login('ana@escola.edu', PASSWORD)
        self.assertEqual(self.client.get('/relatorios/geral').status_code, 403)
        self.assertEqual(
            self.client.get('/relatorios/personalizado').status_code, 403)

    def test_url_antiga_do_relatorio_redireciona(self):
        response = self.client.get('/reservations/relatorio?start=2026-01-01')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/relatorios', response.headers['Location'])
        # Seguindo o redirect, o Relatório Geral responde normalmente
        page = self.client.get(
            '/reservations/relatorio', follow_redirects=True).get_data(as_text=True)
        self.assertIn('Relatório Geral de Salas e Reservas', page)

    def test_gestor_acessa_e_pagina_renderiza(self):
        response = self.client.get('/relatorios/geral')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn('Relatório Geral de Salas e Reservas', page)
        self.assertIn('Imprimir / PDF', page)

    # ---------- período e conteúdo ----------

    def test_padrao_mes_corrente_exclui_mes_que_vem(self):
        page = self.client.get('/relatorios/geral').get_data(as_text=True)
        # Duas aprovadas de 1h no mês corrente: KPI de horas mostra 2h
        self.assertIn('>2h<', page)
        self.assertIn('Reservas aprovadas', page)
        self.assertIn('Horas reservadas', page)
        self.assertIn('Ocupação por sala', page)
        self.assertIn('Sala 1', page)
        self.assertIn('Curso A', page)
        self.assertIn('Ana Souza', page)
        # Reservas sem curso/docente ganham linha própria identificada
        self.assertIn('Sem curso vinculado', page)
        self.assertIn('Sem docente vinculado', page)
        # Quadro Professores e cursos vem com as duas abas do período
        self.assertIn('Professores por curso', page)
        self.assertIn('Cursos por professor', page)
        self.assertNotIn(
            'Nenhuma reserva aprovada no período tem professor e curso', page)
        # A reserva do mês que vem não entra no período padrão
        _, fim = self._hoje_e_fim_do_mes()
        self.assertIn(f'value="{fim.isoformat()}"', page)

    def test_periodo_explicito_inclui_mes_que_vem(self):
        hoje = date.today()
        if hoje.month == 12:
            mes_que_vem = date(hoje.year + 1, 1, 1)
        else:
            mes_que_vem = date(hoje.year, hoje.month + 1, 1)
        fim = date(mes_que_vem.year, mes_que_vem.month,
                   calendar.monthrange(mes_que_vem.year, mes_que_vem.month)[1])
        page = self.client.get(
            f'/relatorios/geral?start={hoje.isoformat()}'
            f'&end={fim.isoformat()}').get_data(as_text=True)
        # Com a reserva futura, o KPI de horas sobe de 2h para 3h
        self.assertIn('>3h<', page)

    def test_datas_invalidas_cai_no_padrao(self):
        # Datas inválidas voltam ao mês corrente (padrão), sem erro
        page = self.client.get(
            '/relatorios/geral?start=banana&end=42').get_data(as_text=True)
        _, fim = self._hoje_e_fim_do_mes()
        self.assertIn(f'value="{fim.isoformat()}"', page)

    def test_periodo_sem_reservas_mostra_estado_vazio(self):
        page = self.client.get(
            '/relatorios/geral?start=2020-01-01&end=2020-01-31'
        ).get_data(as_text=True)
        self.assertIn('Nenhuma reserva no período', page)

    def test_periodo_so_com_pendentes_avisa_sobre_aprovadas(self):
        # Período isolado com apenas uma pendente: o relatório renderiza o
        # gráfico de status e avisa que não há aprovadas no intervalo
        with self.app.app_context():
            unity = Unity.query.filter_by(code='UT').first()
            sala = Classroom.query.filter_by(code='S2', unity_id=unity.id).first()
            gestor = User.query.filter_by(email=EMAIL).first()
            db.session.add(Reservation(
                user_id=gestor.id, classroom_id=sala.id, unity_id=unity.id,
                title='So Pendente', date=date(2020, 2, 10),
                start_time=time(22, 0), end_time=time(23, 0), status='pending'))
            db.session.commit()

        page = self.client.get(
            '/relatorios/geral?start=2020-02-01&end=2020-02-28'
        ).get_data(as_text=True)
        self.assertIn('Nenhuma reserva <strong>aprovada</strong> no período', page)
        self.assertIn('Reservas por status', page)

    # ---------- professores por curso ----------

    def _quadro_professores_curso(self, page):
        """Trecho da página do quadro Professores por curso (até o rodapé)."""
        inicio = page.find('Professores por curso')
        self.assertNotEqual(inicio, -1, 'Quadro Professores por curso ausente')
        return page[inicio:]

    def test_quadro_agrupa_docentes_por_curso_com_participacao(self):
        # Docente sem curso não entra no quadro; curso sem docente vira
        # linha de restos dentro do grupo do curso
        with self.app.app_context():
            unity = Unity.query.filter_by(code='UT').first()
            sala = Classroom.query.filter_by(code='S1', unity_id=unity.id).first()
            gestor = User.query.filter_by(email=EMAIL).first()
            ana = User.query.filter_by(email='ana@escola.edu').first()
            curso = Course.query.filter_by(code='CA1', unity_id=unity.id).first()
            db.session.add(Reservation(
                user_id=gestor.id, classroom_id=sala.id, unity_id=unity.id,
                title='Docente Sem Curso', date=date.today(), start_time=time(9, 0),
                end_time=time(10, 0), status='approved', teacher_id=ana.id))
            db.session.add(Reservation(
                user_id=gestor.id, classroom_id=sala.id, unity_id=unity.id,
                title='Curso Sem Docente', date=date.today(), start_time=time(11, 0),
                end_time=time(12, 0), status='approved', course_id=curso.id))
            db.session.commit()

        page = self.client.get('/relatorios/geral').get_data(as_text=True)
        quadro = self._quadro_professores_curso(page)
        # Aba "por curso": o grupo do curso soma as 2h aprovadas dele
        # (1h da Ana + 1h sem docente)
        self.assertIn('Curso A', quadro)
        self.assertIn('>2h<', quadro)
        self.assertIn('Sem docente vinculado', quadro)
        # Aba "por professor": a carga da Ana soma 2h (1h no Curso A +
        # 1h sem curso), com o resto como linha identificada
        self.assertIn('Sem curso vinculado', quadro)
        # A Ana aparece nas duas abas: linha do curso e grupo próprio
        self.assertEqual(quadro.count('Ana Souza'), 2)

    def test_quadro_vazio_exibe_nota_explicativa(self):
        # Aprovada sem docente e sem curso: quadro existe, mas sem grupos
        with self.app.app_context():
            unity = Unity.query.filter_by(code='UT').first()
            sala = Classroom.query.filter_by(code='S1', unity_id=unity.id).first()
            gestor = User.query.filter_by(email=EMAIL).first()
            db.session.add(Reservation(
                user_id=gestor.id, classroom_id=sala.id, unity_id=unity.id,
                title='Sem Vínculos', date=date(2020, 3, 5), start_time=time(8, 0),
                end_time=time(9, 0), status='approved'))
            db.session.commit()

        page = self.client.get(
            '/relatorios/geral?start=2020-03-01&end=2020-03-31'
        ).get_data(as_text=True)
        self._quadro_professores_curso(page)
        self.assertIn(
            'Nenhuma reserva aprovada no período tem professor e curso', page)

    # ---------- relatório personalizado ----------

    def test_personalizado_renderiza_formulario_e_dados(self):
        page = self.client.get('/relatorios/personalizado').get_data(as_text=True)
        self.assertIn('Relatório Personalizado', page)
        self.assertIn('Gerar Relatório', page)
        self.assertIn('Agrupar por', page)
        self.assertIn('Buscar no título', page)
        # Padrão (mês corrente) inclui todos os status
        self.assertIn('Aula S1', page)
        self.assertIn('Pendente S2', page)
        self.assertIn('Cancelada S2', page)

    def test_personalizado_filtro_status(self):
        page = self.client.get(
            '/relatorios/personalizado?status_approved=1').get_data(as_text=True)
        self.assertIn('Aula S1', page)
        self.assertNotIn('Pendente S2', page)
        self.assertNotIn('Cancelada S2', page)

    def test_personalizado_filtro_sala(self):
        page = self.client.get(
            f"/relatorios/personalizado?room_id={self.ids['sala_s2']}"
        ).get_data(as_text=True)
        self.assertIn('Pendente S2', page)
        self.assertIn('Cancelada S2', page)
        self.assertNotIn('Aula S1', page)

    def test_personalizado_busca_no_titulo(self):
        page = self.client.get(
            '/relatorios/personalizado?texto=Pendente').get_data(as_text=True)
        self.assertIn('Pendente S2', page)
        self.assertNotIn('Aula S1', page)
        self.assertNotIn('Cancelada S2', page)

    def test_personalizado_agrupamento_por_professor(self):
        page = self.client.get(
            '/relatorios/personalizado?agrupar=professor'
        ).get_data(as_text=True)
        # Faixa do docente do período e grupo das reservas sem professor
        self.assertIn('Ana Souza', page)
        self.assertIn('Sem professor', page)
        # Datas não são mais faixas: os títulos continuam como linhas
        self.assertIn('Aula S1', page)

    def test_personalizado_periodo_sem_reservas(self):
        page = self.client.get(
            '/relatorios/personalizado?start=2020-01-01&end=2020-01-31'
        ).get_data(as_text=True)
        self.assertIn('Nenhuma reserva com esses filtros', page)

    def test_personalizado_agrupado_por_data_ordena_cronologicamente(self):
        # Duas datas isoladas: a faixa de 10/02 vem antes da de 20/02 no
        # padrão crescente, e troca de lugar com a ordem decrescente
        with self.app.app_context():
            unity = Unity.query.filter_by(code='UT').first()
            sala = Classroom.query.filter_by(code='S1', unity_id=unity.id).first()
            gestor = User.query.filter_by(email=EMAIL).first()
            db.session.add(Reservation(
                user_id=gestor.id, classroom_id=sala.id, unity_id=unity.id,
                title='Dia 10', date=date(2020, 2, 10), start_time=time(8, 0),
                end_time=time(9, 0), status='approved'))
            db.session.add(Reservation(
                user_id=gestor.id, classroom_id=sala.id, unity_id=unity.id,
                title='Dia 20', date=date(2020, 2, 20), start_time=time(8, 0),
                end_time=time(9, 0), status='approved'))
            db.session.commit()

        page = self.client.get(
            '/relatorios/personalizado?start=2020-02-01&end=2020-02-28'
        ).get_data(as_text=True)
        self.assertLess(page.find('10/02/2020'), page.find('20/02/2020'))
        page = self.client.get(
            '/relatorios/personalizado?start=2020-02-01&end=2020-02-28&ordem=desc'
        ).get_data(as_text=True)
        self.assertGreater(page.find('10/02/2020'), page.find('20/02/2020'))

    # ---------- atalhos nas páginas ----------

    def test_botao_relatorio_aparece_para_gestor(self):
        page = self.client.get('/reservations/all').get_data(as_text=True)
        self.assertIn('/relatorios', page)
        page = self.client.get('/classrooms/').get_data(as_text=True)
        self.assertIn('/relatorios', page)

    def test_botao_relatorio_nao_aparece_sem_permissao(self):
        self.client.get('/logout')
        self._login('ana@escola.edu', PASSWORD)
        page = self.client.get('/classrooms/').get_data(as_text=True)
        self.assertNotIn('/relatorios', page)


if __name__ == '__main__':
    unittest.main()
