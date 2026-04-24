from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Room, Reservation, PropertyReservation, Activity, Hotel, HotelImage, TrendingDestination, Promotion, HotelReview
from forms import ProfileForm, SearchRoomsForm, HotelSearchForm
from datetime import datetime, timedelta
from sqlalchemy import text
import base64
from functools import wraps
import math

user_bp = Blueprint('user', __name__, url_prefix='/user')


def user_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


def log_activity(activity_text):
    try:
        activity = Activity(
            activity=f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {activity_text}",
            timestamp=datetime.now()
        )
        db.session.add(activity)
        db.session.commit()
    except:
        db.session.rollback()


def _check_room_conflict_sql(room_id, start_date, end_date):
    """Fixed: uses DATE_ADD in SQL to avoid timedelta(days=Column) bug."""
    result = db.session.execute(
        text("""SELECT id FROM reservations
                WHERE room_id = :room_id
                  AND start_date < :end_date
                  AND DATE_ADD(start_date, INTERVAL nights DAY) > :start_date
                LIMIT 1"""),
        {'room_id': room_id, 'start_date': start_date, 'end_date': end_date}
    ).fetchone()
    return result is not None


def _check_property_conflict_sql(property_id, start_date, end_date):
    result = db.session.execute(
        text("""SELECT id FROM property_reservations
                WHERE property_id = :property_id
                  AND start_date < :end_date
                  AND DATE_ADD(start_date, INTERVAL nights DAY) > :start_date
                LIMIT 1"""),
        {'property_id': property_id, 'start_date': start_date, 'end_date': end_date}
    ).fetchone()
    return result is not None


def _get_conflicting_room_ids_sql(start_date, end_date):
    rows = db.session.execute(
        text("""SELECT DISTINCT room_id FROM reservations
                WHERE start_date < :end_date
                  AND DATE_ADD(start_date, INTERVAL nights DAY) > :start_date"""),
        {'start_date': start_date, 'end_date': end_date}
    ).fetchall()
    return [r[0] for r in rows]


# ── DASHBOARD ─────────────────────────────────────────────
@user_bp.route('/')
@user_bp.route('/dashboard')
@login_required
@user_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin.dashboard'))

    today = datetime.now().date()

    # Резервации за стаи
    room_reservations = Reservation.query.filter(
        Reservation.guest == current_user.username
    ).all()

    room_upcoming = Reservation.query.filter(
        Reservation.guest == current_user.username,
        Reservation.start_date >= today
    ).order_by(Reservation.start_date).limit(5).all()

    room_past = Reservation.query.filter(
        Reservation.guest == current_user.username,
        Reservation.start_date < today
    ).order_by(Reservation.start_date.desc()).limit(5).all()

    # Резервации за цели имоти
    property_reservations = PropertyReservation.query.filter(
        PropertyReservation.guest == current_user.username
    ).all()

    property_upcoming = PropertyReservation.query.filter(
        PropertyReservation.guest == current_user.username,
        PropertyReservation.start_date >= today
    ).order_by(PropertyReservation.start_date).limit(5).all()

    property_past = PropertyReservation.query.filter(
        PropertyReservation.guest == current_user.username,
        PropertyReservation.start_date < today
    ).order_by(PropertyReservation.start_date.desc()).limit(5).all()

    # Общо резервации
    total_bookings = len(room_reservations) + len(property_reservations)

    # Изчисляване на общо похарчени пари
    total_spent = 0
    for res in room_reservations:
        total_spent += res.room.price * res.nights
    for res in property_reservations:
        total_spent += res.total_price

    # Изчисляване на общо нощувки
    total_nights = sum(res.nights for res in room_reservations) + sum(res.nights for res in property_reservations)

    # Брой посетени дестинации (уникални градове)
    cities_visited = set()
    for res in room_reservations:
        if res.room and res.room.hotel:
            cities_visited.add(res.room.hotel.city)
    for res in property_reservations:
        if res.hotel:
            cities_visited.add(res.hotel.city)

    # Брой хотели/имоти в системата
    total_properties = Hotel.query.count()
    total_hotels = Hotel.query.filter_by(property_type='hotel').count()
    total_apartments = Hotel.query.filter_by(property_type='apartment').count()
    total_villas = Hotel.query.filter_by(property_type='villa').count()
    total_resorts = Hotel.query.filter_by(property_type='resort').count()

    # Комбинирани upcoming и past
    all_upcoming = sorted(
        list(room_upcoming) + list(property_upcoming),
        key=lambda x: x.start_date
    )[:5]

    all_past = sorted(
        list(room_past) + list(property_past),
        key=lambda x: x.start_date,
        reverse=True
    )[:5]

    # Последна резервация
    last_booking = None
    if all_upcoming:
        last_booking = all_upcoming[0]
    elif all_past:
        last_booking = all_past[0]

    # Trending destinations от базата данни
    trending = TrendingDestination.query.filter_by(is_active=True).order_by(
        TrendingDestination.display_order).limit(6).all()

    # Активни промоции
    promotions = Promotion.query.filter_by(is_active=True).all()

    # Топ имоти (по рейтинг)
    top_properties = Hotel.query.order_by(Hotel.avg_rating.desc()).limit(4).all()

    return render_template('user/dashboard.html',
                           total_bookings=total_bookings,
                           total_spent=total_spent,
                           total_nights=total_nights,
                           cities_visited=len(cities_visited),
                           total_properties=total_properties,
                           total_hotels=total_hotels,
                           total_apartments=total_apartments,
                           total_villas=total_villas,
                           total_resorts=total_resorts,
                           upcoming=all_upcoming,
                           past=all_past,
                           last_booking=last_booking,
                           trending=trending,
                           promotions=promotions,
                           top_properties=top_properties,
                           now=datetime.now())

