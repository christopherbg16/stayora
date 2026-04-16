from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Activity
from forms import LoginForm, RegisterForm
from datetime import datetime
from authlib.integrations.flask_client import OAuth
import secrets

auth_bp = Blueprint('auth', __name__)

# Setup OAuth
oauth = OAuth()


def init_oauth(app):
    oauth.init_app(app)
    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile',
            'prompt': 'select_account'
        }
    )


def log_activity(activity_text):
    """Log activity to database"""
    try:
        activity = Activity(
            activity=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {activity_text}",
            timestamp=datetime.now()
        )
        db.session.add(activity)
        db.session.commit()
    except:
        db.session.rollback()


# ... existing login and register routes ...

@auth_bp.route('/google-login')
def google_login():
    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/google-callback')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.parse_id_token(token)

        google_id = user_info['sub']
        email = user_info.get('email')
        name = user_info.get('name')
        picture = user_info.get('picture')

        # Check if user exists by google_id
        user = User.query.filter_by(google_id=google_id).first()

        if not user:
            # Check if user exists by email
            if email:
                user = User.query.filter_by(email=email).first()
                if user:
                    # Link Google account to existing user
                    user.google_id = google_id
                else:
                    # Create new user
                    username = email.split('@')[0] if email else f"user_{google_id[:8]}"
                    # Ensure username is unique
                    base_username = username
                    counter = 1
                    while User.query.filter_by(username=username).first():
                        username = f"{base_username}{counter}"
                        counter += 1

                    user = User(
                        username=username,
                        email=email,
                        google_id=google_id,
                        role='user',
                        created_at=datetime.now()
                    )
                    db.session.add(user)

            db.session.commit()
            log_activity(f"New user '{user.username}' signed up with Google")

        login_user(user)
        log_activity(f"User '{user.username}' logged in via Google")

        if user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.dashboard'))

    except Exception as e:
        flash(f'Google login failed: {str(e)}', 'danger')
        return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('user.dashboard'))

    # Създаваме празна форма за GET заявката
    form = LoginForm()

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            log_activity(f"User '{user.username}' logged in")

            if user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('user.dashboard'))
        else:
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.login'))

    # Задължително подаваме form на шаблона
    return render_template('auth/login.html', form=form)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))

    form = RegisterForm()
    if form.validate_on_submit():
        # Check if username exists
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_user:
            flash('Username already exists', 'danger')
            return render_template('auth/register.html', form=form)

        # Create new user - БЕЗ is_admin!
        user = User(
            username=form.username.data,
            password_hash=generate_password_hash(form.password.data),
            role='user',
            created_at=datetime.now()
        )

        try:
            db.session.add(user)
            db.session.commit()
            log_activity(f"New user '{user.username}' registered")
            flash('Account created successfully! You can now login.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating account: {str(e)}', 'danger')

    return render_template('auth/register.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    log_activity(f"User '{current_user.username}' logged out")
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login'))