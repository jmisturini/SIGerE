"""Testes do sync de permissões (sync_permissions_impl).

Cobre o upgrade de bancos criados antes da separação de papéis dentro do
Financeiro: as permissões vt:* do Vale-Transporte passam a existir e são
concedidas ao Administrador Financeiro sem remover os vínculos de payment:*
(pagamento extra) que o papel já possui.
"""
import os
import tempfile
import unittest

from app import create_app
from app.commands import sync_permissions_impl
from app.config import Config
from app.extensions import db
from app.models import Permission, Role


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class SyncPermissionsTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        TestConfig.SQLALCHEMY_DATABASE_URI = 'sqlite:///' + self.db_path.replace('\\', '/')
        self.app = create_app(TestConfig)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        for suffix in ('', '-wal', '-shm'):
            path = self.db_path + suffix
            if os.path.exists(path):
                os.remove(path)

    def test_separacao_financeiro_no_upgrade_de_banco_antigo(self):
        """Banco pré-separação: o Administrador Financeiro só tem payment:*.
        O sync cria as vt:* e as concede ao papel, preservando os vínculos
        antigos — e é idempotente (rodar de novo não duplica nada)."""
        with self.app.app_context():
            db.create_all()
            for code in ('payment:read', 'payment:create', 'payment:export'):
                db.session.add(Permission(code=code, module='payment',
                                          action=code.split(':')[1]))
            db.session.flush()
            role = Role(name='financial_admin', label='Administrador Financeiro',
                        permissions=Permission.query.filter(
                            Permission.code.like('payment:%')).all())
            db.session.add(role)
            db.session.commit()
            role_id = role.id

            sync_permissions_impl(verbose=False)

            codes = {p.code for p in db.session.get(Role, role_id).permissions}
            self.assertTrue({'vt:read', 'vt:create', 'vt:edit', 'vt:delete',
                             'vt:export'} <= codes)
            self.assertTrue({'payment:read', 'payment:create',
                             'payment:export'} <= codes)

            # Idempotência: segunda execução mantém exatamente os mesmos vínculos
            sync_permissions_impl(verbose=False)
            self.assertEqual(
                {p.code for p in db.session.get(Role, role_id).permissions}, codes)

    def test_sync_cria_todas_as_permissoes_do_catalogo(self):
        with self.app.app_context():
            db.create_all()
            from app.commands import PERMISSION_DATA
            sync_permissions_impl(verbose=False)
            codes = {p.code for p in Permission.query.all()}
            for code, _, _, _ in PERMISSION_DATA:
                self.assertIn(code, codes)


if __name__ == '__main__':
    unittest.main()
