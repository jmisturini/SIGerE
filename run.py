"""Entrypoint da aplicação SIGERE.

Uso:
    python run.py                     # servidor de desenvolvimento (porta 5000)
    flask --app run db upgrade        # cria o schema do zero / aplica migrações
    flask --app run seed-admin        # cria apenas o admin, solicitando a senha
    flask --app run seed              # popula o banco com dados iniciais (admin/admin123)
    flask --app run sync-permissions  # sincroniza permissões de módulos novos
    flask --app run seed-unidades     # cadastra as unidades do Senac SC (docs/unidades-senac-sc.json)
"""
from app import create_app, debug_enabled

app = create_app()

if __name__ == '__main__':
    app.run(debug=debug_enabled(), port=5000)
