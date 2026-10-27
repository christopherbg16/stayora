from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import Reservation, PropertyReservation, Room, Hotel, log_activity, \
    User, check_room_conflict, check_property_conflict
from config import Config
import stripe
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
import uuid

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')
logger = logging.getLogger(__name__)


class BookingConflict(Exception):
    pass


def _checkout_dates(check_in, check_out=None, nights=1):
    try:
        start = datetime.strptime(check_in, '%Y-%m-%d').date() if check_in else date.today()
        if check_out:
            end = datetime.strptime(check_out, '%Y-%m-%d').date()
        else:
            end = start + timedelta(days=int(nights or 1))
    except (TypeError, ValueError):
        raise ValueError('Choose valid check-in and check-out dates.') from None

    duration = (end - start).days
    if start < date.today() or duration < 1 or duration > 365:
        raise ValueError('Choose valid dates for a stay of 1 to 365 nights.')
    return start, end, duration


def _price_total(price_per_night, nights):
    try:
        total = (Decimal(str(price_per_night)) * nights).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
    except Exception:
        raise ValueError('This property has an invalid nightly price.') from None
    if total < 0:
        raise ValueError('This property has an invalid nightly price.')
    return total, int(total * 100)


def _session_value(session, key, default=None):
    if isinstance(session, dict):
        return session.get(key, default)
    return getattr(session, key, default)


def _stripe_error_code(error):
    code = getattr(error, 'code', None)
    if code:
        return code
    details = getattr(error, 'json', None)
    if isinstance(details, dict):
        return details.get('code') or (details.get('details') or {}).get('code')
    return None


def _create_paid_booking(session):
    session_id = _session_value(session, 'id')
    if not session_id:
        raise ValueError('Stripe session has no ID.')
    metadata = _session_value(session, 'metadata', {}) or {}
    booking_type = metadata.get('type')
    user_id = int(metadata.get('user_id'))
    check_in, check_out, nights = _checkout_dates(
        metadata.get('check_in'), metadata.get('check_out'), metadata.get('nights', 1)
    )

    if booking_type == 'room':
        room_id = int(metadata.get('room_id'))
        model = Reservation
        existing = model.find_by_payment_id(session_id)
        if existing:
            return existing
        room = Room.get(room_id)
        if not room or not _listing_is_approved(room.hotel):
            raise BookingConflict('The room is no longer available.')
        if check_room_conflict(room_id, check_in, check_out):
            raise BookingConflict('The room was booked before payment completed.')
        price_per_night = room.price
        reservation_data = {'room_id': room_id}
        activity = f"User booked Room #{room.number} (Card payment)"
    elif booking_type == 'property':
        property_id = int(metadata.get('property_id'))
        model = PropertyReservation
        existing = model.find_by_payment_id(session_id)
        if existing:
            return existing
        hotel = Hotel.get(property_id)
        if not _listing_is_approved(hotel):
            raise BookingConflict('The property is no longer available.')
        if check_property_conflict(property_id, check_in, check_out):
            raise BookingConflict('The property was booked before payment completed.')
        price_per_night = hotel.price_per_night or 0
        reservation_data = {'property_id': property_id}
        activity = f"User booked '{hotel.name}' (Card payment)"
    else:
        raise ValueError('Unknown booking type in Stripe session.')

    user = User.get(user_id)
    if not user:
        raise ValueError('The booking user no longer exists.')
    _, calculated_total_cents = _price_total(price_per_night, nights)
    total_cents = int(metadata.get('total_price_cents', calculated_total_cents))
    if total_cents < 0:
        raise ValueError('Stripe session has an invalid total price.')
    if total_cents != calculated_total_cents:
        raise ValueError('Stripe session total does not match the current listing price.')
    total = Decimal(total_cents) / 100
    amount_total = _session_value(session, 'amount_total')
    currency = _session_value(session, 'currency')
    if amount_total is not None and int(amount_total) != total_cents:
        raise ValueError('Stripe session total does not match the current listing price.')
    if currency and currency.lower() != 'eur':
        raise ValueError('Stripe session currency is not supported.')

    reservation_data.update(
        guest=user.username,
        user_id=user_id,
        start_date=check_in.isoformat(),
        nights=nights,
        total_price=float(total),
        payment_status='paid',
        payment_id=session_id,
    )
    try:
        created = model.create(**reservation_data)
    except Exception as exc:
        if _stripe_error_code(exc) == '23P01':
            raise BookingConflict('The dates were booked before payment completed.') from exc
        raise
    if not created:
        raise RuntimeError('Reservation insert returned no row.')
    log_activity(f"User '{user.username}' {activity}")
    return created


