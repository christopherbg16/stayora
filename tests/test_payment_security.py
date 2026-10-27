import os
import re
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault('SECRET_KEY', 'unit-test-only-secret-value-at-least-32-chars')

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'stayora'
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app import app
import payments
from decimal import Decimal


class TestUser:
    id = 7
    username = 'guest'
    is_authenticated = True

    def get_id(self):
        return str(self.id)


class PaymentSecurityTest(unittest.TestCase):
    def setUp(self):
        self.csrf_enabled = app.config.get('WTF_CSRF_ENABLED', True)

    def tearDown(self):
        app.config['WTF_CSRF_ENABLED'] = self.csrf_enabled

    def test_server_calculates_cash_total_from_database_rate_and_dates(self):
        app.config['WTF_CSRF_ENABLED'] = False
        check_in = (date.today() + timedelta(days=10)).isoformat()
        check_out = (date.today() + timedelta(days=12)).isoformat()
        room = SimpleNamespace(
            id=12,
            hotel_id=3,
            price=80,
            number=101,
            hotel=SimpleNamespace(review_status='approved'),
        )
        client = app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = '7'
            session['_fresh'] = True

        with patch('app.User.get', return_value=TestUser()), \
             patch('payments.Room.get', return_value=room), \
             patch('payments.check_room_conflict', return_value=False), \
             patch('payments.Reservation.create', return_value=object()) as create_reservation, \
             patch('payments.log_activity'):
            response = client.post('/payments/process-payment', data={
                'payment_method': 'cash',
                'booking_type': 'room',
                'booking_id': '12',
                'check_in': check_in,
                'check_out': check_out,
                'nights': '1',
                'total_price': '0.01',
            })

        self.assertEqual(response.status_code, 302)
        reservation = create_reservation.call_args.kwargs
        self.assertEqual(reservation['nights'], 2)
        self.assertEqual(reservation['total_price'], 160.0)
        self.assertTrue(reservation['payment_id'].startswith('CASH-'))

    def test_price_total_rounds_to_euro_cents(self):
        total, total_cents = payments._price_total('12.345', 2)

        self.assertEqual(total, Decimal('24.69'))
        self.assertEqual(total_cents, 2469)

    def test_success_page_does_not_create_a_reservation(self):
        app.config['WTF_CSRF_ENABLED'] = False
        client = app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = '7'
            session['_fresh'] = True
        checkout = SimpleNamespace(
            payment_status='paid',
            metadata={'user_id': '7', 'type': 'room'},
        )

        with patch('app.User.get', return_value=TestUser()), \
             patch('payments.stripe.checkout.Session.retrieve', return_value=checkout), \
             patch('payments.Reservation.find_by_payment_id', return_value=object()), \
             patch('payments.Reservation.create') as create_reservation:
            response = client.get('/payments/success?session_id=cs_test_session')

        self.assertEqual(response.status_code, 302)
        create_reservation.assert_not_called()

    def test_paid_stripe_webhook_creates_booking_without_csrf_token(self):
        app.config['WTF_CSRF_ENABLED'] = True
        client = app.test_client()
        event = {
            'type': 'checkout.session.completed',
            'data': {'object': {'id': 'cs_test_session', 'payment_status': 'paid'}},
        }
        with patch.object(payments.Config, 'STRIPE_WEBHOOK_SECRET', 'test-signing-secret'), \
             patch('payments.stripe.Webhook.construct_event', return_value=event), \
             patch('payments._create_paid_booking') as create_booking:
            response = client.post(
                '/payments/webhook',
                data=b'{}',
                headers={'Stripe-Signature': 'signed'},
            )

        self.assertEqual(response.status_code, 200)
        create_booking.assert_called_once_with(event['data']['object'])

    def test_paid_session_creates_booking_using_signed_amount_metadata(self):
        check_in = (date.today() + timedelta(days=10)).isoformat()
        check_out = (date.today() + timedelta(days=12)).isoformat()
        session = {
            'id': 'cs_test_paid',
            'payment_status': 'paid',
            'amount_total': 16000,
            'currency': 'eur',
            'metadata': {
                'type': 'room',
                'room_id': '12',
                'user_id': '7',
                'check_in': check_in,
                'check_out': check_out,
                'nights': '2',
                'total_price_cents': '16000',
            },
        }
        room = SimpleNamespace(
            id=12,
            hotel_id=3,
            price=80,
            number=101,
            hotel=SimpleNamespace(review_status='approved'),
        )
        with patch('payments.Reservation.find_by_payment_id', return_value=None), \
             patch('payments.Room.get', return_value=room), \
             patch('payments.check_room_conflict', return_value=False), \
             patch('payments.User.get', return_value=TestUser()), \
             patch('payments.Reservation.create', return_value=object()) as create_reservation, \
             patch('payments.log_activity'):
            payments._create_paid_booking(session)

        reservation = create_reservation.call_args.kwargs
        self.assertEqual(reservation['payment_id'], 'cs_test_paid')
        self.assertEqual(reservation['nights'], 2)
        self.assertEqual(reservation['total_price'], 160.0)
        self.assertEqual(reservation['payment_status'], 'paid')

    def test_csrf_protects_chat_but_exempts_signed_webhook_route(self):
        app.config['WTF_CSRF_ENABLED'] = True
        client = app.test_client()
        self.assertEqual(client.post('/api/chat', json={'message': ''}).status_code, 400)

        login_page = client.get('/auth/login')
        self.assertEqual(login_page.status_code, 200)
        token = re.search(rb'<meta name="csrf-token" content="([^"]+)"', login_page.data).group(1).decode()
        accepted = client.post(
            '/api/chat',
            json={'message': ''},
            headers={'X-CSRFToken': token},
        )
        self.assertEqual(accepted.status_code, 400)
        self.assertEqual(accepted.get_json()['error'], 'Message cannot be empty')

        with patch.object(payments.Config, 'STRIPE_WEBHOOK_SECRET', ''):
            webhook_response = client.post('/payments/webhook', data=b'{}')
        self.assertEqual(webhook_response.status_code, 503)

    def test_chat_rate_limit_is_ten_requests_per_minute(self):
        app.config['WTF_CSRF_ENABLED'] = False
        client = app.test_client()
        for _ in range(10):
            response = client.post(
                '/api/chat',
                json={'message': ''},
                environ_base={'REMOTE_ADDR': '192.0.2.10'},
            )
            self.assertEqual(response.status_code, 400)
        limited = client.post(
            '/api/chat',
            json={'message': ''},
            environ_base={'REMOTE_ADDR': '192.0.2.10'},
        )
        self.assertEqual(limited.status_code, 429)


if __name__ == '__main__':
    unittest.main()