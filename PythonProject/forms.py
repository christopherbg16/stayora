from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, IntegerField, FloatField, SelectField, BooleanField, DateField, \
    FileField, TextAreaField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, NumberRange, Optional
from flask_wtf.file import FileAllowed


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])


class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=255)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])


class RoomForm(FlaskForm):
    number = IntegerField('Room Number', validators=[DataRequired()])
    price = FloatField('Price per Night (€)', validators=[DataRequired()])
    type = SelectField('Room Type', choices=[('Standard', 'Standard'), ('Luxury', 'Luxury')],
                       validators=[DataRequired()])
    beds = IntegerField('Number of Beds (for Standard)', validators=[NumberRange(min=0)])
    jacuzzi = SelectField('Jacuzzi (for Luxury)', choices=[('n', 'No'), ('y', 'Yes')])
    image = FileField('Room Image', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])


class ReservationForm(FlaskForm):
    guest = StringField('Guest Name', validators=[DataRequired()])
    start_date = DateField('Check-in Date', validators=[DataRequired()])
    nights = IntegerField('Number of Nights', validators=[DataRequired(), NumberRange(min=1, max=30)])
    room_id = SelectField('Select Room', coerce=int, validators=[DataRequired()])


class ProfileForm(FlaskForm):
    email = StringField('Email', validators=[Email(), Length(max=255)])
    phone = StringField('Phone', validators=[Length(max=20)])
    address = TextAreaField('Address', validators=[Length(max=500)])
    current_password = PasswordField('Current Password')
    new_password = PasswordField('New Password', validators=[Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[EqualTo('new_password')])
    profile_image = FileField('Profile Photo', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])


class SearchRoomsForm(FlaskForm):
    start_date = DateField('Check-in Date', validators=[DataRequired()])
    nights = IntegerField('Number of Nights', validators=[DataRequired(), NumberRange(min=1, max=30)])


class HotelSearchForm(FlaskForm):
    """Форма за търсене на хотели (като Booking.com)"""
    destination = StringField('Destination', validators=[Optional()], render_kw={"placeholder": "Where are you going?"})
    check_in = DateField('Check-in', validators=[Optional()], render_kw={"placeholder": "Check-in date"})
    check_out = DateField('Check-out', validators=[Optional()], render_kw={"placeholder": "Check-out date"})
    guests = IntegerField('Guests', validators=[Optional(), NumberRange(min=1, max=10)], default=2)
    stars = SelectField('Star Rating', choices=[
        ('', 'Any'),
        ('5', '5 Stars'),
        ('4', '4+ Stars'),
        ('3', '3+ Stars'),
        ('2', '2+ Stars'),
        ('1', '1+ Star')
    ], validators=[Optional()])


# ========== НОВА ФОРМА ЗА ДОБАВЯНЕ/РЕДАКТИРАНЕ НА ИМОТИ (ЗА ADMIN) ==========
class HotelForm(FlaskForm):
    """Форма за добавяне и редактиране на имоти (хотели, апартаменти, вили, резорти)"""
    name = StringField('Property Name', validators=[DataRequired(), Length(min=2, max=255)])
    property_type = SelectField('Property Type', choices=[
        ('hotel', 'Hotel'),
        ('apartment', 'Apartment'),
        ('villa', 'Villa'),
        ('resort', 'Resort')
    ], validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional(), Length(max=2000)])
    address = StringField('Address', validators=[Optional(), Length(max=255)])
    city = StringField('City', validators=[DataRequired(), Length(min=2, max=100)])
    country = StringField('Country', validators=[DataRequired(), Length(min=2, max=100)])
    stars = SelectField('Stars', choices=[
        ('1', '1 Star'),
        ('2', '2 Stars'),
        ('3', '3 Stars'),
        ('4', '4 Stars'),
        ('5', '5 Stars')
    ], validators=[DataRequired()])
    main_image = FileField('Main Image', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    gallery_images = FileField('Gallery Images',
                               validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])

    # Валидация за името - да не е само празни интервали
    def validate_name(self, name):
        if not name.data or not name.data.strip():
            raise ValidationError('Property name cannot be empty.')