def _refund_checkout_session(session):
    payment_intent = _session_value(session, 'payment_intent')
    if not payment_intent:
        raise RuntimeError('Paid checkout session has no payment intent to refund.')
    stripe.Refund.create(
        payment_intent=payment_intent,
        idempotency_key=f"booking-conflict-refund-{_session_value(session, 'id')}",
    )


def _stripe_enabled():
    secret = (Config.STRIPE_SECRET_KEY or '').strip()
    placeholder_values = {
        'sk_test_XXXXXXXXXXXXXXXXXXXXX',
        'pk_test_XXXXXXXXXXXXXXXXXXXXX',
        'sk_live_XXXXXXXXXXXXXXXXXXXXX',
        'pk_live_XXXXXXXXXXXXXXXXXXXXX',
    }
    return bool(secret) and secret not in placeholder_values


stripe.api_key = Config.STRIPE_SECRET_KEY if _stripe_enabled() else ''


def _listing_is_approved(hotel):
    return hotel is not None and getattr(hotel, 'review_status', None) == 'approved'


@payments_bp.route('/checkout/room/<int:room_id>', methods=['GET', 'POST'])
@login_required
def checkout_room(room_id):
    room = Room.get(room_id)
    if not room:
        flash('Room not found', 'danger')
        return redirect(url_for('user.browse_stays'))
    hotel = room.hotel
    if not _listing_is_approved(hotel):
        flash('This property is not currently available for booking.', 'warning')
        return redirect(url_for('user.browse_stays'))

    try:
        check_in_date, check_out_date, nights = _checkout_dates(
            request.args.get('check_in'), request.args.get('check_out'),
            request.args.get('nights', 1, type=int),
        )
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('user.hotel_detail', hotel_id=hotel.id))
    check_in = check_in_date.isoformat()
    check_out = check_out_date.isoformat()

    if check_room_conflict(room.id, check_in_date, check_out_date):
        flash('Sorry, this room is no longer available for the selected dates.', 'danger')
        return redirect(url_for('user.hotel_detail', hotel_id=hotel.id))

    total, total_cents = _price_total(room.price, nights)
    total_price = float(total)

    if request.method == 'POST':
        if not _stripe_enabled():
            flash('Card payments are currently in demo mode. Please choose cash payment or add real Stripe keys to enable card checkout.', 'info')
            return redirect(url_for('payments.checkout_room', room_id=room_id, check_in=check_in, check_out=check_out, nights=nights))
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'eur',
                        'product_data': {
                            'name': f'Room #{room.number} - {hotel.name}',
                            'description': f'Room #{room.number} · {nights} night(s) · {hotel.city}, {hotel.country}',
                        },
                        'unit_amount': total_cents,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=url_for('payments.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('payments.cancel', _external=True),
                metadata={
                    'room_id': str(room_id),
                    'user_id': str(current_user.id),
                    'check_in': check_in,
                    'check_out': check_out,
                    'nights': str(nights),
                    'total_price_cents': str(total_cents),
                    'type': 'room'
                }
            )
            return redirect(checkout_session.url, code=303)
        except Exception as e:
            flash(f'Payment error: {str(e)}', 'danger')
            return redirect(url_for('user.hotel_detail', hotel_id=hotel.id))

    return render_template('payments/checkout.html',
                           room=room,
                           hotel=hotel,
                           check_in=check_in,
                           check_out=check_out,
                           nights=nights,
                           total_price=total_price,
                           stripe_public_key=Config.STRIPE_PUBLIC_KEY,
                           stripe_enabled=_stripe_enabled())