# ── BROWSE STAYS — PUBLIC ─────────────────────────────────
@user_bp.route('/stays', methods=['GET'])
def browse_stays():
    trending = TrendingDestination.query.filter_by(is_active=True).order_by(
        TrendingDestination.display_order).limit(6).all()
    promotions = Promotion.query.filter_by(is_active=True).all()
    return render_template('user/browse_stays.html',
                           trending=trending, promotions=promotions, now=datetime.now())


# ── SEARCH STAYS — PUBLIC ─────────────────────────────────
@user_bp.route('/stays/search', methods=['GET'])
def search_stays():
    destination = request.args.get('destination', '')
    check_in = request.args.get('check_in', '')
    check_out = request.args.get('check_out', '')
    adults = request.args.get('adults', 2, type=int)
    children = request.args.get('children', 0, type=int)
    rooms = request.args.get('rooms', 1, type=int)
    sort_by = request.args.get('sort_by', 'recommended')
    property_type = request.args.get('property_type', 'all')

    query = Hotel.query
    if destination:
        query = query.filter(
            (Hotel.city.ilike(f'%{destination}%')) |
            (Hotel.name.ilike(f'%{destination}%')) |
            (Hotel.country.ilike(f'%{destination}%'))
        )
    if property_type != 'all':
        query = query.filter(Hotel.property_type == property_type)

    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)
    if min_price:
        query = query.filter(Hotel.price_per_night >= min_price)
    if max_price:
        query = query.filter(Hotel.price_per_night <= max_price)

    stars = request.args.getlist('stars')
    if stars:
        query = query.filter(Hotel.stars.in_([int(s) for s in stars]))

    min_rating = request.args.get('min_rating', type=float)
    if min_rating:
        query = query.filter(Hotel.avg_rating >= min_rating)

    if sort_by == 'price_asc':
        query = query.order_by(Hotel.price_per_night.asc())
    elif sort_by == 'price_desc':
        query = query.order_by(Hotel.price_per_night.desc())
    elif sort_by == 'rating_desc':
        query = query.order_by(Hotel.avg_rating.desc())
    elif sort_by == 'popularity':
        query = query.order_by(Hotel.review_count.desc())
    else:
        query = query.order_by(Hotel.avg_rating.desc(), Hotel.review_count.desc())

    hotels = query.all()
    return render_template('user/search_results.html',
                           hotels=hotels, total_hotels=len(hotels),
                           destination=destination, check_in=check_in,
                           check_out=check_out, adults=adults,
                           children=children, rooms=rooms,
                           sort_by=sort_by, property_type=property_type,
                           now=datetime.now())


# ── COMPATIBILITY REDIRECTS ───────────────────────────────
@user_bp.route('/hotels', methods=['GET'])
def browse_hotels():
    return redirect(url_for('user.browse_stays'))

@user_bp.route('/hotels/search', methods=['GET'])
def search_hotels():
    return redirect(url_for('user.search_stays', **request.args))

@user_bp.route('/destination/<string:city>')
def destination_hotels(city):
    return redirect(url_for('user.search_stays', destination=city))


