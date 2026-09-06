# Defaults de data/dhora usam lambda: passar datetime.now(timezone.utc) direto
# avaliaria UMA vez no import, congelando created_at/updated_at no boot da app.
from datetime import datetime, timezone
import json
import re

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db, login_manager

# Model representing an educational unit (campus/school) — base do multi-tenancy.
# Cada unidade possui seus próprios salas, cursos, reservas, estoque e lançamentos.
class Unity(db.Model):
    __tablename__ = 'unities'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)
    address = db.Column(db.String(255))
    phone = db.Column(db.String(30))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    classrooms = db.relationship('Classroom', backref='unity', lazy=True)

    def __repr__(self):
        return f'<Unity {self.code}>'

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
    # Unidade educacional do usuário. NULL = conta global (ex: super admin,
    # que pode operar em qualquer unidade via seletor).
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
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

    # NOVAS PROPRIEDADES E MÉTODOS:
    @property
    def permissions(self):
        """Retorna o set de códigos de permissão do usuário."""
        if self.role_obj:
            return {p.code for p in self.role_obj.permissions}
        return set()

    def has_permission(self, perm_code):
        """Verifica se o usuário possui uma permissão específica."""
        if not self.permissions:
            return False
        # Se o usuário tiver a permissão curinga '*', ele tem acesso a tudo
        if '*' in self.permissions:
            return True
        return perm_code in self.permissions

    # Propriedades legado atualizadas para compatibilidade
    @property
    def is_admin(self):
        return self.has_permission('*') or (self.role_obj and self.role_obj.name == 'admin')

    @property
    def can_book(self):
        return self.has_permission('reservation:create')

# Flask-Login loader to fetch user by ID for session management
@login_manager.user_loader
def load_user(user_id):
    # CORREÇÃO: User.query.get() é API legada removida no SQLAlchemy 2.x.
    # db.session.get() é a forma correta desde SQLAlchemy 1.4+.
    return db.session.get(User, int(user_id))

