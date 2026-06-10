from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, Room, Reservation, PropertyReservation, Hotel, HotelImage, TrendingDestination, \
    Promotion, HotelReview, log_activity, check_room_conflict, check_property_conflict, get_conflicting_room_ids, \
    BaseModel
from forms import ProfileForm, SearchRoomsForm, HotelSearchForm
from datetime import datetime, timedelta
from supabase_client import supabase
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


@user_bp.route('/')
@user_bp.route('/dashboard')
@login_required
@user_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin.dashboard'))

    today = datetime.now().date()

    room_reservations = Reservation.find_by_guest(current_user.username)
    property_reservations = PropertyReservation.find_by_guest(current_user.username)

    room_upcoming = [r for r in room_reservations if _parse_date(r.start_date) >= today][:5]
    room_past = [r for r in room_reservations if _parse_date(r.start_date) < today][:5]
    property_upcoming = [r for r in property_reservations if _parse_date(r.start_date) >= today][:5]
    property_past = [r for r in property_reservations if _parse_date(r.start_date) < today][:5]

    total_bookings = len(room_reservations) + len(property_reservations)

    total_spent = 0
    for res in room_reservations:
        if res.total_price:
            total_spent += res.total_price
        elif res.room:
            total_spent += (res.room.price or 0) * (res.nights or 0)
    for res in property_reservations:
        total_spent += res.total_price or 0

    total_nights = sum((r.nights or 0) for r in room_reservations) + sum((r.nights or 0) for r in property_reservations)

    cities_visited = set()
    for res in room_reservations:
        r = res.room
        if r and r.hotel and r.hotel.city:
            cities_visited.add(r.hotel.city)
    for res in property_reservations:
        h = res.hotel
        if h and h.city:
            cities_visited.add(h.city)

    total_properties = Hotel.count()
    total_hotels = Hotel.count_by_type('hotel')
    total_apartments = Hotel.count_by_type('apartment')
    total_villas = Hotel.count_by_type('villa')
    total_resorts = Hotel.count_by_type('resort')

    all_upcoming = sorted(
        room_upcoming + property_upcoming,
        key=lambda x: _parse_date(x.start_date) or datetime.min.date()
    )[:5]

    all_past = sorted(
        room_past + property_past,
        key=lambda x: _parse_date(x.start_date) or datetime.min.date(),
        reverse=True
    )[:5]

    last_booking = None
    if all_upcoming:
        last_booking = all_upcoming[0]
    elif all_past:
        last_booking = all_past[0]

    data = supabase.table('hotels').select('*').order('avg_rating', desc=True).limit(4).execute()
    top_properties = [Hotel(r) for r in (data.data or [])]

    trending = TrendingDestination.get_active(6)

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
                           top_properties=top_properties,
                           now=datetime.now())


