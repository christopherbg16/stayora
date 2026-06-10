import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-this-in-production-2025'

    # Upload settings
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Google OAuth settings
    GOOGLE_CLIENT_ID = 'YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com'
    GOOGLE_CLIENT_SECRET = 'YOUR_GOOGLE_CLIENT_SECRET'

    # Stripe settings
    STRIPE_PUBLIC_KEY = os.environ.get('STRIPE_PUBLIC_KEY') or 'pk_test_XXXXXXXXXXXXXXXXXXXXX'
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY') or 'sk_test_XXXXXXXXXXXXXXXXXXXXX'

    # OpenAI
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') or ''
