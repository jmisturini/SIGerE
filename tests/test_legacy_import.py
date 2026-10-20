"""Testes do importador do sistema legado (app/legacy_import.py).

Cobre as partes de maior risco sem depender do dump real:
- parser do SQL do phpMyAdmin (strings escapadas, NULL, string vazia,
  valores numéricos e strings contendo vírgula/parêntese);
- transcodificação de senha Django pbkdf2 -> Werkzeug (validando a senha com
  check_password_hash, o mesmo caminho do login);
- classificação de categorias de sala com acentuação.
"""
import base64
import hashlib
import os
import tempfile
import unittest

from werkzeug.security import check_password_hash

from app import create_app
from app.config import Config
from app.extensions import db
from app.legacy_import import (_classify_room, _transcode_password,
                               read_dump_table)


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class LegacyImportUnitTestCase(unittest.TestCase):
    """Testes de funções puras (sem banco)."""

    DUMP_SNIPPET = """
CREATE TABLE `t` (`id` int NOT NULL, `nome` varchar(50), `ativo` tinyint(1));
INSERT INTO `t` (`id`, `nome`, `ativo`) VALUES
(1, 'João', 1),
(2, 'Teste com \\'aspas\\' e, vírgula (entre parênteses)', 0),
(3, '', NULL),
(4, 'Linha\\r\\nquebrada', 1);
INSERT INTO `t` (`id`, `nome`, `ativo`) VALUES
(5, 'Segundo bloco', 1);
"""

    def test_read_dump_table(self):
        rows = read_dump_table(self.DUMP_SNIPPET, "t")
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0], {"id": "1", "nome": "João", "ativo": "1"})
        # string com aspas escapadas, vírgula e parênteses preservados
        self.assertEqual(rows[1]["nome"],
                         "Teste com 'aspas' e, vírgula (entre parênteses)")
        self.assertEqual(rows[1]["ativo"], "0")
        # string vazia ≠ NULL
        self.assertEqual(rows[2]["nome"], "")
        self.assertIsNone(rows[2]["ativo"])
        # escapes \\r\\n do phpMyAdmin viram quebras reais
        self.assertEqual(rows[3]["nome"], "Linha\r\nquebrada")
        # segundo bloco INSERT da mesma tabela
        self.assertEqual(rows[4]["nome"], "Segundo bloco")

    def test_transcode_password_roundtrip(self):
        salt, iterations, password = "abcSalt123", 600000, "Senha@Legada"
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
        django_hash = f"pbkdf2_sha256${iterations}${salt}${base64.b64encode(dk).decode()}"
        converted, ok = _transcode_password(django_hash)
        self.assertTrue(ok)
        self.assertTrue(converted.startswith("pbkdf2:sha256:600000$abcSalt123$"))
        # o mesmo caminho executado no login do SIGERE
        self.assertTrue(check_password_hash(converted, password))
        self.assertFalse(check_password_hash(converted, "senha-errada"))

    def test_transcode_password_corrompida(self):
        converted, ok = _transcode_password("S&n@pbkdf2_sha256$600000$s$abc=")
        self.assertIsNone(converted)
        self.assertFalse(ok)
        self.assertEqual(_transcode_password(None), (None, False))
        self.assertEqual(_transcode_password(""), (None, False))

    def test_classify_room_acentos(self):
        self.assertEqual(_classify_room("Lab. Informática"), "lab_info")
        self.assertEqual(_classify_room("Lab. Infinity"), "lab_info")
        self.assertEqual(_classify_room("Lab. Saúde/Masso/Estética"), "lab_saude")
        self.assertEqual(_classify_room("Cozinha Pedagógica"), "cozinha")
        self.assertEqual(_classify_room("Sala de aula"), "sala_aula")
        self.assertEqual(_classify_room(None), "sala_aula")


