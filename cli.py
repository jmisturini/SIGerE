# cli.py
import click
from flask.cli import with_appcontext
from extensions import db
from models import User, Classroom, Reservation, Course, Subject, Holiday, TeacherBasePay
from datetime import datetime, date, time, timedelta
import random

# ============================================================
# COMANDO: flask seed
# ============================================================

@click.command('seed')
@with_appcontext
def seed_command():
    """Popula o banco de dados com dados de demonstração."""
    seed_data()
    click.echo(click.style('✅ Seed concluído com sucesso!', fg='green', bold=True))


# ============================================================
# COMANDO: flask seed --admin-only  (opcional)
# ============================================================

@click.command('seed-admin')
@with_appcontext
def seed_admin_command():
    """Cria apenas o usuário administrador (útil para produção)."""
    if User.query.filter_by(username='admin').first():
        click.echo(click.style('⚠️  Admin já existe. Pulando.', fg='yellow'))
        return

    admin = User(
        username='admin',
        email='admin@school.edu',
        full_name='Administrador do Sistema',
        role='admin',
        department='Administration',
        profile_type='employee',
        force_password_change=False
    )
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.commit()
    click.echo(click.style('✅ Admin criado: admin / admin123', fg='green'))


# ============================================================
# COMANDO: flask reset-db  (opcional, cuidado!)
# ============================================================

@click.command('reset-db')
@with_appcontext
def reset_db_command():
    """REMOVE TODOS OS DADOS e recria as tabelas. Use com cuidado!"""
    confirm = click.prompt(
        '⚠️  Isso APAGARÁ todos os dados. Digite RESET para confirmar',
        type=str
    )
    if confirm != 'RESET':
        click.echo(click.style('❌ Operação cancelada.', fg='red'))
        return

    db.drop_all()
    db.create_all()
    click.echo(click.style('🗑️  Banco de dados recriado.', fg='yellow'))

    seed = click.confirm('Deseja popular com dados de demonstração?')
    if seed:
        seed_data()
        click.echo(click.style('✅ Seed aplicado.', fg='green'))


# ============================================================
# SEED DATA (movido de app.py)
# ============================================================

