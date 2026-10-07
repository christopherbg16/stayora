import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-this-in-production-2025'

    # Upload settings
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Google OAuth settings
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID') or ''
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET') or ''

    # Stripe settings
    STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY') or ''
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY') or ''

    # Gemini
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY') or ''

    # Email / reset password settings
    MAIL_SERVER = os.environ.get('SMTP_HOST') or os.environ.get('MAIL_SERVER') or ''
    MAIL_PORT = int(os.environ.get('SMTP_PORT') or os.environ.get('MAIL_PORT') or 587)
    MAIL_USERNAME = os.environ.get('SMTP_USERNAME') or os.environ.get('MAIL_USERNAME') or ''
    MAIL_PASSWORD = os.environ.get('SMTP_PASSWORD') or os.environ.get('MAIL_PASSWORD') or ''
    MAIL_USE_TLS = str(os.environ.get('SMTP_USE_TLS', 'true')).lower() in {'1', 'true', 'yes', 'on'}
    MAIL_DEFAULT_SENDER = os.environ.get('SMTP_FROM_EMAIL') or os.environ.get('MAIL_DEFAULT_SENDER') or 'noreply@stayora.local'
