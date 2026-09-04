"""Entrypoint da aplicação SIGERE.

Uso:
    python run.py                 # servidor de desenvolvimento (porta 5000)
    flask --app run seed          # popula o banco com dados de demonstração
    flask --app run sync-permissions
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    import os
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=5000)
