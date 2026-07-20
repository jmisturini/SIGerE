from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, IntegerField,
                     DateField, TimeField, TextAreaField, SelectField, BooleanField)
from wtforms.validators import (DataRequired, Email, EqualTo, Length,
                                ValidationError, Optional)
from datetime import date
from models import User, Classroom


class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(max=64)])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Full Name', validators=[DataRequired(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField(
        'Confirm Password', validators=[DataRequired(), EqualTo('password')]
    )
    role = SelectField(
        'Role', choices=[('student', 'Student'), ('teacher', 'Teacher')],
        default='student'
    )
    department = StringField('Department', validators=[Optional(), Length(max=120)])
    submit = SubmitField('Register')

    def validate_username(self, field):
        if User.query.filter_by(username=field.data).first():
            raise ValidationError('Username already taken.')

    def validate_email(self, field):
        if User.query.filter_by(email=field.data).first():
            raise ValidationError('Email already registered.')

class ClassroomForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=64)])
    code = StringField('Code', validators=[DataRequired(), Length(max=20)])
    floor = StringField('Floor', validators=[Optional(), Length(max=20)])
    capacity = IntegerField('Capacity', validators=[DataRequired()])
    category = SelectField('Category', choices=[
        ('classroom', 'Classroom'), 
        ('auditorium', 'Auditorium'),
        ('kitchen', 'Kitchen'),
        ('computer_lab', 'Computer Laboratory'),
        ('health_lab', 'Health Laboratory')
    ], default='classroom')

    computer_count = IntegerField('Number of Computers', validators=[Optional()])
    
    description = TextAreaField('Description', validators=[Optional()])
    is_active = BooleanField('Active', default=True)
    submit = SubmitField('Save')

    def validate_code(self, field):
        existing = Classroom.query.filter_by(code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Classroom code already exists.')
        
class ReservationForm(FlaskForm):
    classroom = SelectField('Classroom', coerce=int, validators=[DataRequired()])
    course = SelectField('Course', coerce=int, validators=[Optional()])
    subject = SelectField('Subject', coerce=int, validators=[Optional()])
    
    # These are the missing fields:
    teacher = SelectField('Teacher', coerce=int, validators=[Optional()])
    acknowledge_teacher_conflict = BooleanField('I acknowledge this teacher is already booked in another reservation at this time.', validators=[Optional()])
    
    title = StringField('Title / Subject', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description / Purpose', validators=[Optional()])
    date = DateField('Date', validators=[DataRequired()])
    start_time = TimeField('Start Time', validators=[DataRequired()])
    end_time = TimeField('End Time', validators=[DataRequired()])
    submit = SubmitField('Request Reservation')

    def validate_end_time(self, field):
        if self.start_time.data and field.data:
            if field.data <= self.start_time.data:
                raise ValidationError('End time must be after start time.')

class TeacherForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Full Name', validators=[DataRequired(), Length(max=120)])
    registration = StringField('Teacher ID / Registration', validators=[Optional(), Length(max=50)])
    department = StringField('Department', validators=[Optional(), Length(max=120)])
    role = SelectField('Access Level', choices=[
        ('room', 'Room Booker'), 
        ('admin', 'Administrator')
    ], default='room')
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    is_active_user = BooleanField('Active', default=True)
    submit = SubmitField('Save Teacher')

    def validate_username(self, field):
        existing = User.query.filter_by(username=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Username already taken.')

    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Email already registered.')

    def validate_registration(self, field):
        if field.data:
            existing = User.query.filter_by(registration=field.data).first()
            if existing and existing.id != getattr(self, '_obj_id', None):
                raise ValidationError('This Registration ID is already in use.')

class EmployeeForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Full Name', validators=[DataRequired(), Length(max=120)])
    registration = StringField('Employee ID / Registration', validators=[Optional(), Length(max=50)])
    sector = StringField('Sector', validators=[Optional(), Length(max=120)])
    function = StringField('Function', validators=[Optional(), Length(max=120)])
    role = SelectField('Access Level', choices=[
        ('viewer', 'Viewer (Read Only)'),
        ('room', 'Room Booker'), 
        ('admin', 'Administrator')
    ], default='viewer')
    is_teacher = BooleanField('Also register as Teacher (can be assigned to reservations)')
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    is_active_user = BooleanField('Active', default=True)
    submit = SubmitField('Save Employee')

    def validate_username(self, field):
        existing = User.query.filter_by(username=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Username already taken.')

    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Email already registered.')

    def validate_registration(self, field):
        if field.data:
            existing = User.query.filter_by(registration=field.data).first()
            if existing and existing.id != getattr(self, '_obj_id', None):
                raise ValidationError('This Registration ID is already in use.')

class ChangePasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Update Password')
    
class CourseForm(FlaskForm):
    name = StringField('Course Name', validators=[DataRequired(), Length(max=120)])
    code = StringField('Course Code', validators=[DataRequired(), Length(max=20)])
    description = TextAreaField('Description', validators=[Optional()])
    is_active = BooleanField('Active', default=True)
    submit = SubmitField('Save Course')

    def validate_code(self, field):
        from models import Course
        existing = Course.query.filter_by(code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Course code already exists.')

class SubjectForm(FlaskForm):
    name = StringField('Subject Name', validators=[DataRequired(), Length(max=120)])
    code = StringField('Subject Code', validators=[DataRequired(), Length(max=20)])
    course_id = SelectField('Belongs to Course', coerce=int, validators=[Optional()])
    description = TextAreaField('Description', validators=[Optional()])
    is_active = BooleanField('Active', default=True)
    submit = SubmitField('Save Subject')

    def validate_code(self, field):
        from models import Subject
        existing = Subject.query.filter_by(code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Subject code already exists.')
