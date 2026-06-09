from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import User, Room, Reservation, Activity, Hotel, HotelImage, log_activity
from forms import RoomForm, ReservationForm, HotelForm
from datetime import datetime, timedelta
from supabase_client import supabase
import base64
from functools import wraps

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Access denied. Admin only area.', 'danger')
            return redirect(url_for('user.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    my_hotels = Hotel.find_by_owner(current_user.id)
    my_hotel_ids = [h.id for h in my_hotels]

    total_my_hotels = len(my_hotels)
    total_my_rooms = Room.count_by_hotel_ids(my_hotel_ids)

    total_my_reservations = 0
    revenue = 0

    if my_hotel_ids:
        my_rooms = Room.find_by_hotel_ids(my_hotel_ids)
        my_room_ids = [r.id for r in my_rooms]

        if my_room_ids:
            data = supabase.table('reservations').select('*').in_('room_id', my_room_ids).execute()
            reservations_list = data.data or []
            total_my_reservations = len(reservations_list)
            for res in reservations_list:
                room_data = supabase.table('rooms').select('price').eq('id', res['room_id']).execute()
                if room_data.data:
                    revenue += (room_data.data[0].get('price', 0) or 0) * (res.get('nights', 0) or 0)

    total_users = User.count()
    recent_activities = Activity.get_recent(10)

    return render_template('admin/dashboard.html',
                           total_my_hotels=total_my_hotels,
                           total_my_rooms=total_my_rooms,
                           total_my_reservations=total_my_reservations,
                           revenue=revenue,
                           total_users=total_users,
                           activities=recent_activities,
                           now=datetime.now())


@admin_bp.route('/my-properties')
@login_required
@admin_required
def my_properties():
    hotels = Hotel.find_by_owner(current_user.id)
    return render_template('admin/my_properties.html', hotels=hotels, now=datetime.now())


@admin_bp.route('/my-properties/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_property():
    if request.method == 'GET':
        return render_template('admin/add_property.html', now=datetime.now())

    name = request.form.get('name')
    property_type = request.form.get('property_type')
    description = request.form.get('description')
    address = request.form.get('address')
    city = request.form.get('city')
    country = request.form.get('country')
    stars = request.form.get('stars', 3)
    total_rooms = request.form.get('total_rooms', 1)
    max_guests = request.form.get('max_guests', 2)
    price_per_night = request.form.get('price_per_night')

    if not name:
        flash('Property name is required!', 'danger')
        return redirect(url_for('admin.add_property'))

    hotel_data = {
        'name': name,
        'property_type': property_type,
        'description': description,
        'address': address,
        'city': city,
        'country': country,
        'stars': int(stars),
        'owner_id': current_user.id,
        'total_rooms': int(total_rooms) if total_rooms else 1,
        'max_guests': int(max_guests) if max_guests else 2,
        'price_per_night': float(price_per_night) if price_per_night and property_type == 'apartment' else None
    }

    if 'main_image' in request.files:
        image = request.files['main_image']
        if image and image.filename:
            hotel_data['main_image'] = base64.b64encode(image.read()).decode('utf-8')

    try:
        hotel = Hotel.create(**hotel_data)

        if 'gallery_images' in request.files:
            images = request.files.getlist('gallery_images')
            for img in images:
                if img and img.filename:
                    HotelImage.create(
                        hotel_id=hotel.id,
                        image_data=base64.b64encode(img.read()).decode('utf-8')
                    )

        log_activity(f"Admin '{current_user.username}' added property '{name}'")
        flash(f'Property "{name}" added successfully!', 'success')
        return redirect(url_for('admin.my_properties'))

    except Exception as e:
        flash(f'Error adding property: {str(e)}', 'danger')
        return redirect(url_for('admin.add_property'))


@admin_bp.route('/my-properties/edit/<int:property_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_property(property_id):
    hotel = Hotel.find_by_id_and_owner(property_id, current_user.id)
    if not hotel:
        flash('Property not found or access denied', 'danger')
        return redirect(url_for('admin.my_properties'))

    if request.method == 'GET':
        return render_template('admin/edit_property.html', hotel=hotel, now=datetime.now())

    update_data = {}
    for field in ['name', 'property_type', 'description', 'address', 'city', 'country']:
        val = request.form.get(field)
        if val is not None:
            update_data[field] = val
    update_data['stars'] = int(request.form.get('stars', hotel.stars))

    if 'main_image' in request.files:
        image = request.files['main_image']
        if image and image.filename:
            update_data['main_image'] = base64.b64encode(image.read()).decode('utf-8')

    try:
        hotel.update(**update_data)
        log_activity(f"Admin '{current_user.username}' edited property '{hotel.name}'")
        flash(f'Property "{hotel.name}" updated successfully!', 'success')
    except Exception as e:
        flash(f'Error updating property: {str(e)}', 'danger')

    return redirect(url_for('admin.my_properties'))


@admin_bp.route('/my-properties/delete/<int:property_id>', methods=['POST'])
@login_required
@admin_required
def delete_property(property_id):
    hotel = Hotel.find_by_id_and_owner(property_id, current_user.id)
    if not hotel:
        flash('Property not found or access denied', 'danger')
        return redirect(url_for('admin.my_properties'))

    hotel_rooms = Room.find_by_hotel(property_id)
    if hotel_rooms:
        flash(f'Cannot delete "{hotel.name}" because it has rooms!', 'danger')
        return redirect(url_for('admin.my_properties'))

    try:
        hotel_name = hotel.name
        hotel.delete()
        log_activity(f"Admin '{current_user.username}' deleted property '{hotel_name}'")
        flash(f'Property "{hotel_name}" deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting property: {str(e)}', 'danger')

    return redirect(url_for('admin.my_properties'))


@admin_bp.route('/my-rooms')
@login_required
@admin_required
def my_rooms():
    my_hotels = Hotel.find_by_owner(current_user.id)
    my_hotel_ids = [h.id for h in my_hotels]
    rooms = Room.find_by_hotel_ids(my_hotel_ids)
    room_hotels = [h for h in my_hotels if h.property_type in ('hotel', 'villa', 'resort')]
    return render_template('admin/my_rooms.html', rooms=rooms, hotels=room_hotels, now=datetime.now())


@admin_bp.route('/my-rooms/add', methods=['POST'])
@login_required
@admin_required
def add_room():
    hotel_id = request.form.get('hotel_id')
    number = request.form.get('number')
    price = request.form.get('price')
    room_type = request.form.get('type')
    beds = request.form.get('beds')
    jacuzzi = request.form.get('jacuzzi')

    hotel = Hotel.find_by_id_and_owner(hotel_id, current_user.id)
    if not hotel:
        flash('Hotel not found or you do not have permission!', 'danger')
        return redirect(url_for('admin.my_rooms'))

    try:
        room_data = {
            'hotel_id': int(hotel_id),
            'number': int(number),
            'price': float(price),
            'type': room_type,
            'beds': int(beds) if beds else None,
            'jacuzzi': (jacuzzi == 'y')
        }
        if 'room_image' in request.files:
            img = request.files['room_image']
            if img and img.filename:
                room_data['image_data'] = base64.b64encode(img.read()).decode('utf-8')
        Room.create(**room_data)
        log_activity(f"Admin '{current_user.username}' added Room #{number} to {hotel.name}")
        flash(f'Room #{number} added successfully!', 'success')
    except Exception as e:
        flash(f'Error adding room: {str(e)}', 'danger')

    return redirect(url_for('admin.my_rooms'))


@admin_bp.route('/my-rooms/delete/<int:room_id>', methods=['POST'])
@login_required
@admin_required
def delete_room(room_id):
    room = Room.get(room_id)
    if not room:
        flash('Room not found', 'danger')
        return redirect(url_for('admin.my_rooms'))

    room_hotel = room.hotel
    if not room_hotel or room_hotel.owner_id != current_user.id:
        flash('You do not have permission to delete this room!', 'danger')
        return redirect(url_for('admin.my_rooms'))

    if room.reservations:
        flash(f'Cannot delete Room #{room.number} because it has reservations!', 'danger')
        return redirect(url_for('admin.my_rooms'))

    try:
        room_number = room.number
        hotel_name = room_hotel.name
        room.delete()
        log_activity(f"Admin '{current_user.username}' deleted Room #{room_number} from {hotel_name}")
        flash(f'Room #{room_number} deleted successfully!', 'success')
    except Exception as e:
        flash(f'Error deleting room: {str(e)}', 'danger')

    return redirect(url_for('admin.my_rooms'))


@admin_bp.route('/property/<int:property_id>/rooms')
@login_required
@admin_required
def property_rooms(property_id):
    hotel = Hotel.find_by_id_and_owner(property_id, current_user.id)
    if not hotel:
        flash('Property not found!', 'danger')
        return redirect(url_for('admin.my_properties'))
    rooms = Room.find_by_hotel(property_id)
    return render_template('admin/property_rooms.html', hotel=hotel, rooms=rooms)


@admin_bp.route('/property/<int:property_id>/rooms/add', methods=['POST'])
@login_required
@admin_required
def add_property_room(property_id):
    hotel = Hotel.find_by_id_and_owner(property_id, current_user.id)
    if not hotel:
        flash('Property not found!', 'danger')
        return redirect(url_for('admin.my_properties'))

    number = request.form.get('number')
    price = request.form.get('price')
    room_type = request.form.get('type')
    beds = request.form.get('beds')
    jacuzzi = request.form.get('jacuzzi')

    try:
        room_data = {
            'hotel_id': property_id,
            'number': int(number),
            'price': float(price),
            'type': room_type,
            'beds': int(beds) if beds else None,
            'jacuzzi': (jacuzzi == 'y')
        }
        if 'room_image' in request.files:
            img = request.files['room_image']
            if img and img.filename:
                room_data['image_data'] = base64.b64encode(img.read()).decode('utf-8')
        Room.create(**room_data)
        log_activity(f"Admin '{current_user.username}' added Room #{number} to {hotel.name}")
        flash(f'Room #{number} added successfully!', 'success')
    except Exception as e:
        flash(f'Error adding room: {str(e)}', 'danger')

    return redirect(url_for('admin.property_rooms', property_id=property_id))


@admin_bp.route('/property/<int:property_id>/rooms/<int:room_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_property_room(property_id, room_id):
    hotel = Hotel.find_by_id_and_owner(property_id, current_user.id)
    if not hotel:
        flash('Property not found!', 'danger')
        return redirect(url_for('admin.my_properties'))

    room = Room.get(room_id)
    if not room or room.hotel_id != property_id:
        flash('Room not found!', 'danger')
        return redirect(url_for('admin.property_rooms', property_id=property_id))

    if room.reservations:
        flash(f'Cannot delete Room #{room.number} — it has active reservations!', 'danger')
        return redirect(url_for('admin.property_rooms', property_id=property_id))

    try:
        room_number = room.number
        room.delete()
        log_activity(f"Admin '{current_user.username}' deleted Room #{room_number} from {hotel.name}")
        flash(f'Room #{room_number} deleted!', 'success')
    except Exception as e:
        flash(f'Error deleting room: {str(e)}', 'danger')

    return redirect(url_for('admin.property_rooms', property_id=property_id))


@admin_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@admin_required
def profile():
    from forms import ProfileForm
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
                return render_template('admin/profile.html', form=form)

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
                log_activity(f"Admin '{current_user.username}' updated their profile")
                flash('Profile updated successfully!', 'success')
            except Exception as e:
                flash(f'Error updating profile: {str(e)}', 'danger')
        else:
            flash('No changes were made', 'info')

        return redirect(url_for('admin.profile'))

    return render_template('admin/profile.html', form=form)


@admin_bp.route('/profile/remove-image', methods=['POST'])
@login_required
@admin_required
def remove_profile_image():
    try:
        current_user.update(profile_image=None)
        log_activity(f"Admin '{current_user.username}' removed their profile image")
        flash('Profile photo removed!', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('admin.profile'))


@admin_bp.route('/my-reservations')
@login_required
@admin_required
def my_reservations():
    my_hotels = Hotel.find_by_owner(current_user.id)
    my_hotel_ids = [h.id for h in my_hotels]

    if not my_hotel_ids:
        return render_template('admin/my_reservations.html', reservations=[], now=datetime.now())

    my_rooms = Room.find_by_hotel_ids(my_hotel_ids)
    my_room_ids = [r.id for r in my_rooms]

    if not my_room_ids:
        return render_template('admin/my_reservations.html', reservations=[], now=datetime.now())

    data = supabase.table('reservations').select('*').in_('room_id', my_room_ids).order('start_date', desc=True).execute()
    reservations = [Reservation(r) for r in (data.data or [])]

    return render_template('admin/my_reservations.html', reservations=reservations, now=datetime.now())
