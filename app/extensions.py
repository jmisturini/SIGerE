from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Por favor, faça login para acessar esta página.'
login_manager.login_message_category = 'warning'

# Versionamento de schema (Alembic): `flask --app run db upgrade` cria/atualiza
# as tabelas; substitui o db.create_all() + ALTER TABLE artesanais do boot.
migrate = Migrate()

# Proteção CSRF GLOBAL: valida o token em TODA requisição POST (formulários
# WTForms via hidden_tag() e botões de ação via csrf_token() nos templates).
csrf = CSRFProtect()

# Rate limiting por IP (aplicado rota a rota, ex.: login).
limiter = Limiter(key_func=get_remote_address)