@payments_bp.route('/checkout/property/<int:property_id>', methods=['GET', 'POST'])
@login_required
def checkout_property(property_id):
    hotel = Hotel.get(property_id)
    if not hotel:
        flash('Property not found', 'danger')
        return redirect(url_for('user.browse_stays'))
    if not _listing_is_approved(hotel):
        flash('This property is not currently available for booking.', 'warning')
        return redirect(url_for('user.browse_stays'))

    try:
        check_in_date, check_out_date, nights = _checkout_dates(
            request.args.get('check_in'), request.args.get('check_out'),
            request.args.get('nights', 1, type=int),
        )
    except ValueError as exc:
        flash(str(exc), 'danger')
        return redirect(url_for('user.hotel_detail', hotel_id=property_id))
    check_in = check_in_date.isoformat()
    check_out = check_out_date.isoformat()

    if check_property_conflict(property_id, check_in_date, check_out_date):
        flash('Sorry, this property is no longer available for the selected dates.', 'danger')
        return redirect(url_for('user.hotel_detail', hotel_id=property_id))

    total, total_cents = _price_total(hotel.price_per_night or 0, nights)
    total_price = float(total)

    if request.method == 'POST':
        if not _stripe_enabled():
            flash('Card payments are currently in demo mode. Please choose cash payment or add real Stripe keys to enable card checkout.', 'info')
            return redirect(url_for('payments.checkout_property', property_id=property_id, check_in=check_in, check_out=check_out, nights=nights))
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'eur',
                        'product_data': {
                            'name': f'{hotel.name} - {hotel.property_type.title()}',
                            'description': f'Entire {hotel.property_type} · {nights} night(s) · {hotel.city}, {hotel.country}',
                        },
                        'unit_amount': total_cents,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=url_for('payments.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('payments.cancel', _external=True),
                metadata={
                    'property_id': str(property_id),
                    'user_id': str(current_user.id),
                    'check_in': check_in,
                    'check_out': check_out,
                    'nights': str(nights),
                    'total_price_cents': str(total_cents),
                    'type': 'property'
                }
            )
            return redirect(checkout_session.url, code=303)
        except Exception as e:
            flash(f'Payment error: {str(e)}', 'danger')
            return redirect(url_for('user.hotel_detail', hotel_id=property_id))

    return render_template('payments/checkout.html',
                           hotel=hotel,
                           check_in=check_in,
                           check_out=check_out,
                           nights=nights,
                           total_price=total_price,
                           stripe_public_key=Config.STRIPE_PUBLIC_KEY,
                           stripe_enabled=_stripe_enabled())


@payments_bp.route('/success')
@login_required
def success():
    session_id = request.args.get('session_id')
    if not session_id:
        return redirect(url_for('user.dashboard'))

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        metadata = _session_value(session, 'metadata', {}) or {}
        if str(metadata.get('user_id')) != str(current_user.id):
            return redirect(url_for('user.dashboard'))
        if _session_value(session, 'payment_status') != 'paid':
            flash('Your payment was not completed, so no booking was made.', 'warning')
            return redirect(url_for('user.dashboard'))

        booking_type = metadata.get('type')
        existing = (
            Reservation.find_by_payment_id(session_id)
            if booking_type == 'room'
            else PropertyReservation.find_by_payment_id(session_id)
            if booking_type == 'property'
            else None
        )
        if existing:
            flash('Payment successful and your booking is confirmed.', 'success')
        else:
            flash('Payment received. Your booking confirmation is processing.', 'info')
        return redirect(url_for('user.my_reservations'))
    except Exception:
        logger.exception('Could not confirm Stripe checkout session %s', session_id)
        flash('We could not confirm the payment status. Please check your reservations or contact support.', 'warning')
        return redirect(url_for('user.dashboard'))


@payments_bp.route('/cancel')
def cancel():
    flash('Payment was cancelled. Your booking was not completed.', 'warning')
    return redirect(url_for('user.browse_stays'))


