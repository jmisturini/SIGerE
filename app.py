from flask import Flask, render_template, redirect, url_for, request
from config import Config
from extensions import db, login_manager
from models import User, Classroom, Reservation, Course, Subject, Holiday
from datetime import datetime, date, time, timedelta
import random

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)

    from auth import bp as auth_bp
    from main import bp as main_bp
    from classrooms import bp as classrooms_bp
    from reservations import bp as reservations_bp
    from admin import bp as admin_bp
    from totem import bp as totem_bp
    from schedule import bp as schedule_bp
    from public import bp as public_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(classrooms_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(totem_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(public_bp)

    @app.errorhandler(403)
    def forbidden(_):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def not_found(_):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def server_error(_):
        return render_template('errors/500.html'), 500

    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    @app.before_request
    def require_password_change():
        from flask_login import current_user
        if current_user.is_authenticated and current_user.force_password_change:
            allowed_endpoints = ['auth.change_password', 'auth.logout', 'static']
            if request.endpoint not in allowed_endpoints:
                return redirect(url_for('auth.change_password'))

    with app.app_context():
        db.create_all()
        seed_data()

    return app


def seed_data():
    """Seed initial demo data if DB is empty."""
    if User.query.count() == 0:
        print("Database is empty. Seeding data...")
        
        # 1. Create Admin
        admin = User(
            username='admin', email='admin@school.edu',
            full_name='System Administrator', role='admin',
            department='Administration', profile_type='employee',
            force_password_change=False
        )
        admin.set_password('admin123')
        db.session.add(admin)

        # 2. Create 100 Users (20 Employees [2 are teachers], 80 Teachers)
        first_names = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa", "Matthew", "Margaret", "Anthony", "Sandra", "Mark", "Ashley", "Donald", "Kimberly", "Steven", "Emily", "Paul", "Donna", "Andrew", "Michelle", "Joshua", "Carol", "Kenneth", "Amanda", "Kevin", "Melissa", "Brian", "Deborah", "George", "Stephanie", "Edward", "Rebecca"]
        last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores"]
        
        users_created = 0
        teachers_list = []
        
        # Create 20 Employees
        for i in range(1, 21):
            fname = random.choice(first_names)
            lname = random.choice(last_names)
            is_teacher_flag = (i in [1, 2]) # First 2 employees are also teachers
            
            e = User(
                username=f"employee{i}",
                email=f"employee{i}@school.edu",
                full_name=f"{fname} {lname}",
                role='room' if is_teacher_flag else 'viewer',
                sector="Administration",
                function=random.choice(["Coordinator", "Secretary", "Technician", "Director"]),
                profile_type='employee',
                is_teacher=is_teacher_flag,
                force_password_change=False
            )
            e.set_password('employee123')
            db.session.add(e)
            if is_teacher_flag:
                teachers_list.append(e)
            users_created += 1
            
        # Create 80 Teachers
        for i in range(1, 81):
            fname = random.choice(first_names)
            lname = random.choice(last_names)
            t = User(
                username=f"teacher{i}",
                email=f"teacher{i}@school.edu",
                full_name=f"{fname} {lname}",
                role='room',
                department=random.choice(["Science", "Math", "History", "Arts", "Languages", "Physical Ed"]),
                profile_type='teacher',
                force_password_change=False
            )
            t.set_password('teacher123')
            db.session.add(t)
            teachers_list.append(t)
            users_created += 1
            
        db.session.commit()
        print(f"Seeded {users_created} Users (20 Employees, 80 Teachers).")

        # 3. Create Rooms
        abbr_map = {'classroom': 'CR', 'auditorium': 'AU', 'kitchen': 'KI', 'computer_lab': 'CP', 'health_lab': 'HL'}
        
        # 1st Floor: 1 Auditorium, 2 Kitchens, 1 Classroom, 2 Computer Labs (6 rooms)
        # 2nd Floor: 5 Computer Labs, 8 Classrooms (13 rooms)
        # 3rd Floor: 3 Health Labs, 6 Classrooms (9 rooms)
        room_data = [
            # 1st Floor
            {"name": "Grand Auditorium", "category": "auditorium", "capacity": 150, "floor": "1st Floor", "computer_count": 0, "room_number": "101"},
            {"name": "Culinary Kitchen A", "category": "kitchen", "capacity": 15, "floor": "1st Floor", "computer_count": 0, "room_number": "102"},
            {"name": "Culinary Kitchen B", "category": "kitchen", "capacity": 15, "floor": "1st Floor", "computer_count": 0, "room_number": "103"},
            {"name": "Intro Classroom", "category": "classroom", "capacity": 30, "floor": "1st Floor", "computer_count": 0, "room_number": "104"},
            {"name": "Computer Lab A", "category": "computer_lab", "capacity": 40, "floor": "1st Floor", "computer_count": 40, "room_number": "105"},
            {"name": "Computer Lab B", "category": "computer_lab", "capacity": 40, "floor": "1st Floor", "computer_count": 40, "room_number": "106"},
            
            # 2nd Floor
            {"name": "Computer Lab C", "category": "computer_lab", "capacity": 35, "floor": "2nd Floor", "computer_count": 35, "room_number": "201"},
            {"name": "Computer Lab D", "category": "computer_lab", "capacity": 35, "floor": "2nd Floor", "computer_count": 35, "room_number": "202"},
            {"name": "Computer Lab E", "category": "computer_lab", "capacity": 35, "floor": "2nd Floor", "computer_count": 35, "room_number": "203"},
            {"name": "Computer Lab F", "category": "computer_lab", "capacity": 35, "floor": "2nd Floor", "computer_count": 35, "room_number": "204"},
            {"name": "Computer Lab G", "category": "computer_lab", "capacity": 35, "floor": "2nd Floor", "computer_count": 35, "room_number": "205"},
            {"name": "Classroom 206", "category": "classroom", "capacity": 30, "floor": "2nd Floor", "computer_count": 0, "room_number": "206"},
            {"name": "Classroom 207", "category": "classroom", "capacity": 30, "floor": "2nd Floor", "computer_count": 0, "room_number": "207"},
            {"name": "Classroom 208", "category": "classroom", "capacity": 30, "floor": "2nd Floor", "computer_count": 0, "room_number": "208"},
            {"name": "Classroom 209", "category": "classroom", "capacity": 30, "floor": "2nd Floor", "computer_count": 0, "room_number": "209"},
            {"name": "Classroom 210", "category": "classroom", "capacity": 30, "floor": "2nd Floor", "computer_count": 0, "room_number": "210"},
            {"name": "Classroom 211", "category": "classroom", "capacity": 30, "floor": "2nd Floor", "computer_count": 0, "room_number": "211"},
            {"name": "Classroom 212", "category": "classroom", "capacity": 30, "floor": "2nd Floor", "computer_count": 0, "room_number": "212"},
            {"name": "Classroom 213", "category": "classroom", "capacity": 30, "floor": "2nd Floor", "computer_count": 0, "room_number": "213"},
            
            # 3rd Floor
            {"name": "Health Lab A", "category": "health_lab", "capacity": 20, "floor": "3rd Floor", "computer_count": 0, "room_number": "301"},
            {"name": "Health Lab B", "category": "health_lab", "capacity": 20, "floor": "3rd Floor", "computer_count": 0, "room_number": "302"},
            {"name": "Health Lab C", "category": "health_lab", "capacity": 20, "floor": "3rd Floor", "computer_count": 0, "room_number": "303"},
            {"name": "Classroom 304", "category": "classroom", "capacity": 30, "floor": "3rd Floor", "computer_count": 0, "room_number": "304"},
            {"name": "Classroom 305", "category": "classroom", "capacity": 30, "floor": "3rd Floor", "computer_count": 0, "room_number": "305"},
            {"name": "Classroom 306", "category": "classroom", "capacity": 30, "floor": "3rd Floor", "computer_count": 0, "room_number": "306"},
            {"name": "Classroom 307", "category": "classroom", "capacity": 30, "floor": "3rd Floor", "computer_count": 0, "room_number": "307"},
            {"name": "Classroom 308", "category": "classroom", "capacity": 30, "floor": "3rd Floor", "computer_count": 0, "room_number": "308"},
            {"name": "Classroom 309", "category": "classroom", "capacity": 30, "floor": "3rd Floor", "computer_count": 0, "room_number": "309"},
        ]
        
        rooms = []
        for r_data in room_data:
            code = f"{abbr_map[r_data['category']]}{r_data['room_number']}"
            room = Classroom(
                code=code, name=r_data["name"], category=r_data["category"],
                capacity=r_data["capacity"], floor=r_data["floor"], building="Main Building",
                room_number=r_data["room_number"], computer_count=r_data["computer_count"], is_active=True
            )
            db.session.add(room)
            rooms.append(room)
            
        db.session.commit()
        print(f"Seeded {len(rooms)} Rooms (1 Aud, 2 Kitchens, 7 Comp Labs, 3 Health Labs, 15 Classrooms).")

        # 4. Create 50 Courses and 50 Subjects
        courses_list = []
        for i in range(1, 51):
            c = Course(name=f"Course {i}", code=f"C{i:03d}", is_active=True)
            db.session.add(c)
            courses_list.append(c)
            
        db.session.commit()
        
        subjects_list = []
        for i in range(1, 51):
            # Assign random course to subject
            random_course = random.choice(courses_list)
            s = Subject(name=f"Subject {i}", code=f"S{i:03d}", course_id=random_course.id, is_active=True)
            db.session.add(s)
            subjects_list.append(s)
            
        db.session.commit()
        print(f"Seeded 50 Courses and 50 Subjects.")

        # 5. Create 20 Reservations (Some happening today)
        all_bookers = teachers_list + [admin]
        time_slots = [
            (time(8, 0), time(10, 0)), (time(10, 0), time(12, 0)),
            (time(13, 0), time(15, 0)), (time(15, 0), time(17, 0)),
            (time(18, 0), time(20, 0)), (time(19, 0), time(21, 0))
        ]

        for i in range(1, 21):
            if i <= 5:
                # Force the first 5 reservations to be TODAY and overlapping NOW
                res_date = date.today()
                if res_date.weekday() == 6: # Skip Sunday
                    res_date += timedelta(days=1)
                    
                now_hour = datetime.now().hour
                start_hour = max(8, now_hour - 1) # Start 1 hour ago
                end_hour = min(20, now_hour + 2)  # End 2 hours from now
                start = time(start_hour, 0)
                end = time(end_hour, 0)
            else:
                # Spread the rest over the next 10 days
                res_date = date.today() + timedelta(days=random.randint(1, 10))
                if res_date.weekday() == 6: 
                    res_date += timedelta(days=1)
                start, end = random.choice(time_slots)
                
            room = random.choice(rooms)
            booker = random.choice(all_bookers)
            teacher = random.choice(teachers_list) if random.random() > 0.3 else None
            course = random.choice(courses_list)
            subject = random.choice(subjects_list)
            
            status = 'approved'
            if i in [10, 15]:
                status = 'pending'
                
            res = Reservation(
                user_id=booker.id,
                classroom_id=room.id,
                teacher_id=teacher.id if teacher else None,
                course_id=course.id,
                subject_id=subject.id,
                title=f"Class Event {i}",
                description="Scheduled class for students.",
                date=res_date,
                start_time=start,
                end_time=end,
                status=status
            )
            db.session.add(res)
            
        db.session.commit()
        print("Seeded 20 Reservations.")
        print("Seeding complete! Login: admin/admin123, teacher1/teacher123, employee1/employee123")

    else:
        print("Database already contains data. Skipping seed.")


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000)