from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from models import db, User, Room, Reservation, Activity, Hotel, HotelImage
from forms import RoomForm, ReservationForm, HotelForm
from datetime import datetime, timedelta
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


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Вземи само имотите на текущия admin
    my_hotels = Hotel.query.filter_by(owner_id=current_user.id).all()
    my_hotel_ids = [h.id for h in my_hotels]

    # Статистики само за неговите имоти
    total_my_hotels = len(my_hotels)
    total_my_rooms = Room.query.filter(Room.hotel_id.in_(my_hotel_ids)).count() if my_hotel_ids else 0

    # Резервации за неговите имоти
    total_my_reservations = 0
    revenue = 0

    if my_hotel_ids:
        # Намери всички стаи в неговите хотели
        my_rooms = Room.query.filter(Room.hotel_id.in_(my_hotel_ids)).all()
        my_room_ids = [r.id for r in my_rooms]

        if my_room_ids:
            # Резервации за неговите стаи
            reservations = Reservation.query.filter(Reservation.room_id.in_(my_room_ids)).all()
            total_my_reservations = len(reservations)

            # Приходи
            for res in reservations:
                if res.room:
                    revenue += res.room.price * res.nights

    # Общи статистики (за информация)
    total_users = User.query.count()

    # Последни активности
    recent_activities = Activity.query.order_by(Activity.timestamp.desc()).limit(10).all()

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
    """Преглед на всички имоти на текущия admin"""
    hotels = Hotel.query.filter_by(owner_id=current_user.id).all()
    return render_template('admin/my_properties.html', hotels=hotels, now=datetime.now())


