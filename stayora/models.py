from datetime import datetime, timedelta
from flask_login import UserMixin
from supabase_client import supabase


def _parse_date(val):
    if isinstance(val, str):
        return datetime.fromisoformat(val).date() if 'T' in val else datetime.strptime(val, '%Y-%m-%d').date()
    return val


def _parse_dt(val):
    if isinstance(val, str):
        return datetime.fromisoformat(val.replace('Z', '+00:00'))
    return val


class BaseModel:
    def __init__(self, data=None):
        if data:
            self.__dict__.update(data)

    def __repr__(self):
        return f'<{self.__class__.__name__} id={getattr(self, "id", None)}>'


class User(UserMixin, BaseModel):
    def __init__(self, data=None):
        super().__init__(data)
        # Parse created_at to datetime for templates that call .strftime()
        if hasattr(self, 'created_at') and isinstance(self.created_at, str):
            try:
                self.created_at = _parse_dt(self.created_at)
            except Exception:
                pass

    @classmethod
    def get(cls, user_id):
        data = supabase.table('users').select('*').eq('id', user_id).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def find_by_username(cls, username):
        data = supabase.table('users').select('*').eq('username', username).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def find_by_google_id(cls, google_id):
        data = supabase.table('users').select('*').eq('google_id', google_id).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def find_by_email(cls, email):
        data = supabase.table('users').select('*').eq('email', email).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def count(cls):
        data = supabase.table('users').select('*', count='exact').execute()
        return data.count if data.count is not None else len(data.data or [])

    @classmethod
    def create(cls, **kwargs):
        if 'id' not in kwargs:
            max_id = supabase.table('users').select('id').order('id', desc=True).limit(1).execute()
            kwargs['id'] = (max_id.data[0]['id'] + 1) if (max_id.data and max_id.data[0].get('id')) else 1
        data = supabase.table('users').insert(kwargs).execute()
        return cls(data.data[0]) if data.data else None

    def update(self, **kwargs):
        supabase.table('users').update(kwargs).eq('id', self.id).execute()
        self.__dict__.update(kwargs)

    def delete(self):
        supabase.table('users').delete().eq('id', self.id).execute()

    @property
    def owned_hotels(self):
        data = supabase.table('hotels').select('*').eq('owner_id', self.id).execute()
        return [Hotel(r) for r in (data.data or [])]

    @property
    def owned_hotels_count(self):
        data = supabase.table('hotels').select('id', count='exact').eq('owner_id', self.id).execute()
        return data.count if data.count is not None else len(data.data or [])


