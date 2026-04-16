import os


class Config:
    SECRET_KEY = 'your-secret-key-change-this-in-production'
    SQLALCHEMY_DATABASE_URI = 'mysql+pymysql://root:@localhost:3307/register_user'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload settings
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static/uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # Google OAuth settings
    GOOGLE_CLIENT_ID = 'your-google-client-id.apps.googleusercontent.com'
    GOOGLE_CLIENT_SECRET = 'your-google-client-secret'