class LegacyImportGuardTestCase(unittest.TestCase):
    """A guarda recusa banco com dados sem --force; a importação cria a
    unidade única e direciona o acervo para ela."""

    MINIMAL_DUMP = (
        "-- phpMyAdmin SQL Dump\n"
        "CREATE TABLE `units` (`id` int NOT NULL, `unit` varchar(50) NOT NULL);\n"
        "INSERT INTO `units` (`id`, `unit`) VALUES\n"
        "(1, 'Unidade Teste'),\n"
        "(2, 'Outra Unidade');\n"
        "CREATE TABLE `classroom` (`id` int NOT NULL, `number_class` int NOT NULL,\n"
        " `description_class` varchar(100) NOT NULL, `computers_available` int,\n"
        " `available_software` longtext, `extra_structure` longtext, `ability` int);\n"
        "INSERT INTO `classroom` (`id`, `number_class`, `description_class`,\n"
        " `computers_available`, `available_software`, `extra_structure`, `ability`) VALUES\n"
        "(1, 104, 'Lab. Informática', 30, '', '', 33);\n"
    )

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        with self.app.app_context():
            db.create_all()
            db.session.commit()
        fd, self.dump_path = tempfile.mkstemp(suffix='.sql')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(self.MINIMAL_DUMP)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)
        os.remove(self.dump_path)

    def test_recusa_banco_com_dados(self):
        from app.legacy_import import (TARGET_UNITY_CODE, TARGET_UNITY_NAME,
                                       import_legacy)
        from app.models import Classroom, Unity
        with self.app.app_context():
            db.session.add(Unity(name="X", code="X1"))
            db.session.commit()
            with self.assertRaises(RuntimeError):
                import_legacy(self.dump_path)
            # com --force passa da guarda (e avança para o parser)
            import_legacy(self.dump_path, force=True)
            # unidades do dump NÃO são criadas; a unidade única sim
            self.assertIsNone(Unity.query.filter_by(name="Unidade Teste").first())
            target = Unity.query.filter_by(code=TARGET_UNITY_CODE).first()
            self.assertIsNotNone(target)
            self.assertEqual(target.name, TARGET_UNITY_NAME)
            # o acervo importado fica na unidade única
            room = Classroom.query.filter_by(code="104").first()
            self.assertIsNotNone(room)
            self.assertEqual(room.unity_id, target.id)