@payments_bp.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = getattr(Config, 'STRIPE_WEBHOOK_SECRET', '')
    if not endpoint_secret:
        return jsonify({'error': 'Webhook is not configured'}), 503

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError:
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400

    if event['type'] not in {
        'checkout.session.completed',
        'checkout.session.async_payment_succeeded',
    }:
        return jsonify({'status': 'ignored'}), 200

    session = event['data']['object']
    if _session_value(session, 'payment_status') != 'paid':
        return jsonify({'status': 'payment_pending'}), 200

    try:
        _create_paid_booking(session)
    except BookingConflict:
        try:
            _refund_checkout_session(session)
        except Exception:
            logger.exception('Could not refund unavailable booking for session %s', _session_value(session, 'id'))
            return jsonify({'error': 'Booking unavailable; refund needs retry'}), 500
        logger.warning('Refunded paid checkout for unavailable inventory: %s', _session_value(session, 'id'))
    except ValueError:
        try:
            _refund_checkout_session(session)
        except Exception:
            logger.exception('Could not refund invalid paid checkout session %s', _session_value(session, 'id'))
            return jsonify({'error': 'Invalid booking; refund needs retry'}), 500
        logger.warning('Refunded invalid paid checkout session %s', _session_value(session, 'id'))
    except Exception as exc:
        if _stripe_error_code(exc) == '23505':
            session_id = _session_value(session, 'id')
            metadata = _session_value(session, 'metadata', {}) or {}
            booking_type = metadata.get('type')
            existing = (
                Reservation.find_by_payment_id(session_id)
                if booking_type == 'room'
                else PropertyReservation.find_by_payment_id(session_id)
                if booking_type == 'property'
                else None
            )
            if existing:
                return jsonify({'status': 'already_processed'}), 200
        logger.exception('Could not create booking from Stripe checkout session %s', _session_value(session, 'id'))
        return jsonify({'error': 'Booking processing failed'}), 500

    return jsonify({'status': 'success'}), 200