# ── HOTEL DETAIL — PUBLIC ─────────────────────────────────
@user_bp.route('/hotel/<int:hotel_id>')
def hotel_detail(hotel_id):
    hotel = Hotel.query.get_or_404(hotel_id)
    check_in = request.args.get('check_in')
    check_out = request.args.get('check_out')
    adults = request.args.get('adults', 2, type=int)
    children = request.args.get('children', 0, type=int)

    nights = 0
    check_in_date = None
    check_out_date = None

    if check_in and check_out:
        try:
            check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
            check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
            nights = max(0, (check_out_date - check_in_date).days)
        except ValueError:
            pass

    available_rooms = []
    if hotel.property_type == 'hotel':
        rooms = Room.query.filter_by(hotel_id=hotel_id).all()
        for room in rooms:
            conflict = False
            if check_in_date and check_out_date and nights > 0:
                conflict = _check_room_conflict_sql(room.id, check_in_date, check_out_date)
            if not conflict:
                available_rooms.append({
                    'room': room,
                    'total_price': room.price * nights if nights > 0 else room.price,
                    'is_whole_property': False,
                    'max_guests': 2
                })
    else:
        price = hotel.price_per_night or 0
        available_rooms.append({
            'room': None,
            'total_price': price * nights if nights > 0 else price,
            'is_whole_property': True,
            'max_guests': hotel.max_guests or 2,
            'total_rooms': hotel.total_rooms or 1,
            'property_type': hotel.property_type
        })

    return render_template('user/hotel_detail.html',
                           hotel=hotel, rooms=available_rooms,
                           check_in=check_in, check_out=check_out,
                           nights=nights, adults=adults, children=children,
                           now=datetime.now())


# ── MY RESERVATIONS ───────────────────────────────────────
@user_bp.route('/my-reservations')
@login_required
@user_required
def my_reservations():
    today = datetime.now().date()
    room_upcoming = Reservation.query.filter(
        Reservation.guest == current_user.username,
        Reservation.start_date >= today
    ).order_by(Reservation.start_date).all()
    room_past = Reservation.query.filter(
        Reservation.guest == current_user.username,
        Reservation.start_date < today
    ).order_by(Reservation.start_date.desc()).all()
    property_upcoming = PropertyReservation.query.filter(
        PropertyReservation.guest == current_user.username,
        PropertyReservation.start_date >= today
    ).order_by(PropertyReservation.start_date).all()
    property_past = PropertyReservation.query.filter(
        PropertyReservation.guest == current_user.username,
        PropertyReservation.start_date < today
    ).order_by(PropertyReservation.start_date.desc()).all()

    upcoming = sorted(room_upcoming + property_upcoming, key=lambda x: x.start_date)
    past = sorted(room_past + property_past, key=lambda x: x.start_date, reverse=True)
    return render_template('user/my_reservations.html',
                           upcoming=upcoming, past=past, now=datetime.now())


@user_bp.route('/cancel-property-reservation/<int:reservation_id>', methods=['POST'])
@login_required
@user_required
def cancel_property_reservation(reservation_id):
    reservation = PropertyReservation.query.get_or_404(reservation_id)
    if reservation.guest != current_user.username:
        flash('You do not have permission to cancel this reservation', 'danger')
        return redirect(url_for('user.my_reservations'))
    try:
        property_name = reservation.hotel.name if hasattr(reservation, 'hotel') and reservation.hotel else 'Unknown'
        db.session.delete(reservation)
        db.session.commit()
        log_activity(f"User '{current_user.username}' cancelled reservation for '{property_name}'")
        flash('Reservation cancelled successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error cancelling reservation: {str(e)}', 'danger')
    return redirect(url_for('user.my_reservations'))


@user_bp.route('/cancel-reservation/<int:reservation_id>', methods=['POST'])
@login_required
@user_required
def cancel_reservation(reservation_id):
    reservation = Reservation.query.get_or_404(reservation_id)
    if reservation.guest != current_user.username:
        flash('You do not have permission to cancel this reservation', 'danger')
        return redirect(url_for('user.my_reservations'))
    try:
        room_number = reservation.room.number if reservation.room else 'Unknown'
        db.session.delete(reservation)
        db.session.commit()
        log_activity(f"User '{current_user.username}' cancelled reservation for Room #{room_number}")
        flash('Reservation cancelled successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error cancelling reservation: {str(e)}', 'danger')
    return redirect(url_for('user.my_reservations'))