class LegacyImportUserProfileRuleTestCase(unittest.TestCase):
    """Regra do quadro: com setor/departamento/função preenchidos o usuário
    importado é funcionário (is_teacher=True preserva a designação em
    reservas); professor é quem não tem nenhum vínculo administrativo."""

    DUMP = (
        "-- phpMyAdmin SQL Dump\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `cores`\n--\n\n"
        "CREATE TABLE `cores` (`id` int NOT NULL, `core` varchar(100) NOT NULL);\n"
        "--\n-- Dumping data for table `cores`\n--\n\n"
        "INSERT INTO `cores` (`id`, `core`) VALUES\n"
        "(1, 'Núcleo Tecnológico');\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `sectors`\n--\n\n"
        "CREATE TABLE `sectors` (`id` int NOT NULL, `sector` varchar(100) NOT NULL);\n"
        "--\n-- Dumping data for table `sectors`\n--\n\n"
        "INSERT INTO `sectors` (`id`, `sector`) VALUES\n"
        "(1, 'Setor de TI');\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `functions`\n--\n\n"
        "CREATE TABLE `functions` (`id` int NOT NULL, `function` varchar(100) NOT NULL);\n"
        "--\n-- Dumping data for table `functions`\n--\n\n"
        "INSERT INTO `functions` (`id`, `function`) VALUES\n"
        "(1, 'Professor de Gastronomia'),\n"
        "(2, 'Coordenador de Curso');\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `authenticator_customuser`\n--\n\n"
        "CREATE TABLE `authenticator_customuser` (`id` int NOT NULL, `registration` int,\n"
        " `email` varchar(100), `first_name` varchar(50), `last_name` varchar(50),\n"
        " `username` varchar(50), `is_active` int, `is_superuser` int, `is_staff` int,\n"
        " `unit_id` int, `core_id` int, `sector_id` int, `function_id` int,\n"
        " `password` varchar(200), `date_joined` datetime);\n"
        "--\n-- Dumping data for table `authenticator_customuser`\n--\n\n"
        "INSERT INTO `authenticator_customuser` (`id`, `registration`, `email`,\n"
        " `first_name`, `last_name`, `username`, `is_active`, `is_superuser`,\n"
        " `is_staff`, `unit_id`, `core_id`, `sector_id`, `function_id`,\n"
        " `password`, `date_joined`) VALUES\n"
        "(1, 100, 'carla@senac.br', 'Carla', 'Com Lotacao', 'carla', 1, 0, 0, 1, 1, 1, 1, 'lixo', '2023-05-10 10:00:00'),\n"
        "(2, 200, 'diego@senac.br', 'Diego', 'Coordenador', 'diego', 1, 0, 0, 1, 1, NULL, 2, 'lixo', '2023-05-10 10:00:00'),\n"
        "(3, 300, 'elena@senac.br', 'Elena', 'Sem Lotacao', 'elena', 1, 0, 0, 1, NULL, NULL, NULL, 'lixo', '2023-05-10 10:00:00');\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `authenticator_teachersuser`\n--\n\n"
        "CREATE TABLE `authenticator_teachersuser` (`registration` int NOT NULL,\n"
        " `email` varchar(100), `first_name` varchar(50), `last_name` varchar(50),\n"
        " `username` varchar(50), `is_active` int, `unit_id` int,\n"
        " `password` varchar(200), `date_joined` datetime);\n"
        "--\n-- Dumping data for table `authenticator_teachersuser`\n--\n\n"
        "INSERT INTO `authenticator_teachersuser` (`registration`, `email`,\n"
        " `first_name`, `last_name`, `username`, `is_active`, `unit_id`,\n"
        " `password`, `date_joined`) VALUES\n"
        "(100, 'carla@senac.br', 'Carla', 'Com Lotacao', 'carla', 1, 1, 'lixo', '2023-05-10 10:00:00'),\n"
        "(300, 'elena@senac.br', 'Elena', 'Sem Lotacao', 'elena', 1, 1, 'lixo', '2023-05-10 10:00:00'),\n"
        "(400, 'fernanda@senac.br', 'Fernanda', 'Pura', 'fernanda', 1, 1, 'lixo', '2023-05-10 10:00:00');\n"
    )

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        with self.app.app_context():
            db.create_all()
            db.session.commit()
        fd, self.dump_path = tempfile.mkstemp(suffix='.sql')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(self.DUMP)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)
        os.remove(self.dump_path)

    def _usuarios_por_matricula(self):
        from app.models import User
        return {u.registration: u for u in User.query.all()}

    def test_com_lotacao_o_perfil_e_funcionario(self):
        from app.legacy_import import import_legacy
        with self.app.app_context():
            import_legacy(self.dump_path, force=True)
        with self.app.app_context():
            usuarios = self._usuarios_por_matricula()
            # Função de professora + setor/departamento preenchidos → funcionária
            carla = usuarios['100']
            self.assertEqual(carla.profile_type, 'employee')
            self.assertTrue(carla.is_teacher)  # segue designável em reservas
            self.assertEqual(carla.role, 'employee')
            self.assertEqual(carla.sector, 'Setor de TI')

    def test_quadro_sem_docencia_e_funcionario(self):
        from app.legacy_import import import_legacy
        with self.app.app_context():
            import_legacy(self.dump_path, force=True)
        with self.app.app_context():
            diego = self._usuarios_por_matricula()['200']
            self.assertEqual(diego.profile_type, 'employee')
            self.assertFalse(diego.is_teacher)

    def test_professor_sem_lotacao_vira_professor(self):
        from app.legacy_import import import_legacy
        with self.app.app_context():
            import_legacy(self.dump_path, force=True)
        with self.app.app_context():
            elena = self._usuarios_por_matricula()['300']
            # dedup com teachersuser: sem nenhum vínculo administrativo → professor
            self.assertEqual(elena.profile_type, 'teacher')
            self.assertTrue(elena.is_teacher)
            self.assertEqual(elena.role, 'teacher')

    def test_professor_puro_da_tabela_de_professores(self):
        from app.legacy_import import import_legacy
        with self.app.app_context():
            import_legacy(self.dump_path, force=True)
        with self.app.app_context():
            fernanda = self._usuarios_por_matricula()['400']
            self.assertEqual(fernanda.profile_type, 'teacher')
            self.assertTrue(fernanda.is_teacher)


