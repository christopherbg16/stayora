import os
import random
import smtplib
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from urllib.parse import urlparse, urljoin

from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from models import User, log_activity
from forms import LoginForm, RegisterForm
from oauth_config import oauth

auth_bp = Blueprint('auth', __name__)


def _normalize_email(email):
    return (email or '').strip().lower()


def _generate_reset_code():
    return f"{random.randint(100000, 999999):06d}"


def _is_reset_code_valid(input_code, expected_code, expires_at):
    if not input_code or not expected_code or not expires_at:
        return False
    try:
        expires = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
    except ValueError:
        return False
    if expires < datetime.now():
        return False
    return str(input_code).strip() == str(expected_code).strip()


def _send_reset_code_email(email, code):
    smtp_host = os.getenv('SMTP_HOST') or os.getenv('MAIL_SERVER') or ''
    if not smtp_host:
        print(f"[Stayora Reset Password] Email for {email}: {code}", file=sys.stderr)
        return True

    smtp_port = int(os.getenv('SMTP_PORT') or os.getenv('MAIL_PORT') or '587')
    smtp_user = os.getenv('SMTP_USERNAME') or os.getenv('MAIL_USERNAME') or ''
    smtp_pass = os.getenv('SMTP_PASSWORD') or os.getenv('MAIL_PASSWORD') or ''
    from_email = os.getenv('SMTP_FROM_EMAIL') or os.getenv('MAIL_DEFAULT_SENDER') or 'noreply@stayora.local'
    use_tls = str(os.getenv('SMTP_USE_TLS', 'true')).lower() in {'1', 'true', 'yes', 'on'}

    msg = EmailMessage()
    msg['Subject'] = 'Stayora password reset code'
    msg['From'] = from_email
    msg['To'] = email
    msg.set_content(
        f"Your Stayora reset code is {code}. It is valid for 10 minutes.\n\n"
        "If you did not request this, you can ignore this email."
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            if use_tls:
                server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception as exc:
        print(f"[Stayora Reset Password] Failed to send email to {email}: {exc}", file=sys.stderr)
        print(f"[Stayora Reset Password] Fallback code for {email}: {code}", file=sys.stderr)
        return False


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


@auth_bp.route('/login', methods=['GET', 'POST'])
@auth_bp.route('/auth/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('user.dashboard'))

    form = LoginForm()
    next_page = request.args.get('next')

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        next_page = request.form.get('next') or next_page

        user = User.find_by_username(username)

        if user and user.password_hash and check_password_hash(user.password_hash, password):
            login_user(user)
            log_activity(f"User '{user.username}' logged in")

            if next_page and is_safe_url(next_page):
                return redirect(next_page)

            if user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('user.dashboard'))
        else:
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.login', next=next_page))

    return render_template('auth/login.html', form=form, next=next_page)


@auth_bp.route('/register', methods=['GET', 'POST'])
@auth_bp.route('/auth/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))

    form = RegisterForm()
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        account_type = request.form.get('account_type', 'user')

        if not username or len(username) < 3:
            flash('Username must be at least 3 characters', 'danger')
            return render_template('auth/register.html', form=form)

        if not password or len(password) < 6:
            flash('Password must be at least 6 characters', 'danger')
            return render_template('auth/register.html', form=form)

        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return render_template('auth/register.html', form=form)

        existing_user = User.find_by_username(username)
        if existing_user:
            flash('Username already exists', 'danger')
            return render_template('auth/register.html', form=form)

        role = 'admin' if account_type == 'admin' else 'user'

        try:
            User.create(
                username=username,
                password_hash=generate_password_hash(password),
                role=role,
                created_at=datetime.now().isoformat()
            )

            if role == 'admin':
                log_activity(f"New property owner '{username}' registered")
                flash('Account created successfully! You can now list your properties.', 'success')
            else:
                log_activity(f"New user '{username}' registered")
                flash('Account created successfully! You can now book your stays.', 'success')

            return redirect(url_for('auth.login'))
        except Exception as e:
            flash(f'Error creating account: {str(e)}', 'danger')

    return render_template('auth/register.html', form=form)


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))

    if request.method == 'POST':
        email = _normalize_email(request.form.get('email'))
        if not email:
            flash('Please enter your email address.', 'danger')
            return render_template('auth/forgot_password.html')

        user = User.find_by_email(email)
        if user and getattr(user, 'email', None):
            code = _generate_reset_code()
            session['reset_email'] = email
            session['reset_code'] = code
            session['reset_expires_at'] = (datetime.now() + timedelta(minutes=10)).isoformat()

            _send_reset_code_email(email, code)
            flash('A 6-digit verification code has been sent to your email.', 'success')
            return redirect(url_for('auth.reset_password'))

        flash('If an account exists for that email, a reset code will be sent.', 'info')
        return render_template('auth/forgot_password.html')

    return render_template('auth/forgot_password.html')


