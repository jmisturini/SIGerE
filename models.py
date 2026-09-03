# CORREÇÃO: datetime.utcnow foi substituído por datetime.now(timezone.utc) em todos os
# defaults — a função sem fuso está deprecada desde o Python 3.12 e será removida.
from datetime import datetime, date, timedelta, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db, login_manager
import math

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
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

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
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
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
    def is_room_group(self):
        return self.has_permission('reservation:create')

    @property
    def is_viewer(self):
        return self.role_obj and self.role_obj.name == 'viewer'

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
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

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
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
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
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    month_start = db.Column(db.String(7), nullable=False) # YYYY-MM
    month_end = db.Column(db.String(7), nullable=False)
    budget_code = db.Column(db.Integer, nullable=False)
    complement = db.Column(db.String(100))
    weekly_workload = db.Column(db.Integer, nullable=False)
    monthly_hour = db.Column(db.Integer, default=0)
    semester_hour = db.Column(db.Integer, default=0)
    accountable_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
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
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))
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
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

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
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    permissions = db.relationship('Permission', secondary='role_permissions', backref='roles')
    # Relacionamento reverso para User (role_obj)
    users = db.relationship('User', backref='role_obj', lazy=True)

# =============================================================================
# COZINHA: Ingredientes, Estoque e Receitas
# =============================================================================

# Unidades de medida aceitas para os ingredientes (código -> rótulo exibido)
UNIT_LABELS = {
    'g': 'g (grama)', 'kg': 'kg (quilo)', 'ml': 'ml (mililitro)', 'l': 'L (litro)',
    'un': 'un (unidade)', 'dz': 'dz (dúzia)', 'colher_sopa': 'colher de sopa',
    'colher_cha': 'colher de chá', 'xicara': 'xícara', 'pitada': 'pitada',
    'dente': 'dente', 'folha': 'folha', 'fatia': 'fatia', 'lata': 'lata',
    'caixa': 'caixa', 'pacote': 'pacote', 'garrafa': 'garrafa', 'pote': 'pote',
}

# Símbolo curto para exibição junto a quantidades (tabelas e alertas)
UNIT_SYMBOLS = {
    'g': 'g', 'kg': 'kg', 'ml': 'ml', 'l': 'L', 'un': 'un', 'dz': 'dz',
    'colher_sopa': 'colher (sopa)', 'colher_cha': 'colher (chá)', 'xicara': 'xícara',
    'pitada': 'pitada', 'dente': 'dente', 'folha': 'folha', 'fatia': 'fatia',
    'lata': 'lata', 'caixa': 'caixa', 'pacote': 'pacote', 'garrafa': 'garrafa', 'pote': 'pote',
}

# Categorias padrão (seções de mercado) criadas na primeira execução do sistema
DEFAULT_INGREDIENT_CATEGORIES = [
    ('Hortifruti', 1), ('Frios e Laticínios', 2), ('Carnes e Aves', 3),
    ('Peixes e Frutos do Mar', 4), ('Grãos e Cereais', 5), ('Temperos e Especiarias', 6),
    ('Confeitaria', 7), ('Enlatados e Conservas', 8), ('Padaria', 9), ('Bebidas', 10),
    ('Congelados', 11), ('Limpeza', 12), ('Outros', 99),
]

# Seção de mercado para agrupar ingredientes (Frios, Hortifruti, Grãos...)
class IngredientCategory(db.Model):
    __tablename__ = 'ingredient_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), unique=True, nullable=False)
    display_order = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, default=True)

    ingredients = db.relationship('Ingredient', backref='category', lazy=True)

    def __repr__(self):
        return f'<IngredientCategory {self.name}>'

