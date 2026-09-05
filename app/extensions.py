from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Por favor, faça login para acessar esta página.'
login_manager.login_message_category = 'warning'

# Proteção CSRF GLOBAL: valida o token em TODA requisição POST (formulários
# WTForms via hidden_tag() e botões de ação via csrf_token() nos templates).
csrf = CSRFProtect()