class Hotel(BaseModel):
    @classmethod
    def get(cls, hotel_id):
        data = supabase.table('hotels').select('*').eq('id', hotel_id).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def find_by_owner(cls, owner_id):
        data = supabase.table('hotels').select('*').eq('owner_id', owner_id).execute()
        return [cls(r) for r in (data.data or [])]

    @classmethod
    def find_by_id_and_owner(cls, hotel_id, owner_id):
        data = supabase.table('hotels').select('*').eq('id', hotel_id).eq('owner_id', owner_id).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def count(cls):
        data = supabase.table('hotels').select('*', count='exact').execute()
        return data.count if data.count is not None else len(data.data or [])

    @classmethod
    def count_by_type(cls, property_type):
        data = supabase.table('hotels').select('*', count='exact').eq('property_type', property_type).execute()
        return data.count if data.count is not None else len(data.data or [])

    @classmethod
    def count_distinct_countries(cls):
        data = supabase.table('hotels').select('country').execute()
        return len(set(r['country'] for r in (data.data or []) if r.get('country')))

    @classmethod
    def search(cls, destination=None, property_type=None, sort_by='recommended', min_price=None, max_price=None, stars=None, min_rating=None):
        query = supabase.table('hotels').select('*')
        if destination:
            query = query.or_(f"city.ilike.%{destination}%,country.ilike.%{destination}%")
        if property_type and property_type != 'all':
            query = query.eq('property_type', property_type)
        if min_price:
            query = query.gte('price_per_night', min_price)
        if max_price:
            query = query.lte('price_per_night', max_price)
        if stars:
            if len(stars) == 1:
                query = query.eq('stars', stars[0])
            else:
                query = query.in_('stars', stars)
        if min_rating:
            query = query.gte('avg_rating', min_rating)
        sort_map = {
            'price_asc': ('price_per_night', False),
            'price_desc': ('price_per_night', True),
            'rating_desc': ('avg_rating', True),
            'popularity': ('review_count', True),
        }
        if sort_by in sort_map:
            col, desc = sort_map[sort_by]
            query = query.order(col, desc=desc)
        data = query.execute()
        return [cls(r) for r in (data.data or [])]

    @classmethod
    def create(cls, **kwargs):
        if 'id' not in kwargs:
            max_id = supabase.table('hotels').select('id').order('id', desc=True).limit(1).execute()
            kwargs['id'] = (max_id.data[0]['id'] + 1) if (max_id.data and max_id.data[0].get('id')) else 1
        data = supabase.table('hotels').insert(kwargs).execute()
        return cls(data.data[0]) if data.data else None

    def update(self, **kwargs):
        supabase.table('hotels').update(kwargs).eq('id', self.id).execute()
        self.__dict__.update(kwargs)

    def delete(self):
        supabase.table('hotels').delete().eq('id', self.id).execute()

    @property
    def rooms(self):
        if not hasattr(self, '_rooms'):
            data = supabase.table('rooms').select('*').eq('hotel_id', self.id).execute()
            self._rooms = [Room(r) for r in (data.data or [])]
        return self._rooms

    @rooms.setter
    def rooms(self, val):
        self._rooms = val

    @property
    def images(self):
        if not hasattr(self, '_images'):
            data = supabase.table('hotel_images').select('*').eq('hotel_id', self.id).execute()
            self._images = [HotelImage(r) for r in (data.data or [])]
        return self._images

    @images.setter
    def images(self, val):
        self._images = val

    @property
    def reviews(self):
        if not hasattr(self, '_reviews'):
            data = supabase.table('hotel_reviews').select('*').eq('hotel_id', self.id).execute()
            self._reviews = [HotelReview(r) for r in (data.data or [])]
        return self._reviews

    @reviews.setter
    def reviews(self, val):
        self._reviews = val

    @property
    def display_price(self):
        if getattr(self, 'property_type', None) in ('hotel', 'villa', 'resort'):
            rooms_data = supabase.table('rooms').select('price').eq('hotel_id', self.id).execute()
            prices = [r['price'] for r in (rooms_data.data or []) if r.get('price')]
            return min(prices) if prices else 0
        return getattr(self, 'price_per_night', 0) or 0

    @property
    def rating_display(self):
        rc = getattr(self, 'review_count', 0) or 0
        if rc > 0:
            ar = getattr(self, 'avg_rating', 0) or 0
            return f'{float(ar):.1f}'
        return 'New'

    @property
    def rating_category(self):
        rc = getattr(self, 'review_count', 0) or 0
        if rc == 0:
            return 'New'
        rating = float(getattr(self, 'avg_rating', 0) or 0)
        if rating >= 9.0:
            return 'Superb'
        elif rating >= 8.0:
            return 'Very good'
        elif rating >= 7.0:
            return 'Good'
        elif rating >= 6.0:
            return 'Pleasant'
        return 'Okay'

    @property
    def min_price(self):
        return self.display_price


class Room(BaseModel):
    @classmethod
    def get(cls, room_id):
        data = supabase.table('rooms').select('*').eq('id', room_id).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def find_by_hotel(cls, hotel_id):
        data = supabase.table('rooms').select('*').eq('hotel_id', hotel_id).execute()
        return [cls(r) for r in (data.data or [])]

    @classmethod
    def find_by_hotel_ids(cls, hotel_ids):
        if not hotel_ids:
            return []
        data = supabase.table('rooms').select('*').in_('hotel_id', hotel_ids).execute()
        return [cls(r) for r in (data.data or [])]

    @classmethod
    def count_by_hotel_ids(cls, hotel_ids):
        if not hotel_ids:
            return 0
        data = supabase.table('rooms').select('id', count='exact').in_('hotel_id', hotel_ids).execute()
        return data.count if data.count is not None else len(data.data or [])

    @classmethod
    def create(cls, **kwargs):
        if 'id' not in kwargs:
            max_id = supabase.table('rooms').select('id').order('id', desc=True).limit(1).execute()
            kwargs['id'] = (max_id.data[0]['id'] + 1) if (max_id.data and max_id.data[0].get('id')) else 1
        data = supabase.table('rooms').insert(kwargs).execute()
        return cls(data.data[0]) if data.data else None

    def update(self, **kwargs):
        supabase.table('rooms').update(kwargs).eq('id', self.id).execute()
        self.__dict__.update(kwargs)

    def delete(self):
        supabase.table('rooms').delete().eq('id', self.id).execute()

    @property
    def hotel(self):
        if not hasattr(self, '_hotel') and getattr(self, 'hotel_id', None):
            data = supabase.table('hotels').select('*').eq('id', self.hotel_id).execute()
            self._hotel = Hotel(data.data[0]) if data.data else None
            return self._hotel
        return getattr(self, '_hotel', None)

    @hotel.setter
    def hotel(self, val):
        self._hotel = val

    @property
    def reservations(self):
        if not hasattr(self, '_reservations'):
            data = supabase.table('reservations').select('*').eq('room_id', self.id).execute()
            self._reservations = [Reservation(r) for r in (data.data or [])]
        return self._reservations

    @reservations.setter
    def reservations(self, val):
        self._reservations = val

    @property
    def has_active_reservations(self):
        today = datetime.now().date()
        for r in self.reservations:
            r_start = r.start_date
            if isinstance(r_start, str):
                try:
                    r_start = datetime.fromisoformat(r_start.replace('Z', '+00:00')).date() if 'T' in r_start else datetime.strptime(r_start, '%Y-%m-%d').date()
                except Exception:
                    continue
            r_end = r_start + timedelta(days=getattr(r, 'nights', 0))
            if r_end >= today:
                return True
        return False

    def to_dict(self):
        return {
            'id': self.id,
            'number': getattr(self, 'number', None),
            'price': getattr(self, 'price', None),
            'beds': getattr(self, 'beds', None)
        }

    def info(self):
        price = getattr(self, 'price', 0)
        beds = getattr(self, 'beds', 0)
        num = getattr(self, 'number', 0)
        return f'Room #{num} - {beds} beds - {price} €'


