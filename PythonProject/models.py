from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timedelta

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)  # Make nullable for Google users
    google_id = db.Column(db.String(255), unique=True, nullable=True)  # NEW
    role = db.Column(db.String(20), default='user')
    profile_image = db.Column(db.LargeBinary, nullable=True)
    email = db.Column(db.String(255), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


    # Relationships
    reservations = db.relationship('Reservation', backref='user', lazy=True)
    owned_hotels = db.relationship('Hotel', backref='owner', lazy=True)
    reviews = db.relationship('HotelReview', backref='user', lazy=True)
    property_reservations = db.relationship('PropertyReservation', backref='user', lazy=True)

    def get_id(self):
        return str(self.id)


class Hotel(db.Model):
    __tablename__ = 'hotels'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    property_type = db.Column(db.String(50), default='hotel')
    description = db.Column(db.Text, nullable=True)
    address = db.Column(db.String(255), nullable=True)
    city = db.Column(db.String(100), nullable=True)
    country = db.Column(db.String(100), nullable=True)
    stars = db.Column(db.Integer, default=3)
    main_image = db.Column(db.LargeBinary, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    total_rooms = db.Column(db.Integer, default=1)
    max_guests = db.Column(db.Integer, default=2)
    price_per_night = db.Column(db.Float, nullable=True)

    avg_rating = db.Column(db.Numeric(2, 1), default=0)
    review_count = db.Column(db.Integer, default=0)

    # Relationships
    rooms = db.relationship('Room', backref='hotel', lazy=True, cascade='all, delete-orphan')
    images = db.relationship('HotelImage', backref='hotel', lazy=True, cascade='all, delete-orphan')
    reviews = db.relationship('HotelReview', backref='hotel', lazy=True, cascade='all, delete-orphan')
    property_reservations = db.relationship('PropertyReservation', backref='hotel', lazy=True,
                                            cascade='all, delete-orphan')

    @property
    def display_price(self):
        if self.property_type == 'hotel':
            if self.rooms:
                return min([r.price for r in self.rooms])
            return 0
        else:
            return self.price_per_night or 0

    @property
    def total_available_rooms(self):
        if self.property_type == 'hotel':
            return len(self.rooms)
        else:
            return self.total_rooms

    @property
    def rating_display(self):
        if self.review_count > 0:
            return f"{float(self.avg_rating):.1f}"
        return "New"

    @property
    def rating_category(self):
        if self.review_count == 0:
            return "New"
        rating = float(self.avg_rating)
        if rating >= 9.0:
            return "Superb"
        elif rating >= 8.0:
            return "Very good"
        elif rating >= 7.0:
            return "Good"
        elif rating >= 6.0:
            return "Pleasant"
        else:
            return "Okay"

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description[:100] + '...' if self.description and len(
                self.description) > 100 else self.description,
            'city': self.city,
            'country': self.country,
            'stars': self.stars,
            'property_type': self.property_type,
            'rooms_count': len(self.rooms) if self.property_type == 'hotel' else self.total_rooms,
            'min_price': self.display_price,
            'max_guests': self.max_guests,
            'avg_rating': float(self.avg_rating) if self.avg_rating else 0,
            'review_count': self.review_count
        }


class Room(db.Model):
    __tablename__ = 'rooms'

    id = db.Column(db.Integer, primary_key=True)
    hotel_id = db.Column(db.Integer, db.ForeignKey('hotels.id'), nullable=True)
    number = db.Column(db.Integer, unique=True, nullable=False)
    price = db.Column(db.Float, nullable=False)
    type = db.Column(db.String(50), nullable=False)
    beds = db.Column(db.Integer, nullable=True)
    jacuzzi = db.Column(db.Boolean, default=False)
    image_data = db.Column(db.LargeBinary, nullable=True)

    reservations = db.relationship('Reservation', backref='room', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'number': self.number,
            'price': self.price,
            'type': self.type,
            'beds': self.beds,
            'jacuzzi': self.jacuzzi
        }

    def info(self):
        if self.type == "Standard":
            return f"Room #{self.number} (Standard) - {self.beds} beds - {self.price} €"
        else:
            jac = "Yes" if self.jacuzzi else "No"
            return f"Room #{self.number} (Luxury) - Jacuzzi: {jac} - {self.price} €"


class HotelImage(db.Model):
    __tablename__ = 'hotel_images'

    id = db.Column(db.Integer, primary_key=True)
    hotel_id = db.Column(db.Integer, db.ForeignKey('hotels.id'), nullable=False)
    image_data = db.Column(db.LargeBinary, nullable=False)
    caption = db.Column(db.String(255), nullable=True)
    is_primary = db.Column(db.Boolean, default=False)


class Reservation(db.Model):
    __tablename__ = 'reservations'

    id = db.Column(db.Integer, primary_key=True)
    room_id = db.Column(db.Integer, db.ForeignKey('rooms.id'), nullable=False)
    guest = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    nights = db.Column(db.Integer, nullable=False)

    @property
    def end_date(self):
        return self.start_date + timedelta(days=self.nights)

    def info(self):
        return f"{self.guest} – Room #{self.room.number} – {self.start_date} to {self.end_date()} ({self.nights} nights)"


class PropertyReservation(db.Model):
    __tablename__ = 'property_reservations'

    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('hotels.id'), nullable=False)
    guest = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    nights = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def end_date(self):
        return self.start_date + timedelta(days=self.nights)


class HotelReview(db.Model):
    __tablename__ = 'hotel_reviews'

    id = db.Column(db.Integer, primary_key=True)
    hotel_id = db.Column(db.Integer, db.ForeignKey('hotels.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    rating = db.Column(db.Numeric(2, 1), nullable=False)
    review_text = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Activity(db.Model):
    __tablename__ = 'activities'

    id = db.Column(db.Integer, primary_key=True)
    activity = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class TrendingDestination(db.Model):
    __tablename__ = 'trending_destinations'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    country = db.Column(db.String(100), default='Bulgaria')
    image_data = db.Column(db.LargeBinary, nullable=True)
    property_count = db.Column(db.Integer, default=0)
    display_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'country': self.country,
            'property_count': self.property_count
        }


class Promotion(db.Model):
    __tablename__ = 'promotions'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    discount_percent = db.Column(db.Integer, default=0)
    valid_until = db.Column(db.Date, nullable=True)
    image_data = db.Column(db.LargeBinary, nullable=True)
    is_active = db.Column(db.Boolean, default=True)