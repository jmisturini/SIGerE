"""Testes do sync de permissões (sync_permissions_impl).

Cobre o catálogo de permissões e o comportamento do sync diante de papéis
que não fazem parte de ROLES_CONFIG (criados manualmente no painel ou
herdados de versões anteriores do sistema): eles não recebem nem perdem
vínculos — e o sync é idempotente.
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

    def test_sync_nao_altera_papel_fora_do_roles_config(self):
        """Papel criado fora de ROLES_CONFIG (manual ou de versão anterior):
        o sync não concede nem remove vínculos dele — e é idempotente."""
        with self.app.app_context():
            db.create_all()
            for code in ('payment:read', 'payment:create', 'payment:export'):
                db.session.add(Permission(code=code, module='payment',
                                          action=code.split(':')[1]))
            db.session.flush()
            role = Role(name='financeiro_legado', label='Financeiro (legado)',
                        permissions=Permission.query.filter(
                            Permission.code.like('payment:%')).all())
            db.session.add(role)
            db.session.commit()
            role_id = role.id

            sync_permissions_impl(verbose=False)

            codes = {p.code for p in db.session.get(Role, role_id).permissions}
            self.assertEqual(codes,
                             {'payment:read', 'payment:create', 'payment:export'})

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

    def test_dump_permissions_um_vinculo_por_linha_com_nome_escapado(self):
        """Inventário do dump-permissions: um nome de papel com quebra de
        linha não forja um vínculo falso — sai escapado, uma linha por par."""
        with self.app.app_context():
            db.create_all()
            leitura = Permission(code='payment:read', module='payment', action='read')
            db.session.add(leitura)
            db.session.flush()
            db.session.add(Role(name='forjado\nadmin :: system:admin',
                                label='Forjado', permissions=[leitura]))
            db.session.add(Role(name='comum', label='Comum', permissions=[leitura]))
            db.session.commit()

        resultado = self.app.test_cli_runner().invoke(args=['dump-permissions'])
        self.assertEqual(resultado.exit_code, 0, resultado.output)
        linhas = resultado.output.splitlines()
        self.assertEqual(linhas, [
            'comum :: payment:read',
            'forjado\\nadmin :: system:admin :: payment:read',
        ])
        self.assertNotIn('admin :: system:admin', linhas)


if __name__ == '__main__':
    unittest.main()