def _parse_date(val):
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace('Z', '+00:00')).date()
        except (ValueError, TypeError):
            try:
                return datetime.strptime(val, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                return None
    return val


@user_bp.route('/stays', methods=['GET'])
def browse_stays():
    trending = TrendingDestination.get_active(6)
    promotions = Promotion.get_active()
    return render_template('user/browse_stays.html',
                           trending=trending, promotions=promotions, now=datetime.now())


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

    min_price = request.args.get('min_price', type=int)
    max_price = request.args.get('max_price', type=int)
    stars = [int(s) for s in request.args.getlist('stars') if s.isdigit()]
    min_rating = request.args.get('min_rating', type=float)

    hotels = Hotel.search(
        destination=destination,
        property_type=property_type,
        sort_by=sort_by,
        min_price=min_price,
        max_price=max_price,
        stars=stars,
        min_rating=min_rating
    )

    return render_template('user/search_results.html',
                           hotels=hotels, total_hotels=len(hotels),
                           destination=destination, check_in=check_in,
                           check_out=check_out, adults=adults,
                           children=children, rooms=rooms,
                           sort_by=sort_by, property_type=property_type,
                           stars=stars, min_rating=min_rating,
                           now=datetime.now())


@user_bp.route('/hotels', methods=['GET'])
def browse_hotels():
    return redirect(url_for('user.browse_stays'))


@user_bp.route('/hotels/search', methods=['GET'])
def search_hotels():
    return redirect(url_for('user.search_stays', **request.args))


@user_bp.route('/destination/<string:city>')
def destination_hotels(city):
    return redirect(url_for('user.search_stays', destination=city))


@user_bp.route('/hotel/<int:hotel_id>')
def hotel_detail(hotel_id):
    hotel = Hotel.get(hotel_id)
    if not hotel:
        flash('Property not found', 'danger')
        return redirect(url_for('user.browse_stays'))

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
    if hotel.property_type in ('hotel', 'villa', 'resort'):
        rooms = Room.find_by_hotel(hotel_id)
        for room in rooms:
            conflict = False
            if check_in_date and check_out_date and nights > 0:
                conflict = check_room_conflict(room.id, check_in_date, check_out_date)
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


@user_bp.route('/my-reservations')
@login_required
@user_required
def my_reservations():
    today = datetime.now().date()

    all_room = Reservation.find_by_guest(current_user.username)
    room_upcoming = [r for r in all_room if _parse_date(r.start_date) >= today]
    room_past = [r for r in all_room if _parse_date(r.start_date) < today]

    all_property = PropertyReservation.find_by_guest(current_user.username)
    property_upcoming = [r for r in all_property if _parse_date(r.start_date) >= today]
    property_past = [r for r in all_property if _parse_date(r.start_date) < today]

    upcoming = sorted(room_upcoming + property_upcoming, key=lambda x: _parse_date(x.start_date) or datetime.min.date())
    past = sorted(room_past + property_past, key=lambda x: _parse_date(x.start_date) or datetime.min.date(), reverse=True)
    return render_template('user/my_reservations.html',
                           upcoming=upcoming, past=past, now=datetime.now())


@user_bp.route('/cancel-property-reservation/<int:reservation_id>', methods=['POST'])
@login_required
@user_required
def cancel_property_reservation(reservation_id):
    reservation = PropertyReservation.get(reservation_id)
    if not reservation or reservation.guest != current_user.username:
        flash('You do not have permission to cancel this reservation', 'danger')
        return redirect(url_for('user.my_reservations'))
    try:
        h = reservation.hotel
        property_name = h.name if h else 'Unknown'
        reservation.delete()
        log_activity(f"User '{current_user.username}' cancelled reservation for '{property_name}'")
        flash('Reservation cancelled successfully!', 'success')
    except Exception as e:
        flash(f'Error cancelling reservation: {str(e)}', 'danger')
    return redirect(url_for('user.my_reservations'))


@user_bp.route('/cancel-reservation/<int:reservation_id>', methods=['POST'])
@login_required
@user_required
def cancel_reservation(reservation_id):
    reservation = Reservation.get(reservation_id)
    if not reservation or reservation.guest != current_user.username:
        flash('You do not have permission to cancel this reservation', 'danger')
        return redirect(url_for('user.my_reservations'))
    try:
        r = reservation.room
        room_number = r.number if r else 'Unknown'
        reservation.delete()
        log_activity(f"User '{current_user.username}' cancelled reservation for Room #{room_number}")
        flash('Reservation cancelled successfully!', 'success')
    except Exception as e:
        flash(f'Error cancelling reservation: {str(e)}', 'danger')
    return redirect(url_for('user.my_reservations'))


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
        update_data = {}

        if form.current_password.data:
            if not check_password_hash(current_user.password_hash, form.current_password.data):
                flash('Current password is incorrect', 'danger')
                return render_template('user/profile.html', form=form, user=current_user, now=datetime.now())
            if form.new_password.data:
                update_data['password_hash'] = generate_password_hash(form.new_password.data)
                changes_made = True

        if form.email.data != current_user.email:
            update_data['email'] = form.email.data or None
            changes_made = True
        if form.phone.data != current_user.phone:
            update_data['phone'] = form.phone.data or None
            changes_made = True
        if form.address.data != current_user.address:
            update_data['address'] = form.address.data or None
            changes_made = True
        if form.profile_image.data:
            update_data['profile_image'] = base64.b64encode(form.profile_image.data.read()).decode('utf-8')
            changes_made = True

        if changes_made:
            try:
                current_user.update(**update_data)
                flash('Profile updated successfully!', 'success')
            except Exception as e:
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
        return current_user.profile_image
    return ''


@user_bp.route('/profile/remove-image', methods=['POST'])
@login_required
@user_required
def remove_profile_image():
    try:
        current_user.update(profile_image=None)
        flash('Profile photo removed!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('user.profile'))


@user_bp.route('/api/available-rooms', methods=['POST'])
@login_required
@user_required
def available_rooms_api():
    data = request.get_json()
    nights = int(data.get('nights', 1))
    try:
        start_date = datetime.strptime(data.get('start_date'), '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=nights)
        all_rooms_data = supabase.table('rooms').select('*').execute()
        conflicting_ids = get_conflicting_room_ids(start_date, end_date)
        rooms_data = []
        for rd in (all_rooms_data.data or []):
            if rd['id'] not in conflicting_ids:
                r = {
                    'id': rd['id'],
                    'number': rd.get('number'),
                    'price': rd.get('price'),
                    'type': rd.get('type'),
                    'beds': rd.get('beds')
                }
                if rd.get('image_data'):
                    r['image'] = rd['image_data']
                rooms_data.append(r)
        return jsonify({'success': True, 'rooms': rooms_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@user_bp.route('/book', methods=['POST'])
@login_required
@user_required
def book_room():
    data = request.get_json()
    nights = int(data.get('nights', 1))
    room_id = int(data.get('room_id'))
    start_date = data.get('start_date')

    return jsonify({
        'success': True,
        'redirect': url_for('payments.checkout_room',
                            room_id=room_id,
                            check_in=start_date,
                            nights=nights)
    })


@user_bp.route('/book-property/<int:property_id>', methods=['POST'])
@login_required
@user_required
def book_property(property_id):
    data = request.get_json()
    nights = int(data.get('nights', 1))
    start_date = data.get('start_date')

    return jsonify({
        'success': True,
        'redirect': url_for('payments.checkout_property',
                            property_id=property_id,
                            check_in=start_date,
                            nights=nights)
    })
