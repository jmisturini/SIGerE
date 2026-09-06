"""Entrypoint da aplicação SIGERE.

Uso:
    python run.py                     # servidor de desenvolvimento (porta 5000)
    flask --app run db upgrade        # cria/atualiza o schema (Flask-Migrate/Alembic)
    flask --app run seed              # popula o banco com dados de demonstração
    flask --app run sync-permissions
    flask --app run db-legacy-upgrade # ponte p/ bancos anteriores ao Alembic
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    import os
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=5000)
