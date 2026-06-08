from flask import Flask, render_template, request, jsonify, url_for, redirect, make_response
from flask_login import LoginManager
from models import User, Hotel, log_activity
from supabase_client import supabase
from auth import auth_bp
from admin import admin_bp
from user import user_bp
from payments import payments_bp
from config import Config
from oauth_config import init_oauth
import os
import base64
from datetime import datetime
import json

app = Flask(__name__)
app.config.from_object(Config)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'

init_oauth(app)


@login_manager.user_loader
def load_user(user_id):
    return User.get(int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    if request.is_json or (request.blueprint == 'user' and '/book' in request.path):
        return jsonify({'success': False, 'error': 'Authentication required', 'redirect': url_for('auth.login')}), 401
    return redirect(url_for('auth.login', next=request.url))


app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(user_bp)
app.register_blueprint(payments_bp)


@app.template_filter('b64encode')
def b64encode_filter(data):
    if not data:
        return ''
    # If the value is already a string (e.g. base64 text stored in DB), return it unchanged
    if isinstance(data, str):
        return data
    # If it's bytes-like, encode to base64 text
    try:
        return base64.b64encode(data).decode('utf-8')
    except TypeError:
        # Fallback: convert to string and encode
        return base64.b64encode(str(data).encode('utf-8')).decode('utf-8')


# Simple translation loader
_translation_cache = {}

def load_translations(lang):
    if lang in _translation_cache:
        return _translation_cache[lang]
    path = os.path.join(os.path.dirname(__file__), 'translations', f'{lang}.json')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        data = {}
    _translation_cache[lang] = data
    return data


@app.template_filter('t')
def translate_filter(text):
    lang = request.cookies.get('site_lang', 'en')
    trans = load_translations(lang)
    return trans.get(text, text)


os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


@app.route('/')
def index():
    data = supabase.table('hotels').select('*').order('avg_rating', desc=True).limit(6).execute()
    hotels_data = data.data or []

    total_properties = Hotel.count()
    total_users = User.count()
    total_hotels = Hotel.count_by_type('hotel')
    total_apartments = Hotel.count_by_type('apartment')
    total_villas = Hotel.count_by_type('villa')
    total_resorts = Hotel.count_by_type('resort')
    total_countries = Hotel.count_distinct_countries()

    hotels = []
    for h in hotels_data:
        hotel = Hotel(h)
        hotels.append(hotel)

    return render_template('index.html',
                           hotels=hotels,
                           total_properties=total_properties,
                           total_users=total_users,
                           total_hotels=total_hotels,
                           total_apartments=total_apartments,
                           total_villas=total_villas,
                           total_resorts=total_resorts,
                           total_countries=total_countries)


@app.route('/test-db')
def test_db():
    try:
        user_count = User.count()
        test_username = f"test_user_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        import secrets
        from werkzeug.security import generate_password_hash
        test_user = User.create(
            username=test_username,
            password_hash=generate_password_hash('test123'),
            role='user',
            created_at=datetime.now().isoformat()
        )
        new_count = User.count()
        return f"""
        <html>
        <head>
            <title>Database Test</title>
            <style>
                body {{ 
                    background: #0f172a; 
                    color: #f8fafc; 
                    font-family: 'Segoe UI', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                }}
                .card {{
                    background: #1e293b;
                    padding: 2rem;
                    border-radius: 1rem;
                    box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);
                    max-width: 600px;
                    text-align: center;
                }}
                .success {{ color: #10b981; font-size: 3rem; margin-bottom: 1rem; }}
                .info {{ color: #94a3b8; margin: 1rem 0; }}
                .details {{ 
                    background: #334155; 
                    padding: 1rem; 
                    border-radius: 0.5rem; 
                    text-align: left;
                    margin: 1rem 0;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="success">✓ УСПЕХ!</div>
                <h2>Supabase връзката работи!</h2>
                <div class="info">
                    <p>Преди теста: <strong>{user_count}</strong> потребители</p>
                    <p>След теста: <strong>{new_count}</strong> потребители</p>
                </div>
                <div class="details">
                    <p><strong>Създаден тестов потребител:</strong> {test_username}</p>
                </div>
                <p>✅ Сега новите потребители ще се записват успешно!</p>
            </div>
        </body>
        </html>
        """
    except Exception as e:
        return f"""
        <html>
        <head>
            <title>Database Test - Error</title>
            <style>
                body {{ 
                    background: #0f172a; 
                    color: #f8fafc; 
                    font-family: 'Segoe UI', sans-serif;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    height: 100vh;
                    margin: 0;
                }}
                .card {{
                    background: #1e293b;
                    padding: 2rem;
                    border-radius: 1rem;
                    box-shadow: 0 25px 50px -12px rgba(0,0,0,0.5);
                    max-width: 600px;
                }}
                .error {{ color: #ef4444; font-size: 3rem; margin-bottom: 1rem; }}
                .details {{ 
                    background: #334155; 
                    padding: 1rem; 
                    border-radius: 0.5rem; 
                    text-align: left;
                    margin: 1rem 0;
                    color: #f87171;
                    overflow-x: auto;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="error">✗ ГРЕШКА</div>
                <h2>Проблем с връзката със Supabase</h2>
                <div class="details">
                    <pre>{str(e)}</pre>
                </div>
                <p>Моля, провери:</p>
                <ul style="color: #94a3b8; text-align: left;">
                    <li>Дали .env файлът съдържа правилните Supabase URL и Key</li>
                    <li>Дали таблиците са създадени в Supabase (SQL Editor)</li>
                </ul>
            </div>
        </body>
        </html>
        """


@app.errorhandler(404)
def not_found_error(error):
    return render_template('404.html'), 404


@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500


@app.context_processor
def inject_now():
    return {'now': datetime.now()}


@app.template_filter('to_date')
def to_date_filter(date_string):
    if date_string:
        return datetime.strptime(date_string, '%Y-%m-%d').date()
    return None


# Supported languages
LANGUAGES = {'en': 'English', 'bg': 'Български', 'es': 'Español', 'de': 'Deutsch'}

@app.context_processor
def inject_language():
    # Provide current language and available languages to all templates
    lang = request.cookies.get('site_lang', 'en')
    if lang not in LANGUAGES:
        lang = 'en'
    return {'current_language': lang, 'languages': LANGUAGES}


@app.route('/set-language/<lang>')
def set_language(lang):
    if lang not in LANGUAGES:
        lang = 'en'
    next_url = request.referrer or url_for('index')
    resp = make_response(redirect(next_url))
    resp.set_cookie('site_lang', lang, max_age=30*24*3600, samesite='Lax')
    return resp


@app.route('/api/chat', methods=['POST'])
def chat_api():
    from chatbot import process_message
    data = request.get_json(silent=True)
    if not data or 'message' not in data:
        return jsonify({'error': 'Message required'}), 400
    message = data['message'].strip()
    if not message:
        return jsonify({'error': 'Message cannot be empty'}), 400
    session_id = data.get('session_id')
    try:
        response = process_message(message, session_id=session_id)
        return jsonify(response)
    except Exception as e:
        return jsonify({'error': str(e), 'text': 'Sorry, something went wrong.'}), 500


@app.route('/api/chat/session', methods=['GET'])
def chat_session():
    from flask_login import current_user
    return jsonify({
        'authenticated': current_user.is_authenticated,
        'username': getattr(current_user, 'username', None),
        'role': getattr(current_user, 'role', None),
    })

if __name__ == '__main__':
    app.run(debug=True)
