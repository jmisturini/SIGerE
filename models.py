from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager
import math

# Model representing the application users (Admins, Teachers, Employees)
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='viewer') # admin, room, viewer
    department = db.Column(db.String(120))
    registration = db.Column(db.String(50), unique=True, nullable=True, index=True)
    sector = db.Column(db.String(120), nullable=True)
    function = db.Column(db.String(120), nullable=True)
    profile_type = db.Column(db.String(20), default='employee') # 'teacher' or 'employee'
    is_teacher = db.Column(db.Boolean, default=False) # Allows an employee to also act as a teacher
    force_password_change = db.Column(db.Boolean, default=True)
    unity = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active_user = db.Column(db.Boolean, default=True)

    # Relationship for reservations made by this user
    reservations = db.relationship(
        'Reservation', backref='user', lazy=True,
        foreign_keys='Reservation.user_id'
    )

    # Method to hash the password before saving to DB
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # Method to verify the password during login
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Helper properties for role checking
    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_room_group(self):
        return self.role == 'room'

    @property
    def is_viewer(self):
        return self.role == 'viewer'

    # Property to check if user can book rooms (Admins and Room Bookers)
    @property
    def can_book(self):
        return self.role in ['admin', 'room']

    # Flask-Login property to check if the user account is active
    @property
    def is_active(self):
        return self.is_active_user

    def __repr__(self):
        return f'<User {self.username}>'

# Flask-Login loader to fetch user by ID for session management
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Model representing the physical rooms (Classrooms, Auditoriums, Labs)
class Classroom(db.Model):
    __tablename__ = 'classrooms'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    room_number = db.Column(db.String(20), nullable=True)
    building = db.Column(db.String(120))
    floor = db.Column(db.String(20))
    capacity = db.Column(db.Integer, nullable=False, default=30)
    category = db.Column(db.String(30), nullable=False, default='classroom')
    computer_count = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship for reservations in this room
    reservations = db.relationship('Reservation', backref='classroom', lazy=True)

    def __repr__(self):
        return f'<Classroom {self.code}>'

# Model representing a reservation event
class Reservation(db.Model):
    __tablename__ = 'reservations'
    __table_args__ = (
        db.Index('idx_reservation_conflict', 'classroom_id', 'date', 'status'),
        db.Index('idx_reservation_teacher_date', 'teacher_id', 'date', 'status'),
    )
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
    status = db.Column(db.String(20), nullable=False, default='approved') # approved, pending, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    review_note = db.Column(db.Text)

    # Relationship for the teacher assigned to this reservation
    teacher = db.relationship('User', foreign_keys=[teacher_id], backref='teaching_reservations')
    # Relationship for the admin who reviewed the reservation (if pending)
    reviewer = db.relationship('User', foreign_keys=[reviewed_by], backref='reviewed_reservations')
    # Relationship for the course linked to this reservation
    course = db.relationship('Course', backref='reservations')
    # Relationship for the subject linked to this reservation
    subject = db.relationship('Subject', backref='reservations')

    def __repr__(self):
        return f'<Reservation {self.id} - {self.title}>'

    @property
    def is_active(self):
        return self.status in ('pending', 'approved')

# Model representing academic courses
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

# Model representing subjects within courses
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

# Model representing holidays to block scheduling
class Holiday(db.Model):
    __tablename__ = 'holidays'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, unique=True, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<Holiday {self.name} on {self.date}>'
    
# Model representing the payment level (e.g., Técnico, Superior)
class PaymentLevel(db.Model):
    __tablename__ = 'payment_levels'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False) 

# Model for Teacher Base Pay (Semester)
class TeacherBasePay(db.Model):
    __tablename__ = 'teacher_base_pay'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    month_start = db.Column(db.String(7), nullable=False) # YYYY-MM
    month_end = db.Column(db.String(7), nullable=False)
    budget_code = db.Column(db.Integer, nullable=False)
    complement = db.Column(db.String(100))
    weekly_workload = db.Column(db.Integer, nullable=False)
    monthly_hour = db.Column(db.Integer, default=0)
    semester_hour = db.Column(db.Integer, default=0)
    accountable_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    term_generated = db.Column(db.Integer, default=1)

    teacher = db.relationship('User', foreign_keys=[teacher_id])
    course = db.relationship('Course')
    accountable = db.relationship('User', foreign_keys=[accountable_id])

# Model for Teacher Additive Payment
class TeacherAdditivePayment(db.Model):
    __tablename__ = 'teacher_additive_payment'
    id = db.Column(db.Integer, primary_key=True)
    base_release_id = db.Column(db.Integer, db.ForeignKey('teacher_base_pay.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    month_start = db.Column(db.String(7), nullable=False)
    month_end = db.Column(db.String(7), nullable=False)
    additional_hour = db.Column(db.Integer, nullable=False)
    monthly_hour = db.Column(db.Integer, default=0)
    semester_hour = db.Column(db.Integer, default=0)
    complement = db.Column(db.String(100))
    accountable_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    term_generated = db.Column(db.Integer, default=1)

    base_release = db.relationship('TeacherBasePay', backref='additives')
    course = db.relationship('Course')
    accountable = db.relationship('User', foreign_keys=[accountable_id])

# Model for Teacher Overtime Pay
class TeacherOvertimePay(db.Model):
    __tablename__ = 'teacher_overtime_pay'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    teaching_level = db.Column(db.String(50), nullable=False) # E.g., 'Técnico', 'Superior'
    weekly_workload = db.Column(db.Integer, nullable=False)
    hourly_value = db.Column(db.Float, nullable=False)
    budget_code = db.Column(db.String(18), nullable=False)
    shift = db.Column(db.String(50), nullable=False) # E.g., 'Matutino', 'Vespertino', 'Noturno'
    multiple_dates = db.Column(db.String(255))
    justification = db.Column(db.String(100))
    month_base = db.Column(db.String(7), nullable=False) # YYYY-MM
    accountable_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    teacher = db.relationship('User', foreign_keys=[teacher_id])
    accountable = db.relationship('User', foreign_keys=[accountable_id])