# ── PROFILE ───────────────────────────────────────────────
@user_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@user_required
def profile():
    form = ProfileForm()
    if request.method == 'GET':
        form.email.data = current_user.email
        form.phone.data = current_user.phone
        form.address.data = current_user.address

    if form.validate_on_submit():
        changes_made = False
        if form.current_password.data:
            if not check_password_hash(current_user.password_hash, form.current_password.data):
                flash('Current password is incorrect', 'danger')
                return render_template('user/profile.html', form=form, user=current_user, now=datetime.now())
            if form.new_password.data:
                current_user.password_hash = generate_password_hash(form.new_password.data)
                changes_made = True
        if form.email.data != current_user.email:
            current_user.email = form.email.data or None
            changes_made = True
        if form.phone.data != current_user.phone:
            current_user.phone = form.phone.data or None
            changes_made = True
        if form.address.data != current_user.address:
            current_user.address = form.address.data or None
            changes_made = True
        if form.profile_image.data:
            current_user.profile_image = form.profile_image.data.read()
            changes_made = True
        if changes_made:
            try:
                db.session.commit()
                flash('Profile updated successfully!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Error updating profile: {str(e)}', 'danger')
        else:
            flash('No changes were made', 'info')
        return redirect(url_for('user.profile'))

    return render_template('user/profile.html', form=form, user=current_user, now=datetime.now())


@user_bp.route('/profile/image')
@login_required
@user_required
def profile_image():
    if current_user.profile_image:
        return base64.b64encode(current_user.profile_image).decode('utf-8')
    return ''


@user_bp.route('/profile/remove-image', methods=['POST'])
@login_required
@user_required
def remove_profile_image():
    current_user.profile_image = None
    try:
        db.session.commit()
        flash('Profile photo removed!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('user.profile'))


# ── BOOKING API ───────────────────────────────────────────
@user_bp.route('/api/available-rooms', methods=['POST'])
@login_required
@user_required
def available_rooms_api():
    data = request.get_json()
    nights = int(data.get('nights', 1))
    try:
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=nights)
        all_rooms = Room.query.all()
        conflicting_ids = _get_conflicting_room_ids_sql(start_date, end_date)
        rooms_data = []
        for room in all_rooms:
            if room.id not in conflicting_ids:
                rd = room.to_dict()
                if room.image_data:
                    rd['image'] = base64.b64encode(room.image_data).decode('utf-8')
                rooms_data.append(rd)
        return jsonify({'success': True, 'rooms': rooms_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@user_bp.route('/book', methods=['POST'])
@login_required
@user_required
def book_room():
    data = request.get_json()
    nights = int(data.get('nights', 1))
    try:
        room = Room.query.get_or_404(int(data.get('room_id')))
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=nights)

        if _check_room_conflict_sql(room.id, start_date, end_date):
            return jsonify({'success': False, 'error': 'Room is no longer available for these dates'})

        reservation = Reservation(
            room_id=room.id, guest=current_user.username,
            user_id=current_user.id, start_date=start_date, nights=nights
        )
        db.session.add(reservation)
        db.session.commit()
        log_activity(f"Room #{room.number} booked by {current_user.username} for {nights} nights")
        return jsonify({'success': True,
                        'message': f'Booking confirmed for Room #{room.number}!',
                        'reservation_id': reservation.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@user_bp.route('/book-property/<int:property_id>', methods=['POST'])
@login_required
@user_required
def book_property(property_id):
    data = request.get_json()
    nights = int(data.get('nights', 1))
    try:
        hotel = Hotel.query.get_or_404(property_id)
        if hotel.property_type == 'hotel':
            return jsonify({'success': False, 'error': 'Use room booking for hotels'})
        if not hotel.price_per_night or hotel.price_per_night <= 0:
            return jsonify({'success': False, 'error': 'Price not set for this property'})

        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=nights)

        if _check_property_conflict_sql(hotel.id, start_date, end_date):
            return jsonify({'success': False, 'error': 'Property is not available for selected dates'})

        total_price = hotel.price_per_night * nights
        reservation = PropertyReservation(
            property_id=hotel.id, guest=current_user.username,
            user_id=current_user.id, start_date=start_date,
            nights=nights, total_price=total_price
        )
        db.session.add(reservation)
        db.session.commit()
        log_activity(f"Property '{hotel.name}' booked by {current_user.username} for {nights} nights")
        return jsonify({'success': True,
                        'message': f'Booking confirmed! Total: €{total_price:.2f}',
                        'reservation_id': reservation.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})