class HotelImage(BaseModel):
    @classmethod
    def find_by_hotel(cls, hotel_id):
        data = supabase.table('hotel_images').select('*').eq('hotel_id', hotel_id).execute()
        return [cls(r) for r in (data.data or [])]

    @classmethod
    def create(cls, **kwargs):
        if 'id' not in kwargs:
            max_id = supabase.table('hotel_images').select('id').order('id', desc=True).limit(1).execute()
            kwargs['id'] = (max_id.data[0]['id'] + 1) if (max_id.data and max_id.data[0].get('id')) else 1
        data = supabase.table('hotel_images').insert(kwargs).execute()
        return cls(data.data[0]) if data.data else None


class Reservation(BaseModel):
    def __init__(self, data=None):
        super().__init__(data)
        # Ensure start_date is a date object for templates
        if hasattr(self, 'start_date') and isinstance(self.start_date, str):
            try:
                self.start_date = _parse_date(self.start_date)
            except Exception:
                pass

    @classmethod
    def get(cls, reservation_id):
        data = supabase.table('reservations').select('*').eq('id', reservation_id).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def find_by_guest(cls, guest):
        data = supabase.table('reservations').select('*').eq('guest', guest).execute()
        return [cls(r) for r in (data.data or [])]

    @classmethod
    def find_by_room_ids(cls, room_ids):
        if not room_ids:
            return []
        data = supabase.table('reservations').select('*').in_('room_id', room_ids).execute()
        return [cls(r) for r in (data.data or [])]

    @classmethod
    def count_by_room_ids(cls, room_ids):
        if not room_ids:
            return 0
        data = supabase.table('reservations').select('id', count='exact').in_('room_id', room_ids).execute()
        return data.count if data.count is not None else len(data.data or [])

    @classmethod
    def create(cls, **kwargs):
        data = supabase.table('reservations').insert(kwargs).execute()
        return cls(data.data[0]) if data.data else None

    def delete(self):
        supabase.table('reservations').delete().eq('id', self.id).execute()

    @property
    def end_date(self):
        start = _parse_date(getattr(self, 'start_date', None))
        if start:
            return start + timedelta(days=getattr(self, 'nights', 0))
        return None

    @property
    def room(self):
        rid = getattr(self, 'room_id', None)
        if rid is None:
            return None
        if not hasattr(self, '_room'):
            data = supabase.table('rooms').select('*').eq('id', rid).execute()
            r = Room(data.data[0]) if data.data else None
            if r:
                hotel_data = supabase.table('hotels').select('*').eq('id', r.hotel_id).execute()
                r.hotel = Hotel(hotel_data.data[0]) if hotel_data.data else None
            self._room = r
        return self._room

    @room.setter
    def room(self, val):
        self._room = val

    def info(self):
        r = self.room
        room_num = r.number if r else '?'
        return f'{self.guest} – Room #{room_num} – {self.start_date} to {self.end_date} ({self.nights} nights)'