@payments_bp.route('/process-payment', methods=['POST'])
@login_required
def process_payment():
    try:
        payment_method = request.form.get('payment_method')
        booking_type = request.form.get('booking_type')
        booking_id = int(request.form.get('booking_id', ''))
        check_in_date, check_out_date, nights = _checkout_dates(
            request.form.get('check_in'), request.form.get('check_out')
        )
        check_in = check_in_date.isoformat()
        check_out = check_out_date.isoformat()
        if payment_method not in {'card', 'cash'}:
            raise ValueError('Choose a valid payment method.')

        if booking_type == 'room':
            room = Room.get(booking_id)
            if not room:
                flash('Room not found.', 'danger')
                return redirect(url_for('user.browse_stays'))
            if not _listing_is_approved(room.hotel):
                flash('This property is not currently available for booking.', 'warning')
                return redirect(url_for('user.browse_stays'))

            if check_room_conflict(booking_id, check_in_date, check_out_date):
                flash('Sorry, this room was just booked for those dates. Please choose another room or dates.', 'danger')
                return redirect(url_for('user.hotel_detail', hotel_id=room.hotel_id))

            total, total_cents = _price_total(room.price, nights)
            if payment_method == 'card' and not _stripe_enabled():
                flash('Card payments are not configured yet. Please choose cash payment or configure Stripe.', 'warning')
                return redirect(url_for('payments.checkout_room', room_id=booking_id, check_in=check_in,
                                        check_out=check_out,
                                        nights=nights))

            if payment_method == 'card':
                session_data = {
                    'payment_method_types': ['card'],
                    'line_items': [{
                        'price_data': {
                            'currency': 'eur',
                            'product_data': {
                                'name': f'Room #{room.number} - {room.hotel.name}',
                                'description': f'Room #{room.number} · {nights} night(s)',
                            },
                            'unit_amount': total_cents,
                        },
                        'quantity': 1,
                    }],
                    'mode': 'payment',
                    'success_url': url_for('payments.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                    'cancel_url': url_for('payments.cancel', _external=True),
                    'metadata': {
                        'room_id': str(booking_id),
                        'user_id': str(current_user.id),
                        'check_in': check_in,
                        'check_out': check_out,
                        'nights': str(nights),
                        'total_price_cents': str(total_cents),
                        'type': 'room'
                    }
                }
                owner_stripe_id = getattr(room.hotel, 'stripe_account_id', None) or None
                if owner_stripe_id:
                    session_data['payment_intent_data'] = {
                        'transfer_data': {
                            'destination': owner_stripe_id,
                        }
                    }
                checkout_session = stripe.checkout.Session.create(**session_data)
                return redirect(checkout_session.url, code=303)

            Reservation.create(
                room_id=booking_id,
                guest=current_user.username,
                user_id=current_user.id,
                start_date=check_in,
                nights=nights,
                total_price=float(total),
                payment_status='pending',
                payment_id=f'CASH-{uuid.uuid4()}'
            )

            log_activity(f"User '{current_user.username}' booked Room #{room.number} (Cash payment)")
            flash('Booking confirmed! Please pay €{:.2f} in cash at the property.'.format(total), 'success')
            return redirect(url_for('user.my_reservations'))

        elif booking_type == 'property':
            hotel = Hotel.get(booking_id)
            if not hotel:
                flash('Property not found.', 'danger')
                return redirect(url_for('user.browse_stays'))
            if not _listing_is_approved(hotel):
                flash('This property is not currently available for booking.', 'warning')
                return redirect(url_for('user.browse_stays'))

            if check_property_conflict(booking_id, check_in_date, check_out_date):
                flash('Sorry, this property was just booked for those dates. Please choose different dates.', 'danger')
                return redirect(url_for('user.hotel_detail', hotel_id=booking_id))

            total, total_cents = _price_total(hotel.price_per_night or 0, nights)
            if payment_method == 'card' and not _stripe_enabled():
                flash('Card payments are not configured yet. Please choose cash payment or configure Stripe.', 'warning')
                return redirect(url_for('payments.checkout_property', property_id=booking_id, check_in=check_in,
                                        check_out=check_out,
                                        nights=nights))

            if payment_method == 'card':
                session_data = {
                    'payment_method_types': ['card'],
                    'line_items': [{
                        'price_data': {
                            'currency': 'eur',
                            'product_data': {
                                'name': f'{hotel.name} - {hotel.property_type.title()}',
                                'description': f'Entire {hotel.property_type} · {nights} night(s)',
                            },
                            'unit_amount': total_cents,
                        },
                        'quantity': 1,
                    }],
                    'mode': 'payment',
                    'success_url': url_for('payments.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                    'cancel_url': url_for('payments.cancel', _external=True),
                    'metadata': {
                        'property_id': str(booking_id),
                        'user_id': str(current_user.id),
                        'check_in': check_in,
                        'check_out': check_out,
                        'nights': str(nights),
                        'total_price_cents': str(total_cents),
                        'type': 'property'
                    }
                }
                owner_stripe_id = getattr(hotel, 'stripe_account_id', None) or None
                if owner_stripe_id:
                    session_data['payment_intent_data'] = {
                        'transfer_data': {
                            'destination': owner_stripe_id,
                        }
                    }
                checkout_session = stripe.checkout.Session.create(**session_data)
                return redirect(checkout_session.url, code=303)

            PropertyReservation.create(
                property_id=booking_id,
                guest=current_user.username,
                user_id=current_user.id,
                start_date=check_in,
                nights=nights,
                total_price=float(total),
                payment_status='pending',
                payment_id=f'CASH-{uuid.uuid4()}'
            )

            log_activity(f"User '{current_user.username}' booked '{hotel.name}' (Cash payment)")
            flash('Booking confirmed! Please pay €{:.2f} in cash at the property.'.format(total), 'success')
            return redirect(url_for('user.my_reservations'))

        else:
            flash('Unknown booking type.', 'danger')
            return redirect(url_for('user.browse_stays'))

    except Exception as exc:
        if _stripe_error_code(exc) == '23P01':
            flash('Sorry, this stay overlaps with an existing reservation. Please choose different dates.', 'danger')
        elif isinstance(exc, ValueError):
            flash(str(exc), 'danger')
        else:
            logger.exception('Could not process booking request')
            flash('We could not complete the booking. Please try again or contact support.', 'danger')
        return redirect(url_for('user.browse_stays'))