# Model representing the physical rooms (Classrooms, Auditoriums, Labs)
class Classroom(db.Model):
    __tablename__ = 'classrooms'
    __table_args__ = (
        # O mesmo código de sala pode existir em unidades diferentes
        db.UniqueConstraint('unity_id', 'code', name='uq_classroom_unity_code'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    code = db.Column(db.String(20), nullable=False, index=True)
    room_number = db.Column(db.String(20), nullable=True)
    building = db.Column(db.String(120))
    floor = db.Column(db.String(20))
    capacity = db.Column(db.Integer, nullable=False, default=30)
    category_id = db.Column(db.Integer, db.ForeignKey('room_categories.id'), nullable=False)
    computer_count = db.Column(db.Integer, default=0)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationship for reservations in this room
    reservations = db.relationship('Reservation', backref='classroom', lazy=True)
    category = db.relationship('RoomCategory')

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
    # CORREÇÃO: Adicionar regras ondelete para evitar registros órfãos
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    classroom_id = db.Column(db.Integer, db.ForeignKey('classrooms.id', ondelete='CASCADE'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id', ondelete='SET NULL'), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id', ondelete='SET NULL'), nullable=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    # Unidade da sala reservada (desnormalizado de classrooms.unity_id para filtros rápidos)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    date = db.Column(db.Date, nullable=False, index=True)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='approved') # approved, pending, cancelled
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
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
    # Unidade educacional da reserva
    unity = db.relationship('Unity')

    def __repr__(self):
        return f'<Reservation {self.id} - {self.title}>'

    @property
    def is_active(self):
        return self.status in ('pending', 'approved')

# Model representing academic courses
class Course(db.Model):
    __tablename__ = 'courses'
    __table_args__ = (
        db.UniqueConstraint('unity_id', 'code', name='uq_course_unity_code'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(20), nullable=False, index=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)

    subjects = db.relationship('Subject', backref='course', lazy=True)

    def __repr__(self):
        return f'<Course {self.code}>'

# Model representing subjects within courses
class Subject(db.Model):
    __tablename__ = 'subjects'
    __table_args__ = (
        db.UniqueConstraint('unity_id', 'code', name='uq_subject_unity_code'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(20), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    description = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)

    def __repr__(self):
        return f'<Subject {self.code}>'

# Model representing holidays to block scheduling
class Holiday(db.Model):
    __tablename__ = 'holidays'
    __table_args__ = (
        db.Index('idx_holiday_active', 'date', 'is_active'), # CORREÇÃO: Índice para queries rápidas
        # Feriados nacionais podem ser cadastrados em todas as unidades na mesma data
        db.UniqueConstraint('unity_id', 'date', name='uq_holiday_unity_date'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)

    def __repr__(self):
        return f'<Holiday {self.name} on {self.date}>'
    
# Model for Teacher Base Pay (Semester)
class TeacherBasePay(db.Model):
    __tablename__ = 'teacher_base_pay'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    month_start = db.Column(db.String(7), nullable=False) # YYYY-MM
    month_end = db.Column(db.String(7), nullable=False)
    budget_code = db.Column(db.Integer, nullable=False)
    complement = db.Column(db.String(100))
    weekly_workload = db.Column(db.Integer, nullable=False)
    monthly_hour = db.Column(db.Integer, default=0)
    semester_hour = db.Column(db.Integer, default=0)
    accountable_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    term_generated = db.Column(db.Integer, default=1)

    teacher = db.relationship('User', foreign_keys=[teacher_id])
    course = db.relationship('Course')
    accountable = db.relationship('User', foreign_keys=[accountable_id])

# Model for Teacher Additive Payment
class TeacherAdditivePayment(db.Model):
    __tablename__ = 'teacher_additive_payment'
    id = db.Column(db.Integer, primary_key=True)
    # CORREÇÃO: Adicionar ondelete='CASCADE' para excluir aditivos se o lançamento base for excluído
    base_release_id = db.Column(db.Integer, db.ForeignKey('teacher_base_pay.id', ondelete='CASCADE'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id', ondelete='SET NULL'), nullable=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    month_start = db.Column(db.String(7), nullable=False)
    month_end = db.Column(db.String(7), nullable=False)
    additional_hour = db.Column(db.Integer, nullable=False)
    monthly_hour = db.Column(db.Integer, default=0)
    semester_hour = db.Column(db.Integer, default=0)
    complement = db.Column(db.String(100))
    accountable_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    term_generated = db.Column(db.Integer, default=1)

    # CORREÇÃO: Adicionar cascade no relacionamento
    base_release = db.relationship('TeacherBasePay', backref=db.backref('additives', cascade='all, delete-orphan'))
    course = db.relationship('Course')
    accountable = db.relationship('User', foreign_keys=[accountable_id])

# Model for Teacher Overtime Pay
class TeacherOvertimePay(db.Model):
    __tablename__ = 'teacher_overtime_pay'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    teaching_level = db.Column(db.String(50), nullable=False) # E.g., 'Técnico', 'Superior'
    weekly_workload = db.Column(db.Integer, nullable=False)
    hourly_value = db.Column(db.Numeric(10, 2), nullable=False) # 10 dígitos no total, 2 decimais
    budget_code = db.Column(db.String(18), nullable=False)
    shift = db.Column(db.String(50), nullable=False) # E.g., 'Matutino', 'Vespertino', 'Noturno'
    multiple_dates = db.Column(db.String(255))
    justification = db.Column(db.String(100))
    month_base = db.Column(db.String(7), nullable=False) # YYYY-MM
    accountable_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    teacher = db.relationship('User', foreign_keys=[teacher_id])
    accountable = db.relationship('User', foreign_keys=[accountable_id])

# Tabela de junção entre Roles e Permissions
role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

# Modelo de Permissões Granulares
class Permission(db.Model):
    __tablename__ = 'permissions'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False)
    module = db.Column(db.String(30), nullable=False)
    action = db.Column(db.String(30), nullable=False)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f'<Permission {self.code}>'

# Modelo de Roles (Grupos de Permissões)
class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    label = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    is_system = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    permissions = db.relationship('Permission', secondary='role_permissions', backref='roles')
    # Relacionamento reverso para User (role_obj)
    users = db.relationship('User', backref='role_obj', lazy=True)

class RoomCategory(db.Model):
    __tablename__ = 'room_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False) # Ex: "Laboratório de Informática"
    code = db.Column(db.String(20), unique=True, nullable=False) # Ex: "computer_lab"
    is_active = db.Column(db.Boolean, default=True)

    # Abreviação para gerar o código da sala automaticamente (ex: CP, CR, AU)
    abbr = db.Column(db.String(3), nullable=True)

    def __repr__(self):
        return f'<RoomCategory {self.name}>'


# ─────────────────────────────────────────────────────────────────────────────
# Módulo Cozinha — fichas técnicas (DOCX), preparações e ingredientes.
# As tabelas usam o prefixo kitchen_/technical_ para não colidir com as tabelas
# legadas do módulo de cozinha v1 (removido), que podem existir no banco.
# ─────────────────────────────────────────────────────────────────────────────

# Ficha Técnica Operacional enviada (arquivo .docx lido pelo kitchen_parser).
class TechnicalSheet(db.Model):
    __tablename__ = 'technical_sheets'
    id = db.Column(db.Integer, primary_key=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    uploaded_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    # pending: aguardando "Salvar Ficha Técnica" | saved: preparação gerada
    # | error: falha na leitura do arquivo
    status = db.Column(db.String(20), nullable=False, default='pending')
    parse_error = db.Column(db.Text)
    # Conteúdo extraído (JSON) enquanto pendente; limpo após salvar.
    data_json = db.Column(db.Text)

    uploaded_by = db.relationship('User')
    recipe = db.relationship('KitchenRecipe', backref='technical_sheet',
                             uselist=False, cascade='all, delete-orphan')

    @property
    def parsed_data(self):
        try:
            return json.loads(self.data_json) if self.data_json else None
        except (ValueError, TypeError):
            return None

    def __repr__(self):
        return f'<TechnicalSheet {self.original_filename}>'


# Preparação (receita) gerada a partir de uma ficha técnica salva.
class KitchenRecipe(db.Model):
    __tablename__ = 'kitchen_recipes'
    id = db.Column(db.Integer, primary_key=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    technical_sheet_id = db.Column(db.Integer,
                                   db.ForeignKey('technical_sheets.id', ondelete='CASCADE'),
                                   nullable=True)
    name = db.Column(db.String(255), nullable=False)
    equipments = db.Column(db.Text)
    utensils = db.Column(db.Text)
    prep_time = db.Column(db.String(255))   # tempo de preparo (texto livre da ficha)
    yield_info = db.Column(db.String(255))  # rendimento
    steps_text = db.Column(db.Text)         # modo de preparo geral (um passo por linha)
    general_notes = db.Column(db.Text)      # observações técnicas
    allergens = db.Column(db.Text)          # alergênicos
    references = db.Column(db.Text)         # referências bibliográficas
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    preparations = db.relationship('KitchenPreparation', backref='recipe',
                                   cascade='all, delete-orphan',
                                   order_by='KitchenPreparation.position',
                                   lazy=True)

    @property
    def step_list(self):
        return [s for s in (self.steps_text or '').split('\n') if s.strip()]

    @property
    def base_portions(self):
        """Rendimento base em porções para recálculo de quantidades: o MENOR
        número do texto de rendimento, ignorando o que está entre parênteses
        ('4 a 6 porções (aprox. 20 unidades)' → 4). None se não houver número."""
        yield_text = re.sub(r'\([^)]*\)', ' ', self.yield_info or '')
        numbers = re.findall(r'\d+(?:[.,]\d+)?', yield_text)
        if not numbers:
            return None
        return min(float(n.replace(',', '.')) for n in numbers)

    @property
    def ingredient_count(self):
        """Apenas ingredientes ativos — os desativados não entram na requisição."""
        return sum(1 for p in self.preparations for i in p.ingredients if i.is_active)

    def __repr__(self):
        return f'<KitchenRecipe {self.name}>'


# Sub-preparação dentro da receita ("Massa do Bolo de Carne", "Purê de Batatas"...).
# Receitas com múltiplas preparações exibem uma lista de ingredientes por grupo.
class KitchenPreparation(db.Model):
    __tablename__ = 'kitchen_preparations'
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer,
                          db.ForeignKey('kitchen_recipes.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    position = db.Column(db.Integer, default=0)

    ingredients = db.relationship('KitchenRecipeIngredient', backref='preparation',
                                  cascade='all, delete-orphan',
                                  order_by='KitchenRecipeIngredient.position',
                                  lazy=True)

    def __repr__(self):
        return f'<KitchenPreparation {self.name}>'


# Ingrediente de uma sub-preparação, com especificação técnica, quantidade e unidade.
class KitchenRecipeIngredient(db.Model):
    __tablename__ = 'kitchen_recipe_ingredients'
    id = db.Column(db.Integer, primary_key=True)
    preparation_id = db.Column(db.Integer,
                               db.ForeignKey('kitchen_preparations.id', ondelete='CASCADE'),
                               nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    specification = db.Column(db.Text)
    quantity = db.Column(db.Float)          # valor numérico quando identificável
    quantity_raw = db.Column(db.String(50)) # texto original ('400', '15 e 3', 'a gosto')
    unit = db.Column(db.String(30))         # g, ml, un, '' (a gosto)...
    position = db.Column(db.Integer, default=0)
    # Ingrediente desativado continua na preparação, mas não aparece na
    # requisição de compra (Compras).
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    def __repr__(self):
        return f'<KitchenRecipeIngredient {self.name}>'