@auth_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if current_user.is_authenticated:
        return redirect(url_for('user.dashboard'))

    email = _normalize_email(request.args.get('email') or request.form.get('email') or session.get('reset_email'))
    if not email:
        flash('Please request a reset code first.', 'info')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        email = _normalize_email(request.form.get('email'))
        code = (request.form.get('verification_code') or '').strip()
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        expected_code = session.get('reset_code')
        expires_at = session.get('reset_expires_at')

        if not _is_reset_code_valid(code, expected_code, expires_at):
            flash('The verification code is invalid or expired. Please request a new one.', 'danger')
            return render_template('auth/reset_password.html', email=email)

        if len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template('auth/reset_password.html', email=email)

        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/reset_password.html', email=email)

        user = User.find_by_email(email)
        if not user:
            flash('We could not find that account. Please request a new reset code.', 'danger')
            return redirect(url_for('auth.forgot_password'))

        user.update(password_hash=generate_password_hash(new_password))
        session.pop('reset_email', None)
        session.pop('reset_code', None)
        session.pop('reset_expires_at', None)

        flash('Your password has been reset successfully. Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', email=email)


@auth_bp.route('/google-login')
def google_login():
    next_page = request.args.get('next')
    if next_page and is_safe_url(next_page):
        session['next'] = next_page
    redirect_uri = url_for('auth.google_callback', _external=True)
    import re
    redirect_uri = re.sub(r'://\d+\.\d+\.\d+\.\d+', '://localhost', redirect_uri)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route('/google-callback')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
        resp = oauth.google.get('userinfo')
        resp.raise_for_status()
        user_info = resp.json()

        google_id = user_info.get('sub') or user_info.get('id')
        email = user_info.get('email')
        name = user_info.get('name', '')

        if not google_id:
            flash('Could not get Google account information', 'danger')
            return redirect(url_for('auth.login'))

        user = User.find_by_google_id(google_id)

        if not user:
            if email:
                user = User.find_by_email(email)
                if user:
                    user.update(google_id=google_id)
                else:
                    username = email.split('@')[0] if email else f"user_{google_id[:8]}"
                    base_username = username
                    counter = 1
                    while User.find_by_username(username):
                        username = f"{base_username}{counter}"
                        counter += 1

                    user = User.create(
                        username=username,
                        email=email,
                        google_id=google_id,
                        role='user',
                        created_at=datetime.now().isoformat()
                    )
            else:
                username = f"user_{google_id[:8]}"
                base_username = username
                counter = 1
                while User.find_by_username(username):
                    username = f"{base_username}{counter}"
                    counter += 1

                user = User.create(
                    username=username,
                    google_id=google_id,
                    role='user',
                    created_at=datetime.now().isoformat()
                )

            log_activity(f"New user '{user.username}' signed up with Google")
        else:
            log_activity(f"User '{user.username}' logged in via Google")

        login_user(user)

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
