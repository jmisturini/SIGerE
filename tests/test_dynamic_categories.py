"""Testes da gestão dinâmica de categorias de espaços.

Garante que totem e dashboard se montam a partir das categorias cadastradas
(banco de dados) e não de códigos fixos: uma categoria nova (ex: Quadra de
Esportes) precisa aparecer nas telas apenas com o cadastro — sem alteração
de código —, com a aparência (cor/ícone) e a janela de tempo (período atual
ou próximos 7 dias) definidos nela mesma.

A suíte sobe a aplicação real (create_app) com banco SQLite temporário,
seguindo o padrão de test_change_password.py.
"""
import os
import tempfile
import unittest
from datetime import date, time, timedelta

from werkzeug.datastructures import MultiDict

from app import create_app
from app.config import Config
from app.extensions import db
from app.forms import RoomCategoryForm
from app.models import Classroom, Reservation, RoomCategory, Unity, User


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class DynamicCategoriesTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')

        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            unity = Unity(name='Unidade Centro', code='CTR')
            db.session.add(unity)
            db.session.flush()
            self.unity_id = unity.id

            # Categoria customizada, como a quadra: nasce direto no cadastro,
            # sem nenhum código de tela conhecendo o seu identificador.
            self.quadra = RoomCategory(name='Quadra de Esportes', code='sports_court',
                                       color='#198754', icon='bi-volleyball')
            self.sem_estilo = RoomCategory(name='Biblioteca', code='library')
            db.session.add_all([self.quadra, self.sem_estilo])
            db.session.flush()

            self.quadra_room = Classroom(name='Quadra Poliesportiva', code='QE001',
                                         capacity=100, category_id=self.quadra.id,
                                         unity_id=unity.id)
            biblio_room = Classroom(name='Biblioteca', code='BI001', capacity=40,
                                    category_id=self.sem_estilo.id, unity_id=unity.id)
            db.session.add_all([self.quadra_room, biblio_room])
            db.session.flush()

            user = User(username='prof.teste', email='prof.teste@escola.edu',
                        full_name='Professor Teste', unity_id=unity.id,
                        force_password_change=False, is_active_user=True)
            user.set_password('SenhaForte123')
            db.session.add(user)
            db.session.flush()

            # Reserva das 00:00 às 23:59: sobrepõe qualquer período atual,
            # tornando o teste independente da hora em que ele roda.
            self._add_reservation(user.id, self.quadra_room.id, 'Aula de Vôlei',
                                  date.today(), time(0, 0), time(23, 59))

            # IDs simples: fora do app_context os objetos ORM ficam detached
            self.quadra_id = self.quadra.id
            self.sem_estilo_id = self.sem_estilo.id
            self.quadra_room_id = self.quadra_room.id
            self.user_id = user.id
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _add_reservation(self, user_id, classroom_id, title, res_date,
                         start_time, end_time, status='approved'):
        reservation = Reservation(user_id=user_id, classroom_id=classroom_id,
                                  title=title, date=res_date,
                                  start_time=start_time, end_time=end_time,
                                  status=status, unity_id=self.unity_id)
        db.session.add(reservation)
        return reservation

    def _login(self):
        return self.client.post('/login',
                                data={'username': 'prof.teste',
                                      'password': 'SenhaForte123'},
                                follow_redirects=False)

    # ── Modelo ───────────────────────────────────────────────────────────

    def test_fallbacks_de_cor_e_icone(self):
        """Categoria sem cor/ícone (cadastrada antes dos campos existirem)
        ainda renderiza, caindo no padrão visual do sistema."""
        with self.app.app_context():
            cat = db.session.get(RoomCategory, self.sem_estilo_id)
            self.assertEqual(cat.display_color, RoomCategory.DEFAULT_COLOR)
            self.assertEqual(cat.display_icon, RoomCategory.DEFAULT_ICON)
            self.assertEqual(cat.totem_window_label, 'Período atual')

    # ── Totem ────────────────────────────────────────────────────────────

    def test_totem_exibe_categoria_cadastrada_sem_codigo(self):
        """A categoria da quadra aparece no totem apenas por existir no
        cadastro — nenhum trecho de código cita 'sports_court'."""
        resp = self.client.get('/totem/')
        self.assertEqual(resp.status_code, 200)
        page = resp.data.decode('utf-8')
        self.assertIn('Quadra de Esportes', page)
        self.assertIn('Aula de Vôlei', page)
        self.assertIn('bi-volleyball', page)
        self.assertIn('#198754', page)

    def test_totem_ignora_categoria_sem_espaco_na_unidade(self):
        """Categoria sem sala na unidade do totem não gera bloco vazio."""
        with self.app.app_context():
            db.session.add(RoomCategory(name='Van', code='van'))
            db.session.commit()

        resp = self.client.get('/totem/')
        self.assertNotIn('Van', resp.data.decode('utf-8'))

    def test_totem_respeita_janela_de_semana(self):
        """Categoria com janela 'week' exibe reserva dos próximos dias —
        recorte que antes era exclusivo do código de auditório."""
        with self.app.app_context():
            cat = db.session.get(RoomCategory, self.sem_estilo_id)
            cat.totem_window = RoomCategory.TOTEM_WINDOW_WEEK
            room = Classroom.query.filter_by(category_id=cat.id).first()
            self._add_reservation(self.user_id, room.id, 'Feira de Livros',
                                  date.today() + timedelta(days=1),
                                  time(9, 0), time(11, 0))
            db.session.commit()

        resp = self.client.get('/totem/')
        page = resp.data.decode('utf-8')
        self.assertIn('Biblioteca', page)
        self.assertIn('Feira de Livros', page)
        self.assertIn('(Próximos 7 dias)', page)

    # ── Dashboard ────────────────────────────────────────────────────────

    def test_dashboard_agrupa_pela_categoria_cadastrada(self):
        """O painel troca os blocos fixos 'Auditórios'/'Salas' por uma seção
        por categoria, montada a partir do cadastro."""
        self._login()
        resp = self.client.get('/dashboard')
        self.assertEqual(resp.status_code, 200)
        page = resp.data.decode('utf-8')
        self.assertIn('Agenda de Quadra de Esportes', page)
        self.assertIn('bi-volleyball', page)

    # ── Formulário ───────────────────────────────────────────────────────

    def test_formulario_rejeita_cor_invalida(self):
        with self.app.app_context():
            # formdata de POST real (MultiDict): com formdata=None o Optional()
            # interrompe a cadeia antes dos validadores inline e o teste
            # perderia o efeito.
            form = RoomCategoryForm(formdata=MultiDict({
                'name': 'Laboratório', 'code': 'lab', 'color': 'verde',
                'totem_window': 'period',
            }))
            self.assertFalse(form.validate())
            self.assertIn('color', form.errors)

    def test_formulario_aceita_categoria_completa(self):
        with self.app.app_context():
            form = RoomCategoryForm(formdata=MultiDict({
                'name': 'Quadra de Areia', 'code': 'beach_court',
                'color': '#198754', 'icon': 'bi-volleyball',
                'totem_window': 'week',
            }))
            self.assertTrue(form.validate(), form.errors)


if __name__ == '__main__':
    unittest.main()