def seed_data():
    """Seed initial demo data if the database is empty."""
    if User.query.count() == 0:
        print("O banco de dados está vazio. Populando dados...")
        
        # Busca os roles criados pelo seed_permissions()
        super_admin_role = Role.query.filter_by(name='super_admin').first()
        teacher_role = Role.query.filter_by(name='teacher').first()
        employee_role = Role.query.filter_by(name='employee').first()
        
        # 1. Create Admin
        admin = User(
            username='admin', email='admin@school.edu',
            full_name='Administrador do Sistema', role='admin',
            department='Administration', profile_type='employee',
            force_password_change=False,
            role_id=super_admin_role.id
        )
        admin.set_password('admin123') # ADICIONADO: Definir a senha do admin
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
                unity=random.choice(["Unidade Centro", "Unidade Norte", "Unidade Sul"]),
                force_password_change=False,
                role_id=employee_role.id
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
                unity=random.choice(["Unidade Centro", "Unidade Norte", "Unidade Sul"]),
                registration=f"REG-{i:04d}", # ADICIONADO: Gera matrícula
                force_password_change=False,
                role_id=teacher_role.id
            )
            t.set_password('teacher123')
            db.session.add(t)
            teachers_list.append(t)
            users_created += 1  # CORREÇÃO: Adicionar contagem
            
        db.session.commit()
        print(f"{users_created} Usuários criados (20 Funcionários, 80 Professores).")

        # 3. Create Rooms (Strict layout requested by user)
        # 3.1 Create Room Categories
        if RoomCategory.query.count() == 0:
            categories = [
                RoomCategory(name="Sala de Aula", code="classroom", abbr="SA"),
                RoomCategory(name="Auditório", code="auditorium", abbr="AU"),
                RoomCategory(name="Cozinha", code="kitchen", abbr="CO"),
                RoomCategory(name="Laboratório de Informática", code="computer_lab", abbr="LI"),
                RoomCategory(name="Laboratório de Saúde", code="health_lab", abbr="LS")
            ]
            db.session.add_all(categories)
            db.session.commit()
            print("Categorias de sala criadas.")
            
        # Busca os IDs das categorias para usar nas salas
        cat_classroom = RoomCategory.query.filter_by(code='classroom').first()
        cat_aud = RoomCategory.query.filter_by(code='auditorium').first()
        cat_kitchen = RoomCategory.query.filter_by(code='kitchen').first()
        cat_comp = RoomCategory.query.filter_by(code='computer_lab').first()
        cat_health = RoomCategory.query.filter_by(code='health_lab').first()
        
        room_data = [
            # 1st Floor
            {"name": "Auditório Principal", "category_id": cat_aud.id, "capacity": 150, "floor": "1º Andar", "computer_count": 0, "room_number": "101"},
            {"name": "Cozinha Experimental A", "category_id": cat_kitchen.id, "capacity": 15, "floor": "1º Andar", "computer_count": 0, "room_number": "102"},
            {"name": "Cozinha Experimental B", "category_id": cat_kitchen.id, "capacity": 15, "floor": "1º Andar", "computer_count": 0, "room_number": "103"},
            {"name": "Sala de Aula 104", "category_id": cat_classroom.id, "capacity": 30, "floor": "1º Andar", "computer_count": 0, "room_number": "104"},
            {"name": "Lab de Informática A", "category_id": cat_comp.id, "capacity": 40, "floor": "1º Andar", "computer_count": 40, "room_number": "105"},
            {"name": "Lab de Informática B", "category_id": cat_comp.id, "capacity": 40, "floor": "1º Andar", "computer_count": 40, "room_number": "106"},
            
            # 2nd Floor
            {"name": "Lab de Informática C", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "201"},
            {"name": "Lab de Informática D", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "202"},
            {"name": "Lab de Informática E", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "203"},
            {"name": "Lab de Informática F", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "204"},
            {"name": "Lab de Informática G", "category_id": cat_comp.id, "capacity": 35, "floor": "2º Andar", "computer_count": 35, "room_number": "205"},
            {"name": "Sala de Aula 206", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "206"},
            {"name": "Sala de Aula 207", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "207"},
            {"name": "Sala de Aula 208", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "208"},
            {"name": "Sala de Aula 209", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "209"},
            {"name": "Sala de Aula 210", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "210"},
            {"name": "Sala de Aula 211", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "211"},
            {"name": "Sala de Aula 212", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "212"},
            {"name": "Sala de Aula 213", "category_id": cat_classroom.id, "capacity": 30, "floor": "2º Andar", "computer_count": 0, "room_number": "213"},
            
            # 3rd Floor
            {"name": "Lab de Saúde A", "category_id": cat_health.id, "capacity": 20, "floor": "3º Andar", "computer_count": 0, "room_number": "301"},
            {"name": "Lab de Saúde B", "category_id": cat_health.id, "capacity": 20, "floor": "3º Andar", "computer_count": 0, "room_number": "302"},
            {"name": "Lab de Saúde C", "category_id": cat_health.id, "capacity": 20, "floor": "3º Andar", "computer_count": 0, "room_number": "303"},
            {"name": "Sala de Aula 304", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "304"},
            {"name": "Sala de Aula 305", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "305"},
            {"name": "Sala de Aula 306", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "306"},
            {"name": "Sala de Aula 307", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "307"},
            {"name": "Sala de Aula 308", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "308"},
            {"name": "Sala de Aula 309", "category_id": cat_classroom.id, "capacity": 30, "floor": "3º Andar", "computer_count": 0, "room_number": "309"},
        ]
        
        rooms = []
        for r_data in room_data:
            # Pega a abreviação da categoria dinamicamente
            cat_obj = RoomCategory.query.get(r_data['category_id'])
            code = f"{cat_obj.abbr}{r_data['room_number']}" if cat_obj.abbr else r_data['room_number']
            
            room = Classroom(
                code=code, name=r_data["name"], category_id=r_data["category_id"],
                capacity=r_data["capacity"], floor=r_data["floor"], building="Bloco Principal",
                room_number=r_data["room_number"], computer_count=r_data["computer_count"], is_active=True
            )
            db.session.add(room)
            rooms.append(room)
            
        db.session.commit()
        print(f"{len(rooms)} Salas criadas.")

        # 4. Create 50 Courses and 50 Subjects
        courses_list = []
        for i in range(1, 51):
            c = Course(name=f"Curso {i}", code=f"C{i:03d}", is_active=True)
            db.session.add(c)
            courses_list.append(c)
            
        db.session.commit()
        
        subjects_list = []
        for i in range(1, 51):
            random_course = random.choice(courses_list)
            s = Subject(name=f"Disciplina {i}", code=f"S{i:03d}", course_id=random_course.id, is_active=True)
            db.session.add(s)
            subjects_list.append(s)
            
        db.session.commit()
        print("50 Cursos e 50 Disciplinas criados.")

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
                # Garantir janela mínima de 1h e respeitar o limite do dia
                start_hour = min(now_hour, 19)  # máximo 19h para caber até 20h
                end_hour = min(start_hour + 1, 20)
                start = time(start_hour, 0)
                end = time(end_hour, 0)
            else:
                # Reservas futuras aleatórias
                res_date = date.today() + timedelta(days=random.randint(1, 30))
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
                user_id=booker.id, classroom_id=room.id, teacher_id=teacher.id if teacher else None,
                course_id=course.id, subject_id=subject.id, title=f"Aula/Evento {i}",
                description="Aula agendada para alunos.", date=res_date, start_time=start, end_time=end, status=status
            )
            db.session.add(res)
            
        db.session.commit()
        print("20 Reservas criadas.")

        # 6. Create Sample Base Payment (Using new Django migrated model)
        sample_teachers = teachers_list[:3]
        for i, teacher in enumerate(sample_teachers):
            base_pay = TeacherBasePay(
                teacher_id=teacher.id,
                course_id=courses_list[i].id,
                month_start='2024-02',
                month_end='2024-07',
                budget_code=95000,
                complement='Contrato Inicial',
                weekly_workload=20,
                accountable_id=admin.id
            )
            db.session.add(base_pay)
            
        db.session.commit()
        print("Lançamentos de pagamento base de exemplo criados.")
        print("População concluída! Logins: admin/admin123, teacher1/teacher123, employee1/employee123")

    else:
        print("O banco de dados já contém dados. Pulando população.")


def register_cli_commands(app):
    """Registra os comandos CLI na aplicação Flask."""
    app.cli.add_command(seed_command)
    app.cli.add_command(seed_admin_command)
    app.cli.add_command(reset_db_command)