@admin_bp.route('/my-properties/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_property():
    """Добавяне на нов имот"""
    if request.method == 'GET':
        return render_template('admin/add_property.html', now=datetime.now())

    # POST заявка
    name = request.form.get('name')
    property_type = request.form.get('property_type')
    description = request.form.get('description')
    address = request.form.get('address')
    city = request.form.get('city')
    country = request.form.get('country')
    stars = request.form.get('stars', 3)

    # Нови полета
    total_rooms = request.form.get('total_rooms', 1)
    max_guests = request.form.get('max_guests', 2)
    price_per_night = request.form.get('price_per_night')

    if not name:
        flash('Property name is required!', 'danger')
        return redirect(url_for('admin.add_property'))

    # Създаване на нов имот
    hotel = Hotel(
        name=name,
        property_type=property_type,
        description=description,
        address=address,
        city=city,
        country=country,
        stars=int(stars),
        owner_id=current_user.id,
        total_rooms=int(total_rooms) if total_rooms else 1,
        max_guests=int(max_guests) if max_guests else 2,
        price_per_night=float(price_per_night) if price_per_night and property_type != 'hotel' else None
    )

    # Обработка на снимки
    if 'main_image' in request.files:
        image = request.files['main_image']
        if image and image.filename:
            hotel.main_image = image.read()

    try:
        db.session.add(hotel)
        db.session.commit()

        # Обработка на галерия
        if 'gallery_images' in request.files:
            images = request.files.getlist('gallery_images')
            for img in images:
                if img and img.filename:
                    hotel_img = HotelImage(
                        hotel_id=hotel.id,
                        image_data=img.read()
                    )
                    db.session.add(hotel_img)
            db.session.commit()

        log_activity(f"Admin '{current_user.username}' added property '{name}'")
        flash(f'Property "{name}" added successfully!', 'success')
        return redirect(url_for('admin.my_properties'))

    except Exception as e:
        db.session.rollback()
        flash(f'Error adding property: {str(e)}', 'danger')
        return redirect(url_for('admin.add_property'))


@admin_bp.route('/my-properties/edit/<int:property_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_property(property_id):
    """Редактиране на имот (само ако е на текущия admin)"""
    hotel = Hotel.query.filter_by(id=property_id, owner_id=current_user.id).first_or_404()

    if request.method == 'GET':
        return render_template('admin/edit_property.html', hotel=hotel, now=datetime.now())

    # POST заявка
    hotel.name = request.form.get('name', hotel.name)
    hotel.property_type = request.form.get('property_type', hotel.property_type)
    hotel.description = request.form.get('description', hotel.description)
    hotel.address = request.form.get('address', hotel.address)
    hotel.city = request.form.get('city', hotel.city)
    hotel.country = request.form.get('country', hotel.country)
    hotel.stars = int(request.form.get('stars', hotel.stars))

    if 'main_image' in request.files:
        image = request.files['main_image']
        if image and image.filename:
            hotel.main_image = image.read()

    try:
        db.session.commit()
        log_activity(f"Admin '{current_user.username}' edited property '{hotel.name}'")
        flash(f'Property "{hotel.name}" updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating property: {str(e)}', 'danger')

    return redirect(url_for('admin.my_properties'))


@admin_bp.route('/my-properties/delete/<int:property_id>', methods=['POST'])
@login_required
@admin_required
def delete_property(property_id):
    """Изтриване на имот (само ако е на текущия admin)"""
    hotel = Hotel.query.filter_by(id=property_id, owner_id=current_user.id).first_or_404()

    # Проверка за стаи
    if hotel.rooms:
        flash(f'Cannot delete "{hotel.name}" because it has rooms!', 'danger')
        return redirect(url_for('admin.my_properties'))

    try:
        hotel_name = hotel.name
        db.session.delete(hotel)
        db.session.commit()
        log_activity(f"Admin '{current_user.username}' deleted property '{hotel_name}'")
        flash(f'Property "{hotel_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting property: {str(e)}', 'danger')

    return redirect(url_for('admin.my_properties'))


# СТАИ (само за имотите на текущия admin)
@admin_bp.route('/my-rooms')
@login_required
@admin_required
def my_rooms():
    """Преглед на всички стаи в имотите на текущия admin"""
    my_hotels = Hotel.query.filter_by(owner_id=current_user.id).all()
    my_hotel_ids = [h.id for h in my_hotels]

    rooms = Room.query.filter(Room.hotel_id.in_(my_hotel_ids)).all() if my_hotel_ids else []

    return render_template('admin/my_rooms.html', rooms=rooms, hotels=my_hotels, now=datetime.now())


@admin_bp.route('/my-rooms/add', methods=['POST'])
@login_required
@admin_required
def add_room():
    """Добавяне на стая към имот на текущия admin"""
    hotel_id = request.form.get('hotel_id')
    number = request.form.get('number')
    price = request.form.get('price')
    room_type = request.form.get('type')
    beds = request.form.get('beds')
    jacuzzi = request.form.get('jacuzzi')

    # Проверка дали хотелът принадлежи на текущия admin
    hotel = Hotel.query.filter_by(id=hotel_id, owner_id=current_user.id).first()
    if not hotel:
        flash('Hotel not found or you do not have permission!', 'danger')
        return redirect(url_for('admin.my_rooms'))

    try:
        room = Room(
            hotel_id=hotel_id,
            number=int(number),
            price=float(price),
            type=room_type,
            beds=int(beds) if beds else None,
            jacuzzi=(jacuzzi == 'y')
        )

        db.session.add(room)
        db.session.commit()

        log_activity(f"Admin '{current_user.username}' added Room #{number} to {hotel.name}")
        flash(f'Room #{number} added successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding room: {str(e)}', 'danger')

    return redirect(url_for('admin.my_rooms'))


@admin_bp.route('/my-rooms/delete/<int:room_id>', methods=['POST'])
@login_required
@admin_required
def delete_room(room_id):
    """Изтриване на стая (само ако е в имот на текущия admin)"""
    room = Room.query.get_or_404(room_id)

    # Проверка дали хотелът е на текущия admin
    if room.hotel.owner_id != current_user.id:
        flash('You do not have permission to delete this room!', 'danger')
        return redirect(url_for('admin.my_rooms'))

    if room.reservations:
        flash(f'Cannot delete Room #{room.number} because it has reservations!', 'danger')
        return redirect(url_for('admin.my_rooms'))

    try:
        room_number = room.number
        hotel_name = room.hotel.name
        db.session.delete(room)
        db.session.commit()
        log_activity(f"Admin '{current_user.username}' deleted Room #{room_number} from {hotel_name}")
        flash(f'Room #{room_number} deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting room: {str(e)}', 'danger')

    return redirect(url_for('admin.my_rooms'))


# РЕЗЕРВАЦИИ (само за имотите на текущия admin)
@admin_bp.route('/my-reservations')
@login_required
@admin_required
def my_reservations():
    """Преглед на резервации за имотите на текущия admin"""
    my_hotels = Hotel.query.filter_by(owner_id=current_user.id).all()
    my_hotel_ids = [h.id for h in my_hotels]

    if not my_hotel_ids:
        return render_template('admin/my_reservations.html', reservations=[], now=datetime.now())

    # Намери всички стаи в неговите хотели
    my_rooms = Room.query.filter(Room.hotel_id.in_(my_hotel_ids)).all()
    my_room_ids = [r.id for r in my_rooms]

    if not my_room_ids:
        return render_template('admin/my_reservations.html', reservations=[], now=datetime.now())

    # Резервации за неговите стаи
    reservations = Reservation.query.filter(Reservation.room_id.in_(my_room_ids)).order_by(
        Reservation.start_date.desc()).all()

    return render_template('admin/my_reservations.html', reservations=reservations, now=datetime.now())