import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        ##f'postgresql://sigere:sigere@localhost:5432/sigeredb'
        f'sqlite:///{os.path.join(BASE_DIR, "reservation.db")}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── Envio de e-mail (lista de compras) ──
    # Sem essas variáveis o botão de envio avisa que o e-mail não está configurado
    # e a lista continua disponível para copiar/imprimir.
    MAIL_HOST = os.environ.get('MAIL_HOST')          # ex: smtp.gmail.com
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USER = os.environ.get('MAIL_USER')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_FROM = os.environ.get('MAIL_FROM') or os.environ.get('MAIL_USER')
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'