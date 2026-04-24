from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Activity
from forms import LoginForm, RegisterForm
from oauth_config import oauth  # Add this import
from datetime import datetime
from urllib.parse import urlparse, urljoin

auth_bp = Blueprint('auth', __name__)


def is_safe_url(target):
    """Check if the redirect URL is safe (same host)."""
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


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


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        else:
            return redirect(url_for('user.dashboard'))

    form = LoginForm()
    next_page = request.args.get('next')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        next_page = request.form.get('next') or next_page

        user = User.query.filter_by(username=username).first()

        if user and user.password_hash and check_password_hash(user.password_hash, password):
            login_user(user)
            log_activity(f"User '{user.username}' logged in")

            if next_page and is_safe_url(next_page):
                return redirect(next_page)

            if user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            else:
                return redirect(url_for('user.dashboard'))
        else:
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.login', next=next_page))

    return render_template('auth/login.html', form=form, next=next_page)


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))

    form = RegisterForm()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        account_type = request.form.get('account_type', 'user')  # Default to 'user'

        # Validation
        if not username or len(username) < 3:
            flash('Username must be at least 3 characters', 'danger')
            return render_template('auth/register.html', form=form)

        if not password or len(password) < 6:
            flash('Password must be at least 6 characters', 'danger')
            return render_template('auth/register.html', form=form)

        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return render_template('auth/register.html', form=form)

        # Check if username exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists', 'danger')
            return render_template('auth/register.html', form=form)

        # Create new user with the selected role
        role = 'admin' if account_type == 'admin' else 'user'

        user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role=role,
            created_at=datetime.now()
        )

        try:
            db.session.add(user)
            db.session.commit()

            if role == 'admin':
                log_activity(f"New property owner '{user.username}' registered")
                flash('Account created successfully! You can now list your properties.', 'success')
            else:
                log_activity(f"New user '{user.username}' registered")
                flash('Account created successfully! You can now book your stays.', 'success')

            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating account: {str(e)}', 'danger')

    return render_template('auth/register.html', form=form)

@auth_bp.route('/google-login')
def google_login():
    next_page = request.args.get('next')
    if next_page and is_safe_url(next_page):
        session['next'] = next_page

    redirect_uri = url_for('auth.google_callback', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/google-callback')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        user_info = oauth.google.parse_id_token(token)

        if not user_info:
            # Try getting user info from API
            resp = oauth.google.get('userinfo')
            user_info = resp.json()

        google_id = user_info.get('sub') or user_info.get('id')
        email = user_info.get('email')
        name = user_info.get('name', '')

        if not google_id:
            flash('Could not get Google account information', 'danger')
            return redirect(url_for('auth.login'))

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
            else:
                # No email, create with google_id
                username = f"user_{google_id[:8]}"
                base_username = username
                counter = 1
                while User.query.filter_by(username=username).first():
                    username = f"{base_username}{counter}"
                    counter += 1

                user = User(
                    username=username,
                    google_id=google_id,
                    role='user',
                    created_at=datetime.now()
                )
                db.session.add(user)

            db.session.commit()
            log_activity(f"New user '{user.username}' signed up with Google")

        login_user(user)
        log_activity(f"User '{user.username}' logged in via Google")

        next_page = session.pop('next', None) or request.args.get('next')
        if next_page and is_safe_url(next_page):
            return redirect(next_page)

        if user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.dashboard'))

    except Exception as e:
        flash(f'Google login failed: {str(e)}', 'danger')
        return redirect(url_for('auth.login'))


@auth_bp.route('/logout')
@login_required
def logout():
    log_activity(f"User '{current_user.username}' logged out")
    logout_user()
    flash('You have been logged out', 'info')
    return redirect(url_for('auth.login'))