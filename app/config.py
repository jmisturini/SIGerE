import os

# Raiz do projeto (o pacote app/ vive um nível abaixo) — é onde o SQLite persiste.
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        ##f'postgresql://sigere:sigere@localhost:5432/sigeredb'
        f'sqlite:///{os.path.join(BASE_DIR, "reservation.db")}'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Rejeita uploads/requisições maiores que 16 MB (proteção contra DoS por upload)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    # Mitiga CSRF em navegação cross-site em complemento ao token do Flask-WTF
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Rate limiting (storage em memória é suficiente para 1 processo;
    # para múltiplos workers, aponte RATELIMIT_STORAGE_URI para Redis)
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    # Localização do totem/portal para o clima (Open-Meteo). Ajuste por env var.
    TOTEM_LATITUDE = float(os.environ.get('TOTEM_LATITUDE', '-23.5505'))
    TOTEM_LONGITUDE = float(os.environ.get('TOTEM_LONGITUDE', '-46.6333'))