class PropertyReservation(BaseModel):
    def __init__(self, data=None):
        super().__init__(data)
        # Ensure start_date is a date object for templates
        if hasattr(self, 'start_date') and isinstance(self.start_date, str):
            try:
                self.start_date = _parse_date(self.start_date)
            except Exception:
                pass

    @classmethod
    def get(cls, reservation_id):
        data = supabase.table('property_reservations').select('*').eq('id', reservation_id).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def find_by_guest(cls, guest):
        data = supabase.table('property_reservations').select('*').eq('guest', guest).execute()
        return [cls(r) for r in (data.data or [])]

    @classmethod
    def create(cls, **kwargs):
        if 'id' not in kwargs:
            max_id = supabase.table('property_reservations').select('id').order('id', desc=True).limit(1).execute()
            kwargs['id'] = (max_id.data[0]['id'] + 1) if (max_id.data and max_id.data[0].get('id')) else 1
        data = supabase.table('property_reservations').insert(kwargs).execute()
        return cls(data.data[0]) if data.data else None

    def delete(self):
        supabase.table('property_reservations').delete().eq('id', self.id).execute()

    @property
    def end_date(self):
        start = _parse_date(getattr(self, 'start_date', None))
        if start:
            return start + timedelta(days=getattr(self, 'nights', 0))
        return None

    @property
    def hotel(self):
        pid = getattr(self, 'property_id', None)
        if pid is None:
            return None
        if not hasattr(self, '_hotel'):
            data = supabase.table('hotels').select('*').eq('id', pid).execute()
            self._hotel = Hotel(data.data[0]) if data.data else None
        return self._hotel

    @hotel.setter
    def hotel(self, val):
        self._hotel = val


class HotelReview(BaseModel):
    def __init__(self, data=None):
        super().__init__(data)
        if hasattr(self, 'created_at') and isinstance(self.created_at, str):
            try:
                self.created_at = _parse_dt(self.created_at)
            except Exception:
                pass

    @classmethod
    def find_by_hotel(cls, hotel_id):
        data = supabase.table('hotel_reviews').select('*').eq('hotel_id', hotel_id).execute()
        return [cls(r) for r in (data.data or [])]


class Activity(BaseModel):
    @classmethod
    def create(cls, **kwargs):
        if 'id' not in kwargs:
            max_id = supabase.table('activities').select('id').order('id', desc=True).limit(1).execute()
            kwargs['id'] = (max_id.data[0]['id'] + 1) if (max_id.data and max_id.data[0].get('id')) else 1
        data = supabase.table('activities').insert(kwargs).execute()
        return cls(data.data[0]) if data.data else None

    @classmethod
    def get_recent(cls, limit=10):
        data = supabase.table('activities').select('*').order('timestamp', desc=True).limit(limit).execute()
        return [cls(r) for r in (data.data or [])]


class TrendingDestination(BaseModel):
    @classmethod
    def get_active(cls, limit=6):
        # Some Supabase/PostgREST schemas use SMALLINT for boolean-like columns.
        # Try filtering by True first, but fall back to 1 if the server rejects the boolean.
        try:
            data = supabase.table('trending_destinations').select('*').eq('is_active', True).order('display_order').limit(limit).execute()
        except Exception:
            data = supabase.table('trending_destinations').select('*').eq('is_active', 1).order('display_order').limit(limit).execute()
        return [cls(r) for r in (data.data or [])]

    def to_dict(self):
        return {
            'id': self.id,
            'name': getattr(self, 'name', ''),
            'country': getattr(self, 'country', ''),
            'property_count': getattr(self, 'property_count', 0)
        }


class Promotion(BaseModel):
    @classmethod
    def get_active(cls):
        # Same fallback for promotions.is_active
        try:
            data = supabase.table('promotions').select('*').eq('is_active', True).execute()
        except Exception:
            data = supabase.table('promotions').select('*').eq('is_active', 1).execute()
        return [cls(r) for r in (data.data or [])]


def log_activity(activity_text):
    try:
        Activity.create(
            activity=f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {activity_text}',
            timestamp=datetime.now().isoformat()
        )
    except Exception:
        pass


def check_room_conflict(room_id, start_date, end_date):
    data = supabase.table('reservations').select('*').eq('room_id', room_id).execute()
    for r in (data.data or []):
        r_start = _parse_date(r.get('start_date'))
        if not r_start:
            continue
        r_end = r_start + timedelta(days=r.get('nights', 0))
        if r_start < end_date and r_end > start_date:
            return True
    return False


def check_property_conflict(property_id, start_date, end_date):
    data = supabase.table('property_reservations').select('*').eq('property_id', property_id).execute()
    for r in (data.data or []):
        r_start = _parse_date(r.get('start_date'))
        if not r_start:
            continue
        r_end = r_start + timedelta(days=r.get('nights', 0))
        if r_start < end_date and r_end > start_date:
            return True
    return False


def get_conflicting_room_ids(start_date, end_date):
    data = supabase.table('reservations').select('*').execute()
    conflicting = []
    for r in (data.data or []):
        r_start = _parse_date(r.get('start_date'))
        if not r_start:
            continue
        r_end = r_start + timedelta(days=r.get('nights', 0))
        if r_start < end_date and r_end > start_date:
            conflicting.append(r['room_id'])
    return conflicting
