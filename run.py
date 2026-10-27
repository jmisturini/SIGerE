"""Entrypoint da aplicação SIGERE.

Uso:
    python run.py                     # servidor de desenvolvimento (porta 5000)
    flask --app run db upgrade        # cria o schema do zero / aplica migrações
    flask --app run seed-admin        # cria apenas o admin, solicitando a senha
    flask --app run seed              # admin com senha aleatória (exibida uma vez) + dados iniciais
    flask --app run seed-demo         # cenário de demonstração completo (só em desenvolvimento)
    flask --app run sync-permissions  # sincroniza permissões de módulos novos
    flask --app run seed-unidades     # cadastra as unidades do Senac SC (docs/unidades-senac-sc.json)
    flask --app run backup            # backup do banco (gzip + retenção + upload para nuvem)
    flask --app run unlock-user EMAIL # desbloqueia conta travada (ex.: unlock-user admin@school.edu)
"""
from app import create_app, debug_enabled

app = create_app()

if __name__ == '__main__':
    app.run(debug=debug_enabled(), port=5000)
