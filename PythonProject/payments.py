from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from models import Reservation, PropertyReservation, Room, Hotel, log_activity
from supabase_client import supabase
from config import Config
import stripe
from datetime import datetime, timedelta

payments_bp = Blueprint('payments', __name__, url_prefix='/payments')

stripe.api_key = Config.STRIPE_SECRET_KEY


@payments_bp.route('/checkout/room/<int:room_id>', methods=['GET', 'POST'])
@login_required
def checkout_room(room_id):
    room = Room.get(room_id)
    if not room:
        flash('Room not found', 'danger')
        return redirect(url_for('user.browse_stays'))
    hotel = room.hotel

    check_in = request.args.get('check_in')
    check_out = request.args.get('check_out')
    nights = request.args.get('nights', 1, type=int)

    if check_in and check_out:
        check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
        check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
        nights = (check_out_date - check_in_date).days
    elif not nights:
        nights = 1

    total_price = room.price * nights
    total_cents = int(total_price * 100)

    if request.method == 'POST':
        try:
            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'eur',
                        'product_data': {
                            'name': f'Room #{room.number} - {hotel.name}',
                            'description': f'{room.type} Room · {nights} night(s) · {hotel.city}, {hotel.country}',
                        },
                        'unit_amount': total_cents,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=url_for('payments.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('payments.cancel', _external=True),
                metadata={
                    'room_id': room_id,
                    'user_id': current_user.id,
                    'check_in': check_in,
                    'nights': nights,
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
                           stripe_public_key=Config.STRIPE_PUBLIC_KEY)


@payments_bp.route('/checkout/property/<int:property_id>', methods=['GET', 'POST'])
@login_required
def checkout_property(property_id):
    hotel = Hotel.get(property_id)
    if not hotel:
        flash('Property not found', 'danger')
        return redirect(url_for('user.browse_stays'))

    check_in = request.args.get('check_in')
    check_out = request.args.get('check_out')
    nights = request.args.get('nights', 1, type=int)

    if check_in and check_out:
        check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
        check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
        nights = (check_out_date - check_in_date).days

    total_price = (hotel.price_per_night or 0) * nights
    total_cents = int(total_price * 100)

    if request.method == 'POST':
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
                    'property_id': property_id,
                    'user_id': current_user.id,
                    'check_in': check_in,
                    'nights': nights,
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
                           stripe_public_key=Config.STRIPE_PUBLIC_KEY)


@payments_bp.route('/success')
def success():
    session_id = request.args.get('session_id')

    if session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            metadata = session.metadata

            if metadata.get('type') == 'room':
                room_id = int(metadata.get('room_id'))
                check_in = metadata.get('check_in')
                nights = int(metadata.get('nights'))

                room = Room.get(room_id)

                Reservation.create(
                    room_id=room_id,
                    guest=current_user.username,
                    user_id=current_user.id,
                    start_date=check_in,
                    nights=nights,
                    total_price=room.price * nights,
                    payment_status='paid',
                    payment_id=session_id
                )

                flash('Payment successful! Your room has been booked.', 'success')

            elif metadata.get('type') == 'property':
                property_id = int(metadata.get('property_id'))
                check_in = metadata.get('check_in')
                nights = int(metadata.get('nights'))

                hotel = Hotel.get(property_id)

                PropertyReservation.create(
                    property_id=property_id,
                    guest=current_user.username,
                    user_id=current_user.id,
                    start_date=check_in,
                    nights=nights,
                    total_price=(hotel.price_per_night or 0) * nights,
                    payment_status='paid',
                    payment_id=session_id
                )

                flash('Payment successful! Your property has been booked.', 'success')

            return redirect(url_for('user.my_reservations'))

        except Exception as e:
            flash(f'Error processing payment: {str(e)}', 'danger')
            return redirect(url_for('user.dashboard'))

    return redirect(url_for('user.dashboard'))


@payments_bp.route('/cancel')
def cancel():
    flash('Payment was cancelled. Your booking was not completed.', 'warning')
    return redirect(url_for('user.browse_stays'))


@payments_bp.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    endpoint_secret = 'whsec_your_webhook_secret'

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError:
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400

    if event['type'] == 'checkout.session.completed':
        pass

    return jsonify({'status': 'success'}), 200


@payments_bp.route('/process-payment', methods=['POST'])
@login_required
def process_payment():
    payment_method = request.form.get('payment_method')
    booking_type = request.form.get('booking_type')
    booking_id = int(request.form.get('booking_id'))
    check_in = request.form.get('check_in')
    nights = int(request.form.get('nights'))
    total_price = float(request.form.get('total_price'))

    start_date = check_in

    try:
        if booking_type == 'room':
            room = Room.get(booking_id)

            if payment_method == 'card':
                checkout_session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'eur',
                            'product_data': {
                                'name': f'Room #{room.number} - {room.hotel.name}',
                                'description': f'{room.type} Room · {nights} night(s)',
                            },
                            'unit_amount': int(total_price * 100),
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url=url_for('payments.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                    cancel_url=url_for('payments.cancel', _external=True),
                    metadata={
                        'room_id': booking_id,
                        'user_id': current_user.id,
                        'check_in': check_in,
                        'nights': nights,
                        'type': 'room'
                    }
                )
                return redirect(checkout_session.url, code=303)

            else:
                Reservation.create(
                    room_id=booking_id,
                    guest=current_user.username,
                    user_id=current_user.id,
                    start_date=start_date,
                    nights=nights,
                    total_price=total_price,
                    payment_status='pending',
                    payment_id=f'CASH-{datetime.now().strftime("%Y%m%d%H%M%S")}'
                )

                log_activity(f"User '{current_user.username}' booked Room #{room.number} (Cash payment)")
                flash('Booking confirmed! Please pay €{:.2f} in cash at the property.'.format(total_price), 'success')
                return redirect(url_for('user.my_reservations'))

        elif booking_type == 'property':
            hotel = Hotel.get(booking_id)

            if payment_method == 'card':
                checkout_session = stripe.checkout.Session.create(
                    payment_method_types=['card'],
                    line_items=[{
                        'price_data': {
                            'currency': 'eur',
                            'product_data': {
                                'name': f'{hotel.name} - {hotel.property_type.title()}',
                                'description': f'Entire {hotel.property_type} · {nights} night(s)',
                            },
                            'unit_amount': int(total_price * 100),
                        },
                        'quantity': 1,
                    }],
                    mode='payment',
                    success_url=url_for('payments.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                    cancel_url=url_for('payments.cancel', _external=True),
                    metadata={
                        'property_id': booking_id,
                        'user_id': current_user.id,
                        'check_in': check_in,
                        'nights': nights,
                        'type': 'property'
                    }
                )
                return redirect(checkout_session.url, code=303)

            else:
                PropertyReservation.create(
                    property_id=booking_id,
                    guest=current_user.username,
                    user_id=current_user.id,
                    start_date=start_date,
                    nights=nights,
                    total_price=total_price,
                    payment_status='pending',
                    payment_id=f'CASH-{datetime.now().strftime("%Y%m%d%H%M%S")}'
                )

                log_activity(f"User '{current_user.username}' booked '{hotel.name}' (Cash payment)")
                flash('Booking confirmed! Please pay €{:.2f} in cash at the property.'.format(total_price), 'success')
                return redirect(url_for('user.my_reservations'))

    except Exception as e:
        flash(f'Error processing booking: {str(e)}', 'danger')
        return redirect(url_for('user.browse_stays'))
