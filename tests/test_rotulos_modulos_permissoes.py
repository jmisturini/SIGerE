"""Rótulos dos grupos de permissão no painel de papéis.

Cada módulo de permissão precisa de rótulo em MODULO_LABELS (app/admin):
sem ele o grupo cai no fallback ``modulo.title()`` e aparece em inglês
("Meal", "Course Type", "Notification", "Api").
"""
import os
import re
import tempfile
import unittest

from app import create_app
from app.commands import _seed_permissions
from app.config import Config
from app.extensions import db
from app.models import Permission, Role, Unity, User

EMAIL = 'gestor@escola.edu'
PASSWORD = 'SenhaForte123'


class TestConfig(Config):
    SECRET_KEY = 'chave-de-teste-nao-usar-o-valor-dev'
    TESTING = True
    WTF_CSRF_ENABLED = False
    RATELIMIT_ENABLED = False


class RotulosModulosPermissoesTestCase(unittest.TestCase):
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
            db.session.commit()
            _seed_permissions()
            db.session.commit()

            perms = [Permission.query.filter_by(code=c).first()
                     for c in ('role:read', 'role:create')]
            papel = Role(name='gestor-papeis', label='Gestor de Papéis',
                         permissions=perms)
            db.session.add(papel)
            db.session.flush()

            user = User(
                email=EMAIL, full_name='Gestor Teste', role='room',
                profile_type='employee', unities=[self.unity],
                role_id=papel.id, force_password_change=False,
                is_active_user=True,
            )
            user.set_password(PASSWORD)
            db.session.add(user)
            db.session.commit()

        response = self.client.post('/login', data={'email': EMAIL,
                                                    'password': PASSWORD},
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

    def _rotulos_de_grupos(self, page):
        """Cabeçalhos dos grupos de permissão do formulário de papéis."""
        return re.findall(
            r'<span class="fw-bold small text-uppercase">([^<]+)</span>', page)

    def test_grupos_de_permissoes_em_portugues(self):
        """Todo módulo de permissão tem rótulo próprio — nenhum grupo
        aparece com o nome em inglês do fallback title()."""
        response = self.client.get('/admin/roles/create')
        self.assertEqual(response.status_code, 200)
        rotulos = self._rotulos_de_grupos(response.get_data(as_text=True))

        self.assertIn('Vale Alimentação', rotulos)
        self.assertIn('Tipos de Curso', rotulos)
        self.assertIn('Notificações', rotulos)
        self.assertIn('API', rotulos)
        for estrangeiro in ('Meal', 'Course Type', 'Notification', 'Api'):
            self.assertNotIn(estrangeiro, rotulos)

    def test_modulos_cobertos_por_um_rotulo(self):
        """Guarda estrutural: todo módulo em PERMISSION_DATA tem entrada
        em MODULO_LABELS — novo módulo criado atualiza os dois lugares."""
        from app.blueprints.admin import MODULO_LABELS
        from app.commands import PERMISSION_DATA

        modulos = {module for _, module, _, _ in PERMISSION_DATA}
        self.assertEqual(modulos, set(MODULO_LABELS))


if __name__ == '__main__':
    unittest.main()
