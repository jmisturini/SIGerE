"""Trilha de auditoria de segurança: eventos sensíveis geram uma linha
'[AUDITORIA] evento=... ator=... ip=... alvo=...' no log da aplicação.

Cobre login (sucesso/falha/bloqueio automático), ações administrativas de
conta (bloquear/desbloquear/resetar/criar/editar) e garante que senha nunca
aparece no log.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import AuditLog, Permission, Role, Unity, User

SENHA = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class AuditoriaTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.app.config['SESSION_COOKIE_SECURE'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

            perms = {}
            for code in ('user:lock', 'user:create', 'user:edit',
                         'user:toggle', 'user:read', 'system:audit'):
                perms[code] = Permission(code=code, module=code.split(':')[0],
                                         action=code.split(':')[1],
                                         description=code)
            db.session.add_all(perms.values())
            db.session.flush()

            self.role_gestor = Role(
                name='gestor_teste', label='Gestor Teste',
                permissions=list(perms.values()))
            self.role_basico = Role(name='basico_teste', label='Básico Teste',
                                    permissions=[])
            db.session.add_all([self.role_gestor, self.role_basico])
            db.session.flush()

            unity = Unity(name='Unidade A', code='UA', is_active=True)
            db.session.add(unity)
            db.session.flush()

            def novo(email, nome, role):
                u = User(email=email, full_name=nome, registration=email,
                         profile_type='employee', role_id=role.id,
                         force_password_change=False, is_active_user=True)
                u.set_password(SENHA)
                db.session.add(u)
                return u

            self.gestor = novo('gestor@escola.edu', 'Gestor Auditoria', self.role_gestor)
            self.alvo = novo('alvo@escola.edu', 'Conta Alvo', self.role_basico)
            db.session.commit()
            self.ids = {u.email: u.id for u in (self.gestor, self.alvo)}
            self.gestor_role_id = self.role_gestor.id
            self.unity_id = unity.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _post_login(self, email, senha):
        self.client.get('/logout')
        return self.client.post('/login', data={'email': email, 'password': senha},
                                follow_redirects=True)

    def _linhas(self, cm, evento):
        return [linha for linha in cm.output
                if '[AUDITORIA] evento=' + evento in linha]

    # ── Login ────────────────────────────────────────────────────────────

    def test_login_sucesso_e_falha_auditorados(self):
        with self.assertLogs('app', level='INFO') as cm:
            self._post_login('alvo@escola.edu', 'SenhaErrada999')
        falhas = self._linhas(cm, 'login_falha')
        self.assertEqual(len(falhas), 1)
        self.assertIn('alvo=alvo@escola.edu', falhas[0])
        self.assertIn('conta_existe=sim', falhas[0])

        with self.assertLogs('app', level='INFO') as cm:
            self._post_login('alvo@escola.edu', SENHA)
        sucessos = self._linhas(cm, 'login_sucesso')
        self.assertEqual(len(sucessos), 1)
        # O ator é anônimo no momento do POST; o alvo identifica a conta.
        self.assertIn('alvo=alvo@escola.edu', sucessos[0])
        self.assertIn('ip=', sucessos[0])

    def test_email_inexistente_auditorado_sem_conta(self):
        with self.assertLogs('app', level='INFO') as cm:
            self._post_login('fantasma@escola.edu', SENHA)
        falhas = self._linhas(cm, 'login_falha')
        self.assertEqual(len(falhas), 1)
        self.assertIn('conta_existe=nao', falhas[0])

    def test_bloqueio_automatico_auditorado(self):
        with self.assertLogs('app', level='INFO') as cm:
            for _ in range(10):
                self._post_login('alvo@escola.edu', 'SenhaErrada999')
        bloqueios = self._linhas(cm, 'conta_bloqueada_automatica')
        self.assertEqual(len(bloqueios), 1, 'a transição para bloqueada é única')
        self.assertIn('tentativas=10', bloqueios[0])
        self.assertIn('alvo=alvo@escola.edu', bloqueios[0])

    # ── Ações administrativas ────────────────────────────────────────────

    def _como_gestor(self):
        self._post_login('gestor@escola.edu', SENHA)

    def test_bloqueio_e_desbloqueio_manual_auditorados(self):
        self._como_gestor()
        with self.assertLogs('app', level='INFO') as cm:
            self.client.post(f"/admin/users/{self.ids['alvo@escola.edu']}/lock")
            self.client.post(f"/admin/users/{self.ids['alvo@escola.edu']}/unlock")
        self.assertEqual(len(self._linhas(cm, 'conta_bloqueada_manual')), 1)
        desbloqueios = self._linhas(cm, 'conta_desbloqueada')
        self.assertEqual(len(desbloqueios), 1)
        self.assertIn('alvo=alvo@escola.edu', desbloqueios[0])

    def test_reset_de_senha_auditorado_sem_vazar_senha(self):
        self._como_gestor()
        with self.assertLogs('app', level='INFO') as cm:
            self.client.post(f"/admin/users/{self.ids['alvo@escola.edu']}/reset-password")
        resets = self._linhas(cm, 'senha_resetada')
        self.assertEqual(len(resets), 1)
        self.assertIn('alvo=alvo@escola.edu', resets[0])
        # A senha temporária (no flash) e a senha dos testes nunca vão ao log.
        self.assertNotIn(SENHA, ' '.join(cm.output))

    def test_criacao_e_edicao_auditoradas(self):
        self._como_gestor()
        payload = {
            'profile_type': 'employee', 'full_name': 'Nova Pessoa',
            'email': 'nova@escola.edu', 'registration': 'MAT999',
            'unities': str(self.unity_id), 'role_id': str(self.gestor_role_id),
            'password': 'SenhaForte123', 'is_active_user': 'y',
        }
        with self.assertLogs('app', level='INFO') as cm:
            self.client.post('/admin/users/create-employee', data=payload)
            self.client.post(f"/admin/users/{self.ids['alvo@escola.edu']}/edit",
                             data={'profile_type': 'employee',
                                   'full_name': 'Conta Alvo Editada',
                                   'email': 'alvo@escola.edu', 'registration': 'alvo@escola.edu',
                                   'role_id': str(self.gestor_role_id),
                                   'unities': str(self.unity_id),
                                   'password': '', 'is_active_user': 'y'})
        criacoes = self._linhas(cm, 'usuario_criado')
        self.assertEqual(len(criacoes), 1)
        self.assertIn('alvo=nova@escola.edu', criacoes[0])
        self.assertIn('perfil=employee', criacoes[0])
        edicoes = self._linhas(cm, 'usuario_editado')
        self.assertEqual(len(edicoes), 1)
        self.assertIn('senha_alterada=nao', edicoes[0])

    def test_senha_nunca_aparece_no_log(self):
        """Nenhum evento de auditoria carrega a senha (nem em falha de login)."""
        with self.assertLogs('app', level='INFO') as cm:
            self._post_login('alvo@escola.edu', SENHA)
            self._post_login('alvo@escola.edu', 'SenhaErrada999')
        for linha in cm.output:
            self.assertNotIn(SENHA, linha)

    # ── Persistência e consulta no painel ────────────────────────────────

    def _linhas_db(self, **filtros):
        with self.app.app_context():
            return [f'{r.evento}|{r.actor_email}|{r.alvo}|{r.ip}|{r.detalhes}'
                    for r in AuditLog.query.filter_by(**filtros).all()]

    def test_eventos_persistem_na_tabela(self):
        """auditar() grava em audit_logs além do log: ator anônimo no login,
        alvo e IP preenchidos; eventos administrativos carregam o ator."""
        self._post_login('alvo@escola.edu', 'SenhaErrada999')
        falhas = self._linhas_db(evento='login_falha')
        self.assertEqual(len(falhas), 1)
        self.assertIn('None|', falhas[0])  # sem ator: antes do login
        self.assertIn('alvo@escola.edu', falhas[0])
        self.assertIn('conta_existe=sim', falhas[0])
        self.assertNotIn('None|None|None|', falhas[0])  # ip sempre presente

        self._como_gestor()
        self.client.post(f"/admin/users/{self.ids['alvo@escola.edu']}/lock")
        bloqueios = self._linhas_db(evento='conta_bloqueada_manual')
        self.assertEqual(len(bloqueios), 1)
        self.assertIn('gestor@escola.edu', bloqueios[0])
        self.assertIn('alvo@escola.edu', bloqueios[0])

    def test_consulta_exige_system_audit(self):
        self._post_login('alvo@escola.edu', SENHA)  # papel sem system:audit
        resp = self.client.get('/admin/auditoria')
        self.assertEqual(resp.status_code, 403)

    def test_consulta_filtra_por_evento_e_texto(self):
        self._post_login('alvo@escola.edu', SENHA)
        self._post_login('gestor@escola.edu', SENHA)

        resp = self.client.get('/admin/auditoria?evento=login_sucesso')
        self.assertEqual(resp.status_code, 200)
        pagina = resp.get_data(as_text=True)
        self.assertIn('login_sucesso', pagina)
        self.assertNotIn('login_falha</span>', pagina)

        resp = self.client.get('/admin/auditoria?q=alvo@')
        pagina = resp.get_data(as_text=True)
        self.assertIn('alvo@escola.edu', pagina)
        self.assertNotIn('gestor@escola.edu', pagina)

    def test_consulta_filtra_por_periodo(self):
        """Filtro de período com datas fixas: os eventos são gravados em UTC,
        então o teste não pode derivar 'hoje' da data local (à noite no Brasil
        o dia UTC já é o seguinte)."""
        self._post_login('alvo@escola.edu', SENHA)
        self._como_gestor()
        with self.app.app_context():
            db.session.add(AuditLog(evento='login_falha', alvo='antigo@escola.edu',
                                    created_at=datetime(2020, 1, 1)))
            db.session.commit()

        hoje = datetime.now(timezone.utc).date().isoformat()

        # Período de hoje (UTC): traz os logins recentes, não o evento de 2020.
        resp = self.client.get(f'/admin/auditoria?de={hoje}&ate={hoje}')
        self.assertEqual(resp.status_code, 200)
        pagina = resp.get_data(as_text=True)
        self.assertIn('alvo@escola.edu', pagina)
        self.assertNotIn('antigo@escola.edu', pagina)

        # Período da data fixa: só o evento antigo. 'login_sucesso' sempre
        # aparece no <option> do filtro — asserção pelo dado, não pelo nome.
        resp = self.client.get('/admin/auditoria?de=2020-01-01&ate=2020-01-01')
        self.assertEqual(resp.status_code, 200)
        pagina = resp.get_data(as_text=True)
        self.assertIn('antigo@escola.edu', pagina)
        self.assertNotIn('alvo@escola.edu', pagina)


if __name__ == '__main__':
    unittest.main()
