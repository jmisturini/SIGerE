"""Comando CLI unlock-user: desbloqueio de recuperação com trilha de auditoria.

Cobre a lacuna apontada na revisão do PR #162: o desbloqueio pela CLI (caminho
de recuperação do único super-admin bloqueado no login público) precisa ficar
na trilha de auditoria mesmo fora de contexto HTTP.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import AuditLog, Permission, Role, User

SENHA = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class UnlockUserCommandTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)
        self.runner = self.app.test_cli_runner()

        with self.app.app_context():
            db.create_all()
            perm = Permission(code='user:lock', module='user', action='lock')
            role = Role(name='gestor', label='Gestor', permissions=[perm])
            db.session.add(role)
            db.session.flush()
            user = User(email='admin@escola.edu', full_name='Super Um',
                        profile_type='employee', role_id=role.id,
                        force_password_change=False, is_active_user=True)
            user.set_password(SENHA)
            user.is_locked = True
            user.locked_at = datetime.now(timezone.utc)
            user.failed_login_attempts = 10
            db.session.add(user)
            db.session.commit()
            self.email = user.email

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_desbloqueia_e_audita_origem_cli(self):
        with patch('app.commands._operador_cli', return_value='operador-teste'):
            resultado = self.runner.invoke(args=['unlock-user', self.email])
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        with self.app.app_context():
            user = User.query.filter_by(email=self.email).first()
            self.assertFalse(user.is_locked)
            self.assertEqual(user.failed_login_attempts, 0)
            registro = AuditLog.query.filter_by(evento='conta_desbloqueada',
                                                alvo=self.email).first()
            self.assertIsNotNone(registro)
            # Fora de contexto HTTP: sem ator de sessão, sem IP, e o operador
            # resolvido pelo comando presente nos detalhes.
            self.assertIn('origem=cli', registro.detalhes or '')
            self.assertIn('operador=operador-teste', registro.detalhes or '')
            self.assertIsNone(registro.actor_id)
            self.assertEqual(registro.ip, '-')

    def test_conta_ja_desbloqueada_nada_alterado(self):
        with self.app.app_context():
            User.query.filter_by(email=self.email).first().desbloquear()
            db.session.commit()
        resultado = self.runner.invoke(args=['unlock-user', self.email])
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        self.assertIn('não está bloqueada', resultado.output)
        with self.app.app_context():
            self.assertEqual(AuditLog.query.filter_by(
                evento='conta_desbloqueada').count(), 0)

    def test_conta_inexistente_falha_sem_auditar(self):
        resultado = self.runner.invoke(args=['unlock-user', 'fantasma@escola.edu'])
        self.assertNotEqual(resultado.exit_code, 0)
        with self.app.app_context():
            self.assertEqual(AuditLog.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