class LegacyImportHoraExtraFechamentoTestCase(unittest.TestCase):
    """Meses de referência anteriores ao mês base atual (janela 20→20) já
    entram bloqueados na importação — o acervo do legado é histórico. Mês
    futuro e month_base fora do formato não são bloqueados, e mês repetido
    em vários lançamentos gera um único fechamento."""

    DUMP = (
        "-- phpMyAdmin SQL Dump\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `authenticator_teachersuser`\n--\n\n"
        "CREATE TABLE `authenticator_teachersuser` (`registration` int NOT NULL,\n"
        " `email` varchar(100), `first_name` varchar(50), `last_name` varchar(50),\n"
        " `username` varchar(50), `is_active` int, `unit_id` int,\n"
        " `password` varchar(200), `date_joined` datetime);\n"
        "--\n-- Dumping data for table `authenticator_teachersuser`\n--\n\n"
        "INSERT INTO `authenticator_teachersuser` (`registration`, `email`,\n"
        " `first_name`, `last_name`, `username`, `is_active`, `unit_id`,\n"
        " `password`, `date_joined`) VALUES\n"
        "(400, 'fernanda@senac.br', 'Fernanda', 'Pura', 'fernanda', 1, 1, 'lixo', '2023-05-10 10:00:00');\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `teaching_level`\n--\n\n"
        "CREATE TABLE `teaching_level` (`id` int NOT NULL, `level` varchar(50));\n"
        "--\n-- Dumping data for table `teaching_level`\n--\n\n"
        "INSERT INTO `teaching_level` (`id`, `level`) VALUES\n"
        "(1, 'Graduação');\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `shifts`\n--\n\n"
        "CREATE TABLE `shifts` (`id` int NOT NULL, `shift` varchar(50));\n"
        "--\n-- Dumping data for table `shifts`\n--\n\n"
        "INSERT INTO `shifts` (`id`, `shift`) VALUES\n"
        "(1, 'Matutino'),\n"
        "(2, 'Noturno');\n"
        "-- --------------------------------------------------------\n"
        "--\n-- Table structure for table `teacher_overtime_pay`\n--\n\n"
        "CREATE TABLE `teacher_overtime_pay` (`id` int NOT NULL, `teacher_id` int,\n"
        " `accountable_id` int, `teaching_level_id` int, `weekly_workload` int,\n"
        " `hourly_value` varchar(20), `budget_code` varchar(50), `shift_id` int,\n"
        " `multiple_dates` varchar(255), `justification` varchar(255),\n"
        " `month_base` varchar(7), `created_at` datetime);\n"
        "--\n-- Dumping data for table `teacher_overtime_pay`\n--\n\n"
        "INSERT INTO `teacher_overtime_pay` (`id`, `teacher_id`, `accountable_id`,\n"
        " `teaching_level_id`, `weekly_workload`, `hourly_value`, `budget_code`,\n"
        " `shift_id`, `multiple_dates`, `justification`, `month_base`, `created_at`) VALUES\n"
        "(1, 400, NULL, 1, 20, '45.00', 'PROJ-A', 1, '10/03/2025, 17/03/2025', 'Aula extra', '2025-03', '2025-04-02 10:00:00'),\n"
        "(2, 400, NULL, 1, 20, '45.00', 'PROJ-A', 2, '09/12/2024', 'Reposição', '2024-12', '2025-01-05 10:00:00'),\n"
        "(3, 400, NULL, 1, 20, '45.00', 'PROJ-B', 1, '11/03/2025', 'Banco de horas', '2025-03', '2025-04-03 10:00:00'),\n"
        "(4, 400, NULL, 1, 20, '45.00', 'PROJ-C', 1, '05/01/2099', 'Lançamento futuro', '2099-01', '2025-04-03 10:00:00'),\n"
        "(5, 400, NULL, 1, 20, '45.00', NULL, 1, NULL, NULL, '', NULL);\n"
    )

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        with self.app.app_context():
            db.create_all()
            db.session.commit()
        fd, self.dump_path = tempfile.mkstemp(suffix='.sql')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(self.DUMP)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)
        os.remove(self.dump_path)

    def test_meses_anteriores_ao_mes_base_ja_vem_bloqueados(self):
        from app.legacy_import import TARGET_UNITY_CODE, import_legacy
        from app.models import OvertimeMonthClosure, TeacherOvertimePay, Unity
        with self.app.app_context():
            import_legacy(self.dump_path, force=True)
        with self.app.app_context():
            unity = Unity.query.filter_by(code=TARGET_UNITY_CODE).first()
            closures = OvertimeMonthClosure.query.all()
            # meses passados bloqueados; repetição de 2025-03 vira um só
            self.assertEqual({c.month_base for c in closures},
                             {'2025-03', '2024-12'})
            for c in closures:
                self.assertEqual(c.unity_id, unity.id)
                self.assertIsNone(c.closed_by_id)  # fechado pela migração
                self.assertIsNotNone(c.closed_at)
            # mês futuro e month_base inválido seguem sem fechamento
            self.assertEqual(TeacherOvertimePay.query.filter_by(
                month_base='2099-01').count(), 1)
            self.assertIsNone(OvertimeMonthClosure.query.filter_by(
                month_base='2099-01').first())
            self.assertIsNone(OvertimeMonthClosure.query.filter_by(
                month_base='').first())


if __name__ == '__main__':
    unittest.main()