# Model representing a culinary ingredient with stock control
class Ingredient(db.Model):
    __tablename__ = 'ingredients'
    __table_args__ = (
        # O mesmo ingrediente pode existir em unidades diferentes (estoques separados)
        db.UniqueConstraint('unity_id', 'name', name='uq_ingredient_unity_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    unit = db.Column(db.String(20), nullable=False, default='un')
    stock_quantity = db.Column(db.Float, nullable=False, default=0.0)
    minimum_stock = db.Column(db.Float, nullable=False, default=0.0)
    unit_price = db.Column(db.Float, nullable=True) # preço de compra por unidade registrada (R$)
    category_id = db.Column(db.Integer, db.ForeignKey('ingredient_categories.id'), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    recipe_links = db.relationship(
        'RecipeIngredient', backref='ingredient', lazy=True,
        cascade='all, delete-orphan'
    )
    movements = db.relationship(
        'StockMovement', backref='ingredient', lazy=True,
        cascade='all, delete-orphan', order_by='StockMovement.created_at.desc()'
    )
    batches = db.relationship(
        'StockBatch', backref='ingredient', lazy=True,
        cascade='all, delete-orphan', order_by='StockBatch.expiry_date'
    )

    @property
    def unit_label(self):
        return UNIT_LABELS.get(self.unit, self.unit)

    @property
    def unit_symbol(self):
        return UNIT_SYMBOLS.get(self.unit, self.unit)

    @property
    def is_low_stock(self):
        return self.stock_quantity <= self.minimum_stock

    @property
    def restock_quantity(self):
        """Quantidade a comprar para voltar ao estoque mínimo."""
        return max(0.0, (self.minimum_stock or 0.0) - self.stock_quantity)

    @property
    def estimated_cost(self):
        """Custo estimado (R$) do que falta para recompor o estoque mínimo."""
        return self.restock_quantity * (self.unit_price or 0.0)

    def expired_batches(self):
        return [b for b in self.batches if b.is_expired]

    def expiring_batches(self, days=7):
        return [b for b in self.batches if b.is_expiring(days)]

    def __repr__(self):
        return f'<Ingredient {self.name}>'

# Model representing a registered batch/lot of an ingredient with expiry date
class StockBatch(db.Model):
    __tablename__ = 'stock_batches'
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredients.id', ondelete='CASCADE'), nullable=False, index=True)
    quantity = db.Column(db.Float, nullable=False)
    expiry_date = db.Column(db.Date, nullable=True, index=True)
    note = db.Column(db.String(80)) # identificação do lote
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    @property
    def is_expired(self):
        return self.expiry_date is not None and self.expiry_date < date.today()

    def is_expiring(self, days=7):
        if self.expiry_date is None:
            return False
        return date.today() <= self.expiry_date <= date.today() + timedelta(days=days)

    def status_label(self):
        if self.is_expired:
            return 'Vencido'
        if self.is_expiring():
            return 'Vencendo'
        return 'OK'

    def __repr__(self):
        return f'<StockBatch ingredient={self.ingredient_id} qty={self.quantity}>'

# Model representing a stock movement (entry or exit) of an ingredient
class StockMovement(db.Model):
    __tablename__ = 'stock_movements'
    __table_args__ = (
        db.Index('idx_stock_movement_created', 'created_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredients.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    # Unidade do ingrediente movimentado (desnormalizado de ingredients.unity_id)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    quantity = db.Column(db.Float, nullable=False)
    movement_type = db.Column(db.String(10), nullable=False) # 'in' (entrada) ou 'out' (saída)
    note = db.Column(db.String(255))
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipes.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys=[user_id])
    recipe = db.relationship('Recipe')

    def __repr__(self):
        return f'<StockMovement {self.movement_type} {self.quantity}>'

# Model representing a culinary recipe
class Recipe(db.Model):
    __tablename__ = 'recipes'
    __table_args__ = (
        # O mesmo nome de receita pode existir em unidades diferentes
        db.UniqueConstraint('unity_id', 'name', name='uq_recipe_unity_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, index=True)
    description = db.Column(db.Text) # Modo de preparo
    servings = db.Column(db.Integer, default=1) # Rendimento (porções)
    prep_time_minutes = db.Column(db.Integer, nullable=True)
    photo = db.Column(db.String(255), nullable=True) # Nome do arquivo em static/uploads/recipes/
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc))

    ingredients = db.relationship(
        'RecipeIngredient', backref='recipe', lazy=True,
        cascade='all, delete-orphan', order_by='RecipeIngredient.id'
    )
    author = db.relationship('User', foreign_keys=[created_by])

    def check_stock(self):
        """Verifica se todos os ingredientes da receita estão disponíveis no estoque.

        Retorna uma tupla (disponivel, faltando):
        - disponivel: True se TODOS os ingredientes possuem quantidade suficiente;
        - faltando: lista de dicts com ingrediente, necessário, disponível e motivo.
        """
        missing = []
        for link in self.ingredients:
            ing = link.ingredient
            if ing is None:
                continue
            if not ing.is_active:
                missing.append({
                    'ingredient': ing, 'required': link.quantity,
                    'available': ing.stock_quantity, 'shortage': link.quantity,
                    'reason': 'inactive'
                })
            elif ing.stock_quantity < link.quantity:
                missing.append({
                    'ingredient': ing, 'required': link.quantity,
                    'available': ing.stock_quantity,
                    'shortage': link.quantity - ing.stock_quantity,
                    'reason': 'insufficient'
                })
        return (len(missing) == 0, missing)

    @property
    def has_all_ingredients(self):
        return self.check_stock()[0]

    @property
    def total_cost(self):
        """Custo total (R$) somando quantidade x preço unitário de cada ingrediente."""
        total = 0.0
        for link in self.ingredients:
            if link.ingredient and link.ingredient.unit_price:
                total += link.quantity * link.ingredient.unit_price
        return total

    @property
    def cost_per_serving(self):
        if not self.servings:
            return self.total_cost
        return self.total_cost / self.servings

    def __repr__(self):
        return f'<Recipe {self.name}>'

# Junction model: quantity of an ingredient required by a recipe
class RecipeIngredient(db.Model):
    __tablename__ = 'recipe_ingredients'
    __table_args__ = (
        db.UniqueConstraint('recipe_id', 'ingredient_id', name='uq_recipe_ingredient'),
    )
    id = db.Column(db.Integer, primary_key=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey('recipes.id', ondelete='CASCADE'), nullable=False)
    ingredient_id = db.Column(db.Integer, db.ForeignKey('ingredients.id', ondelete='CASCADE'), nullable=False)
    quantity = db.Column(db.Float, nullable=False)

    def __repr__(self):
        return f'<RecipeIngredient recipe={self.recipe_id} ingredient={self.ingredient_id}>'

# Model for Room Categories (dynamic)
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