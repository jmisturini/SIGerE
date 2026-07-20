from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='student')  # admin, teacher, student
    department = db.Column(db.String(120))
    registration = db.Column(db.String(50), unique=True, nullable=True, index=True)
    sector = db.Column(db.String(120), nullable=True)
    profile_type = db.Column(db.String(20), default='employee') # 'teacher' or 'employee'
    is_teacher = db.Column(db.Boolean, default=False) # Allows an employee to also act as a teacher
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active_user = db.Column(db.Boolean, default=True)
    force_password_change = db.Column(db.Boolean, default=True)

    reservations = db.relationship(
        'Reservation', backref='user', lazy=True,
        cascade='all, delete-orphan',
        foreign_keys='Reservation.user_id'
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_room_group(self):
        return self.role == 'room'

    @property
    def is_viewer(self):
        return self.role == 'viewer'

    @property
    def can_book(self):
        """Users who can create and manage their own reservations."""
        return self.role in ['admin', 'room']

    # Flask-Login uses this property to check if the user is allowed to log in
    @property
    def is_active(self):
        return self.is_active_user

    def __repr__(self):
        return f'<User {self.username}>'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Classroom(db.Model):
    __tablename__ = 'classrooms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    building = db.Column(db.String(120))
    floor = db.Column(db.String(20))
    capacity = db.Column(db.Integer, nullable=False, default=30)
    category = db.Column(db.String(30), nullable=False, default='classroom') # Increased length for new categories
    computer_count = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    reservations = db.relationship('Reservation', backref='classroom', lazy=True)

    def __repr__(self):
        return f'<Classroom {self.code}>'


class Reservation(db.Model):
    __tablename__ = 'reservations'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classrooms.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='approved')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    review_note = db.Column(db.Text)
    
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_reservations')
    teacher = db.relationship('User', foreign_keys=[teacher_id], backref='teaching_reservations')
    course = db.relationship('Course', backref='reservations')
    subject = db.relationship('Subject', backref='reservations')

    def __repr__(self):
        return f'<Reservation {self.id} - {self.title}>'

    @property
    def is_active(self):
        return self.status in ('pending', 'approved')

    def conflicts_with(self, other_start, other_end):
        """Return True if this reservation's time overlaps with the given window."""
        return self.start_time < other_end and other_start < self.end_time
    
class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

    subjects = db.relationship('Subject', backref='course', lazy=True)

    def __repr__(self):
        return f'<Course {self.code}>'


class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<Subject {self.code}>'
