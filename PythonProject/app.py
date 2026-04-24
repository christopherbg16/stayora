from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_login import LoginManager
from models import db, User, Hotel
from auth import auth_bp
from admin import admin_bp
from user import user_bp
from config import Config
from oauth_config import init_oauth
from werkzeug.security import generate_password_hash
import os
import base64
from datetime import datetime

# Create Flask app
app = Flask(__name__)
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)

# ✅ Създаване на таблиците, ако не съществуват
with app.app_context():
    db.create_all()
    print("✓ Таблиците са синхронизирани с моделите!")

# Initialize Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'

# Initialize OAuth
init_oauth(app)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@login_manager.unauthorized_handler
def unauthorized():
    if request.is_json or (request.blueprint == 'user' and '/book' in request.path):
        return jsonify({'success': False, 'error': 'Authentication required', 'redirect': url_for('auth.login')}), 401
    return redirect(url_for('auth.login', next=request.url))


# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(user_bp)


# Custom template filters
@app.template_filter('b64encode')
def b64encode_filter(data):
    if data:
        return base64.b64encode(data).decode('utf-8')
    return ''


# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# Root route — public, shows featured properties
@app.route('/')
def index():
    hotels = Hotel.query.order_by(Hotel.avg_rating.desc()).limit(6).all()

    # Real-time stats
    total_properties = Hotel.query.count()
    total_users = User.query.count()
    total_hotels = Hotel.query.filter_by(property_type='hotel').count()
    total_apartments = Hotel.query.filter_by(property_type='apartment').count()
    total_villas = Hotel.query.filter_by(property_type='villa').count()
    total_resorts = Hotel.query.filter_by(property_type='resort').count()

    # Count unique countries
    total_countries = db.session.query(Hotel.country).distinct().count()

    return render_template('index.html',
                           hotels=hotels,
                           total_properties=total_properties,
                           total_users=total_users,
                           total_hotels=total_hotels,
                           total_apartments=total_apartments,
                           total_villas=total_villas,
                           total_resorts=total_resorts,
                           total_countries=total_countries)


# ✅ ТЕСТОВ МАРШРУТ - за проверка на връзката с базата данни
@app.route('/test-db')
def test_db():
    try:
        # Опитай да преброиш потребителите
        user_count = User.query.count()

        # Опитай да създадеш тестов потребител
        test_username = f"test_user_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        test_user = User(
            username=test_username,
            password_hash=generate_password_hash('test123'),
            role='user',
            created_at=datetime.now()
        )

        db.session.add(test_user)
        db.session.commit()

        new_count = User.query.count()

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
                <h2>Връзката с базата данни работи!</h2>
                <div class="info">
                    <p>Преди теста: <strong>{user_count}</strong> потребители</p>
                    <p>След теста: <strong>{new_count}</strong> потребители</p>
                </div>
                <div class="details">
                    <p><strong>Създаден тестов потребител:</strong> {test_username}</p>
                    <p><strong>Можеш да го видиш в phpMyAdmin:</strong> http://localhost/phpmyadmin</p>
                    <p><strong>База данни:</strong> register_user</p>
                    <p><strong>Таблица:</strong> users</p>
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
                <h2>Проблем с връзката с базата данни</h2>
                <div class="details">
                    <pre>{str(e)}</pre>
                </div>
                <p>Моля, провери:</p>
                <ul style="color: #94a3b8; text-align: left;">
                    <li>Дали MySQL сървърът работи (XAMPP/WAMP)</li>
                    <li>Дали базата 'register_user' съществува в phpMyAdmin</li>
                    <li>Дали няма парола за MySQL (в config.py)</li>
                </ul>
            </div>
        </body>
        </html>
        """


# Error handlers
@app.errorhandler(404)
def not_found_error(error):
    return "<h1>404 Page Not Found</h1><p>The page you're looking for doesn't exist.</p><a href='/'>Go Home</a>", 404


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('500.html'), 500


# Context processor to make 'now' available in all templates
@app.context_processor
def inject_now():
    return {'now': datetime.now()}


@app.template_filter('to_date')
def to_date_filter(date_string):
    """Конвертира стринг в date обект"""
    if date_string:
        return datetime.strptime(date_string, '%Y-%m-%d').date()
    return None


if __name__ == '__main__':
    app.run(debug=True)