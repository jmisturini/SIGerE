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
    # Clima no totem: as unidades ficam distantes entre si, então cada uma tem
    # a própria localização. NULL cai para TOTEM_LATITUDE/TOTEM_LONGITUDE (Config).
    weather_latitude = db.Column(db.Float)
    weather_longitude = db.Column(db.Float)
    weather_city = db.Column(db.String(120))  # rótulo exibido (ex: "São Paulo, SP")
    is_active = db.Column(db.Boolean, default=True)
    # Módulos opcionais por unidade: cada administrador liga/desliga no painel
    # apenas o que a unidade usa (códigos 'kitchen' e 'finance' em
    # TOGGLEABLE_MODULES). default True mantém as instalações antigas com tudo
    # ligado até que alguém desative.
    kitchen_enabled = db.Column(db.Boolean, nullable=False, default=True,
                                server_default='1')
    finance_enabled = db.Column(db.Boolean, nullable=False, default=True,
                                server_default='1')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Módulos opcionais (Reservas de Sala é o core do sistema: não pode ser
    # desativado e por isso não está na lista — is_module_enabled trata todo
    # código fora dela como sempre ativo).
    MODULE_KITCHEN = 'kitchen'
    MODULE_FINANCE = 'finance'
    TOGGLEABLE_MODULES = (
        {'code': MODULE_KITCHEN, 'label': 'Cozinha', 'attr': 'kitchen_enabled',
         'description': 'Fichas técnicas, preparações e requisição de compras'},
        {'code': MODULE_FINANCE, 'label': 'Financeiro', 'attr': 'finance_enabled',
         'description': 'Hora extra, vale alimentação e vale transporte'},
    )

    classrooms = db.relationship('Classroom', backref='unity', lazy=True)

    def is_module_enabled(self, code):
        """Estado do módulo opcional nesta unidade; códigos fora da lista de
        alternáveis (ex: reservas, o core) são sempre ativos."""
        for module in self.TOGGLEABLE_MODULES:
            if module['code'] == code:
                return bool(getattr(self, module['attr']))
        return True

    def __repr__(self):
        return f'<Unity {self.code}>'

# Model representing the application users (Admins, Teachers, Employees)

# Papel legado (coluna role) correspondente a cada profile_type — regra de
# domínio do User usada pelo cadastro unificado (UserForm). NÃO confundir com
# os papéis do dump antigo usados no legacy_import, que têm nomes próprios
# (teacher, admin, super_admin) vindos do sistema antigo.
ROLE_POR_PERFIL = {'teacher': 'room', 'employee': 'viewer'}


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    # O e-mail é o identificador de login do usuário (não há username).
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
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active_user = db.Column(db.Boolean, default=True)

    # Unidades às quais o usuário está vinculado — professor ou funcionário
    # pode atuar em mais de uma. Sem vínculos = conta global (ex: super admin,
    # que pode operar em qualquer unidade via seletor). A unidade ativa de
    # operação é resolvida por requisição em app.unity_context.
    unities = db.relationship('Unity', secondary='user_unities', lazy='select',
                              order_by='Unity.name')

    # Papéis adicionais (add-on) concedidos além do papel principal — a
    # permissão efetiva é a união (ex.: Professor + Módulo Cozinha para
    # professores de gastronomia). Ver User.permissions.
    extra_roles = db.relationship('Role', secondary='user_roles', lazy='select')

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
        """Retorna o set de códigos de permissão do usuário: união do papel
        principal com os papéis adicionais (add-on)."""
        codes = set()
        if self.role_obj:
            codes.update(p.code for p in self.role_obj.permissions)
        for extra in self.extra_roles:
            codes.update(p.code for p in extra.permissions)
        return codes

    def has_permission(self, perm_code):
        """Verifica se o usuário possui uma permissão específica."""
        if not self.permissions:
            return False
        # Se o usuário tiver a permissão curinga '*', ele tem acesso a tudo
        if '*' in self.permissions:
            return True
        return perm_code in self.permissions

    # ── Vínculos com unidades (N:N) ──────────────────────────────────────
    @property
    def unity_ids(self):
        """IDs das unidades do usuário (sem consulta extra além do relacionamento)."""
        return [u.id for u in self.unities]

    @property
    def primary_unity_id(self):
        """Primeira unidade do usuário (ordem alfabética) — unidade
        representativa para lançamentos legados (ex.: hora extra importada).
        None em contas globais."""
        return self.unities[0].id if self.unities else None

    @classmethod
    def escopo_unidade(cls, unity_id):
        """Filtro SQLAlchemy: usuários vinculados à unidade informada + contas
        globais (sem vínculos) — mesmo critério antes expresso por
        (unity_id == X) | (unity_id IS NULL) na coluna única."""
        return cls.unities.any(Unity.id == unity_id) | ~cls.unities.any()

    # Propriedades legado atualizadas para compatibilidade
    @property
    def is_admin(self):
        return self.has_permission('*')

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
    # Séries de repetição: reservas geradas pela tela "Repetir" (e a origem)
    # compartilham o mesmo repeat_group_id — permite editar/excluir o lote.
    repeat_group_id = db.Column(db.Integer, db.ForeignKey('reservations.id'),
                                nullable=True, index=True)
    # Notificações de proximidade são opt-in por reserva: o interruptor na
    # seção "Notificações" do formulário ativa/desativa; sem ativação a
    # varredura notify-scan ignora a reserva. Destinatários e antecedências
    # ficam na configuração 1:1 (notification_config, definida junto aos
    # modelos de notificação).
    notify_enabled = db.Column(db.Boolean, nullable=False, default=False,
                               server_default='0')

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
    
# Model for Teacher Overtime Pay
class TeacherOvertimePay(db.Model):
    __tablename__ = 'teacher_overtime_pay'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    teaching_level = db.Column(db.String(50), nullable=False) # E.g., 'Técnico', 'Superior'
    # Hora decimal com 2 casas (ex: 4.5 = 4h30) — o formulário recebe hora e
    # minuto separados e grava o valor já convertido.
    weekly_workload = db.Column(db.Numeric(5, 2), nullable=False)
    hourly_value = db.Column(db.Numeric(10, 2), nullable=False) # 10 dígitos no total, 2 decimais
    budget_code = db.Column(db.String(18), nullable=False)
    shift = db.Column(db.String(50), nullable=False) # E.g., 'Matutino', 'Vespertino', 'Noturno'
    # Dias do lançamento ("10, 17, 25"), todos dentro do mês gravado em
    # dates_month; lançamentos antigos têm os dias relativos ao month_base.
    multiple_dates = db.Column(db.String(255))
    # Mês (YYYY-MM) dos dias gravados em multiple_dates — o mês de referência
    # ou o anterior (janela 20→20). Nulo nos lançamentos antigos: os dias
    # pertencem então ao month_base.
    dates_month = db.Column(db.String(7))
    justification = db.Column(db.String(100))
    # Tipo de curso é obrigatório no formulário; nullable no banco apenas para
    # os lançamentos anteriores à existência do campo (exibem "—" nos detalhes).
    course_type_id = db.Column(db.Integer, db.ForeignKey('course_types.id'), nullable=True)
    observation = db.Column(db.Text)
    month_base = db.Column(db.String(7), nullable=False) # YYYY-MM
    accountable_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    teacher = db.relationship('User', foreign_keys=[teacher_id])
    accountable = db.relationship('User', foreign_keys=[accountable_id])


# Tipo de curso do lançamento de Hora Extra (ex.: Técnico, Superior, FIC):
# catálogo gerenciado no Painel Admin (/admin/tipos-curso) — nada fixo no
# código. Nome único: a lista alimenta o dropdown do formulário.
class CourseType(db.Model):
    __tablename__ = 'course_types'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    overtime_pays = db.relationship('TeacherOvertimePay', backref='course_type')

    def __repr__(self):
        return f'<CourseType {self.name}>'


# Fechamento mensal da Hora Extra: registra quando a unidade fechou os
# lançamentos de um mês de referência — daí em diante o mês não aceita mais
# edição nem exclusão (a planilha final foi baixada no fechamento). Substitui
# os antigos bloqueios de 30 dias e de mês anterior.
class OvertimeMonthClosure(db.Model):
    __tablename__ = 'overtime_month_closures'
    __table_args__ = (
        db.UniqueConstraint('unity_id', 'month_base',
                            name='uq_overtime_closure_unity_month'),
    )
    id = db.Column(db.Integer, primary_key=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=False, index=True)
    month_base = db.Column(db.String(7), nullable=False)  # YYYY-MM
    closed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    closed_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    closed_by = db.relationship('User')

    def __repr__(self):
        return f'<OvertimeMonthClosure unity={self.unity_id} {self.month_base}>'


# Lançamento simples do Vale Alimentação de Professores (RH): cada linha é a
# contagem de dias trabalhados informada para um professor — sem valores nem
# vínculo com folha; o responsável pelo lançamento fica registrado.
class TeacherMealAllowance(db.Model):
    __tablename__ = 'teacher_meal_allowances'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    days = db.Column(db.Integer, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    teacher = db.relationship('User', foreign_keys=[teacher_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    def __repr__(self):
        return f'<TeacherMealAllowance {self.teacher_id} +{self.days}d>'

# Registro do módulo Vale Transporte (Financeiro): uma linha por colaborador,
# espelhando todas as colunas da aba "Vale Transporte" do Pedido de Compra
# enviado (A–P) para que possam ser revisadas/editadas antes da exportação.
class VtRecord(db.Model):
    __tablename__ = 'vt_records'
    id = db.Column(db.Integer, primary_key=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    registration = db.Column(db.String(20), nullable=False)          # A: Matricula
    full_name = db.Column(db.String(255), nullable=False)            # B: Nome
    # Nome como veio no Pedido de Compra, quando a padronização automática
    # (iniciais maiúsculas) alterou o texto — None se o nome já estava certo.
    original_name = db.Column(db.String(255))
    optant = db.Column(db.String(3), nullable=False, default='Não')  # C: Optante VT (Sim/Não)
    link = db.Column(db.String(50))                                  # D: Vínculo
    unity = db.Column(db.String(100))                                # E: Unidade (do Pedido de Compra)
    company_count = db.Column(db.Integer, default=0)                 # F: Empresas
    company_a_name = db.Column(db.String(100))                       # G: Empresa A
    company_a_value = db.Column(db.Numeric(10, 2))                   # H: Valor VT A
    company_a_passes = db.Column(db.Integer)                         # I: VT A
    company_a_total = db.Column(db.Numeric(10, 2))                   # J: Valor Total Empresa A
    company_b_name = db.Column(db.String(100))                       # K: Empresa B
    company_b_value = db.Column(db.Numeric(10, 2))                   # L: Valor VT B
    company_b_passes = db.Column(db.Integer)                         # M: VT B
    company_b_total = db.Column(db.Numeric(10, 2))                   # N: Valor Total Empresa B
    total_passes = db.Column(db.Integer, default=0)                  # O: Total de Passes
    total_value = db.Column(db.Numeric(10, 2))                       # P: Valor Total dos Passes
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Grupos de exportação da planilha de pagamento: definidos pelo VÍNCULO
    # do colaborador (Técnico-Administrativo e Professores).
    GROUP_TECNICO = 'tecnico'
    GROUP_PROFESSORES = 'professores'

    @property
    def group(self):
        """Classificação do colaborador para a exportação (ou None se fora
        dos grupos)."""
        if self.link == 'Professor(a)':
            return self.GROUP_PROFESSORES
        if self.link == 'Técnico - Administrativo':
            return self.GROUP_TECNICO
        return None

    # Exportável = os mesmos critérios do script: optante "Sim" e passes > 0.
    @property
    def is_exportable(self):
        return self.optant == 'Sim' and bool(self.total_passes)


# Pedido de Vale-Transporte enviado pelo formulário público (/vt/pedido) —
# adaptação do "Pedido de Vale-Transporte" (Microsoft Forms) que o RH usava
# fora do sistema. Acesso anônimo: a identificação é apenas o e-mail
# informado. Os textos de vínculo/empresa são exatamente as opções do
# formulário, compatíveis com VtRecord.link — a listagem Pedidos VT
# (/vt/pedidos) e a planilha de pagamento usam os mesmos grupos.
class VtRequest(db.Model):
    __tablename__ = 'vt_requests'
    id = db.Column(db.Integer, primary_key=True)
    # Unidade dona do pedido (resolvida pela URL do formulário público:
    # /vt/pedido?unity=N); as listagens são escopadas à unidade ativa.
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)    # identificação (acesso público)
    full_name = db.Column(db.String(255), nullable=False)            # Nome
    registration = db.Column(db.String(20), nullable=False)          # Matrícula
    optant = db.Column(db.String(3), nullable=False, default='Não')  # "Deseja VT para o mês" (Sim/Não)
    unity = db.Column(db.String(100))                                # Unidade do formulário
    link = db.Column(db.String(50))                                  # Vínculo
    company_count = db.Column(db.Integer, default=0)                 # nº de empresas de ônibus (1/2)
    company_a_name = db.Column(db.String(100))                       # Empresa A (nome)
    company_a_value = db.Column(db.Numeric(10, 2))                   # tarifa do vale A
    company_a_passes = db.Column(db.Integer)                         # nº de vales A
    company_a_route = db.Column(db.String(20))                       # trajeto A (Somente Volta / Ida e Volta)
    company_b_name = db.Column(db.String(100))                       # Empresa B
    company_b_value = db.Column(db.Numeric(10, 2))                   # tarifa do vale B
    company_b_passes = db.Column(db.Integer)                         # nº de vales B
    company_b_route = db.Column(db.String(20))                       # trajeto B
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Total de vales do pedido (empresas A + B).
    @property
    def total_passes(self):
        return (self.company_a_passes or 0) + (self.company_b_passes or 0)

    # Valor total do pedido: Σ tarifa × vales das empresas informadas.
    @property
    def total_value(self):
        total = ((self.company_a_value or 0) * (self.company_a_passes or 0)
                 + (self.company_b_value or 0) * (self.company_b_passes or 0))
        return float(total)

    # Grupo de exportação da planilha de pagamento — mesmos grupos do
    # VtRecord: definidos pelo vínculo informado no pedido.
    @property
    def group(self):
        return {'Professor(a)': VtRecord.GROUP_PROFESSORES,
                'Técnico - Administrativo': VtRecord.GROUP_TECNICO}.get(self.link)

    # Exportável = os mesmos critérios do script: optante "Sim" e passes > 0.
    @property
    def is_exportable(self):
        return self.optant == 'Sim' and bool(self.total_passes)


# Empresas de ônibus e tarifas vigentes do pedido público de Vale-Transporte
# (/vt/pedido), gerenciadas na área de administração (/admin/vt-empresas) e
# PERTENCENTES A UMA UNIDADE: cada unidade mantém o próprio cadastro, e o
# formulário público mostra apenas as empresas da unidade do link.
# Substituíram as opções fixas que eram cópia do formulário original do
# Microsoft Forms. Pedidos antigos guardam nome/tarifa como texto — apagar a
# empresa não afeta o histórico.
class VtEmpresa(db.Model):
    __tablename__ = 'vt_empresas'
    id = db.Column(db.Integer, primary_key=True)
    # Sem unique no banco: o mesmo nome pode existir em unidades diferentes —
    # a unicidade é por escopo visível, validada na rota.
    nome = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    # Unidade dona do cadastro (toda empresa pertence a uma unidade).
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    valores = db.relationship('VtEmpresaValor', backref='empresa',
                              cascade='all, delete-orphan',
                              order_by='VtEmpresaValor.valor')

    @classmethod
    def empresas_ativas(cls, unity_id):
        """Empresas disponíveis no formulário público da unidade, em ordem
        alfabética."""
        return (cls.query
                .filter_by(unity_id=unity_id, is_active=True)
                .order_by(cls.nome).all())

    @classmethod
    def mapa_tarifas(cls, unity_id):
        """Mapa {nome_da_empresa: [VtEmpresaValor...]} da unidade — alimenta
        as opções e a validação empresa↔tarifa do formulário; cada linha
        carrega id, identificação e valor."""
        return {e.nome: list(e.valores) for e in cls.empresas_ativas(unity_id)}


# Configurações do pedido público de VT por unidade: números base de vales
# por trajeto (quando definidos, o pedido usa esses valores em vez de pedir
# que o colaborador digite) e data de fechamento do formulário (último dia
# em que ele pode ser preenchido). Gerenciadas em /admin/vt-configuracao.
class VtConfig(db.Model):
    __tablename__ = 'vt_configs'
    id = db.Column(db.Integer, primary_key=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=False,
                         unique=True, index=True)
    vales_somente_ida = db.Column(db.Integer)                        # nº base de vales — Somente Volta
    vales_ida_e_volta = db.Column(db.Integer)                        # nº base de vales — Ida e Volta
    fecha_em = db.Column(db.Date)                                    # último dia para preencher o pedido

    def esta_fechado(self, hoje):
        """True quando a data de fechamento já passou (o dia de fecha_em
        ainda permite preencher). Aceita date ou datetime."""
        if isinstance(hoje, datetime):
            hoje = hoje.date()
        return self.fecha_em is not None and hoje > self.fecha_em


class VtEmpresaValor(db.Model):
    __tablename__ = 'vt_empresas_valores'
    id = db.Column(db.Integer, primary_key=True)
    empresa_id = db.Column(db.Integer, db.ForeignKey('vt_empresas.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    # Texto livre que identifica a tarifa aplicada (ex.: "Patamar 3", da
    # tabela Metropolis) — não é o trajeto (Somente Volta / Ida e Volta),
    # que o colaborador escolhe no pedido.
    identificacao = db.Column(db.String(100))
    valor = db.Column(db.Numeric(10, 2), nullable=False)             # tarifa em reais

    @property
    def valor_texto(self):
        """Tarifa no formato do formulário: '7,24'."""
        return f'{float(self.valor):.2f}'.replace('.', ',')

    @property
    def rotulo(self):
        """Rótulo da opção no formulário público: 'Patamar 3 — R$ 7,38'
        (linhas antigas sem identificação mostram só o valor)."""
        if self.identificacao:
            return f'{self.identificacao} — R$ {self.valor_texto}'
        return f'R$ {self.valor_texto}'

# Tabela de junção entre Roles e Permissions
role_permissions = db.Table('role_permissions',
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True),
    db.Column('permission_id', db.Integer, db.ForeignKey('permissions.id', ondelete='CASCADE'), primary_key=True)
)

# Tabela de junção dos papéis adicionais (add-on) de cada usuário — complementam
# o papel principal (users.role_id) sem substituí-lo.
user_roles = db.Table('user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id', ondelete='CASCADE'), primary_key=True)
)

# Tabela de junção dos vínculos do usuário com unidades (N:N): o mesmo
# professor ou funcionário pode atuar em várias unidades. Usuário sem linha
# aqui é conta global (ex: super admin).
user_unities = db.Table('user_unities',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    db.Column('unity_id', db.Integer, db.ForeignKey('unities.id', ondelete='CASCADE'), primary_key=True)
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

# Token de integração da API pública de leitura de reservas (/api/v1).
# O valor completo é exibido UMA vez na geração; o banco guarda apenas o hash
# SHA-256, então quem obtiver o banco não descobre nenhum token válido. O
# escopo dos dados é o do usuário criador (unidade e permissões).
class ApiToken(db.Model):
    __tablename__ = 'api_tokens'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, index=True, unique=True)
    prefix = db.Column(db.String(16), nullable=False)  # exibição: 'sige_ab12…'
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                              nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime)   # None = sem expiração
    last_used_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_by = db.relationship('User', backref='api_tokens')

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        # SQLite devolve datetimes naive (UTC); comparação em UTC naive.
        expires = self.expires_at
        if expires.tzinfo is not None:
            expires = expires.astimezone(timezone.utc).replace(tzinfo=None)
        return expires <= datetime.now(timezone.utc).replace(tzinfo=None)

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired

class RoomCategory(db.Model):
    __tablename__ = 'room_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False) # Ex: "Laboratório de Informática"
    code = db.Column(db.String(20), unique=True, nullable=False) # Ex: "computer_lab"
    is_active = db.Column(db.Boolean, default=True)

    # Abreviação para gerar o código da sala automaticamente (ex: CP, CR, AU)
    abbr = db.Column(db.String(3), nullable=True)
    # Regra explícita: categorias que controlam computadores exibem/gravam a
    # contagem de máquinas (substitui a comparação fixa ao código antigo).
    controla_computadores = db.Column(db.Boolean, nullable=False, default=False,
                                      server_default='0')

    # Aparência no totem/dashboard: a tela se monta a partir das categorias
    # cadastradas, sem lógica fixa por tipo de espaço.
    color = db.Column(db.String(7))              # hex '#rrggbb'; NULL usa o padrão
    icon = db.Column(db.String(50))              # classe Bootstrap Icons (ex: bi-buildings)
    # Janela de tempo exibida no totem: 'period' = reservas do período atual
    # (manhã/tarde/noite); 'week' = próximos 7 dias (ex: agenda de auditórios).
    totem_window = db.Column(db.String(20), default='period')

    # Janelas de exibição do totem
    TOTEM_WINDOW_PERIOD = 'period'
    TOTEM_WINDOW_WEEK = 'week'

    # Fallbacks visuais para categorias cadastradas antes de cor/ícone existirem
    DEFAULT_COLOR = '#0d6efd'
    DEFAULT_ICON = 'bi-tag'

    @property
    def display_color(self):
        return self.color or self.DEFAULT_COLOR

    @property
    def display_icon(self):
        return self.icon or self.DEFAULT_ICON

    @property
    def totem_window_label(self):
        return 'Próximos 7 dias' if self.totem_window == self.TOTEM_WINDOW_WEEK else 'Período atual'

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
    # Porções desejadas salvas pelo botão "Salvar quantidades" do recálculo:
    # as quantidades exibidas e a requisição de compras passam a usar
    # quantidade × (scaled_portions ÷ base_portions). None = quantidades
    # originais da ficha.
    scaled_portions = db.Column(db.Float)
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
    def scale_factor(self):
        """Fator de escala em vigor sobre as quantidades originais: porções
        salvas ÷ rendimento base (1.0 sem escala salva)."""
        base = self.base_portions
        if self.scaled_portions and base and base > 0:
            return self.scaled_portions / base
        return 1.0

    @property
    def effective_portions(self):
        """Porções em vigor na preparação: a escala salva ou o rendimento base."""
        base = self.base_portions
        if self.scaled_portions and base and base > 0:
            return self.scaled_portions
        return base

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


# ─────────────────────────────────────────────────────────────────────────────
# Notificações de atividades próximas. A varredura (comando `flask notify-scan`,
# agendado por systemd timer na produção) cria uma Notification por destinatário
# conforme a configuração da própria reserva (ReservationNotificationConfig) —
# a constraint de unicidade garante idempotência: rodar a varredura duas vezes,
# ou o timer disparar em cima do outro, não duplica avisos.
# ─────────────────────────────────────────────────────────────────────────────

EVENT_RESERVATION_UPCOMING = 'reservation_upcoming'

# Regra de carga docente: reserva que leva o professor além do limite diário
# (app/services/scheduling.py) nasce Pendente e avisa os grupos personalizados
# da unidade — criada no momento da gravação, não pela varredura notify-scan.
EVENT_TEACHER_DAILY_LIMIT = 'teacher_daily_limit'

# Mudança de status da reserva (aprovada/cancelada): aviso criado no momento
# da ação para o criador da reserva — também fora da varredura notify-scan.
EVENT_RESERVATION_APPROVED = 'reservation_approved'
EVENT_RESERVATION_CANCELLED = 'reservation_cancelled'

# Exclusão permanente: aviso ao criador criado no momento da exclusão, com
# reservation_id nulo — a FK da notificação apaga em cascata junto com a
# reserva, então o aviso de exclusão não pode referenciá-la.
EVENT_RESERVATION_DELETED = 'reservation_deleted'

# Lembrete de reserva pendente aguardando aprovação: gerado pela varredura
# notify-scan para os aprovadores da unidade (24h e 48h após a criação).
EVENT_RESERVATION_PENDING_REMINDER = 'reservation_pending_reminder'

# Grupos personalizados de destinatários por unidade: a equipe que deve ser
# avisada junta (ex.: "Coordenação Gastronomia"). A configuração da unidade
# seleciona quais grupos recebem os avisos.
notification_group_members = db.Table(
    'notification_group_members',
    db.Column('group_id', db.Integer,
              db.ForeignKey('notification_groups.id', ondelete='CASCADE'), primary_key=True),
    db.Column('user_id', db.Integer,
              db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
)

# Grupos selecionados como destinatários de uma reserva específica.
reservation_notification_groups = db.Table(
    'reservation_notification_groups',
    db.Column('config_id', db.Integer,
              db.ForeignKey('reservation_notification_configs.id', ondelete='CASCADE'), primary_key=True),
    db.Column('group_id', db.Integer,
              db.ForeignKey('notification_groups.id', ondelete='CASCADE'), primary_key=True),
)

# Usuários individuais selecionados como destinatários de uma reserva.
reservation_notification_users = db.Table(
    'reservation_notification_users',
    db.Column('config_id', db.Integer,
              db.ForeignKey('reservation_notification_configs.id', ondelete='CASCADE'), primary_key=True),
    db.Column('user_id', db.Integer,
              db.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
)

# Tipos de sala silenciados pelo usuário (preferência no perfil). O user_id
# referencia a própria preferência (1:1 com o usuário) para a junção ser
# inequívoca; apagar o usuário apaga a preferência e, em cascata, esta tabela.
user_notification_muted_categories = db.Table(
    'user_notification_muted_categories',
    db.Column('user_id', db.Integer,
              db.ForeignKey('user_notification_prefs.user_id', ondelete='CASCADE'),
              primary_key=True),
    db.Column('category_id', db.Integer,
              db.ForeignKey('room_categories.id', ondelete='CASCADE'), primary_key=True),
)


# Grupos que recebem o aviso de sobrecarga de professor (regra de carga
# docente) — seleção dedicada na configuração da unidade, independente das
# configurações por reserva.
notification_config_overload_groups = db.Table(
    'notification_config_overload_groups',
    db.Column('config_id', db.Integer,
              db.ForeignKey('unity_notification_configs.id', ondelete='CASCADE'), primary_key=True),
    db.Column('group_id', db.Integer,
              db.ForeignKey('notification_groups.id', ondelete='CASCADE'), primary_key=True),
)


class NotificationGroup(db.Model):
    __tablename__ = 'notification_groups'
    __table_args__ = (
        db.UniqueConstraint('unity_id', 'name', name='uq_notification_group_unity_name'),
    )
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    members = db.relationship('User', secondary='notification_group_members',
                              lazy='select', order_by='User.full_name')

    def __repr__(self):
        return f'<NotificationGroup {self.name}>'


class ReservationNotificationConfig(db.Model):
    """Configuração de notificações da própria reserva, feita no formulário de
    criar/editar (padrão: desativada). Define os avisos de antecedência
    (24h e/ou 1h antes do início da atividade) e os destinatários explícitos:
    usuários individuais e grupos personalizados da unidade. A varredura
    notify-scan ignora reservas sem esta configuração ou com notify_enabled
    desativado."""
    __tablename__ = 'reservation_notification_configs'
    id = db.Column(db.Integer, primary_key=True)
    reservation_id = db.Column(db.Integer,
                               db.ForeignKey('reservations.id', ondelete='CASCADE'),
                               nullable=False, unique=True, index=True)
    notify_24h = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    notify_1h = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    # Marco ancorado a um horário fixo do próprio dia da atividade (07:00),
    # além das antecedências em horas.
    notify_dia = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    notify_7d = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    # O criador da reserva entra como destinatário dos avisos dela (padrão;
    # pode desmarcar no formulário).
    notify_criador = db.Column(db.Boolean, nullable=False, default=True,
                               server_default='1')
    groups = db.relationship('NotificationGroup', secondary='reservation_notification_groups',
                             lazy='select', order_by='NotificationGroup.name')
    users = db.relationship('User', secondary='reservation_notification_users',
                            lazy='select', order_by='User.full_name')
    reservation = db.relationship('Reservation',
                                  backref=db.backref('notification_config', uselist=False,
                                                     cascade='all, delete-orphan'))

    @property
    def marcos_ativos(self):
        """Rótulos dos marcos habilitados, na ordem em que aparecem na UI."""
        return [rotulo for rotulo, ativo in
                (('7 dias antes', self.notify_7d),
                 ('24 horas antes', self.notify_24h), ('1 hora antes', self.notify_1h),
                 ('No dia da atividade (07:00)', self.notify_dia))
                if ativo]

    def __repr__(self):
        return f'<ReservationNotificationConfig reservation={self.reservation_id}>'


class UserNotificationPref(db.Model):
    """Preferências de notificação do usuário (autoatendimento no perfil):
    silenciar todos os avisos de atividade próxima ou apenas os de salas de
    determinados tipos (RoomCategory). Vale só para os avisos de reserva
    próxima — o aviso de sobrecarga de professor não passa por aqui."""
    __tablename__ = 'user_notification_prefs'
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                        primary_key=True)
    mute_all = db.Column(db.Boolean, nullable=False, default=False, server_default='0')
    # Espelho por e-mail: desligado no perfil, o usuário deixa de receber os
    # avisos por e-mail (o sino in-app continua inalterado). Padrão ligado.
    email_enabled = db.Column(db.Boolean, nullable=False, default=True,
                              server_default='1')
    muted_categories = db.relationship('RoomCategory',
                                       secondary='user_notification_muted_categories',
                                       lazy='select', order_by='RoomCategory.name')
    user = db.relationship('User', backref=db.backref('notification_pref', uselist=False))

    def __repr__(self):
        return f'<UserNotificationPref user={self.user_id}>'


class UnityNotificationConfig(db.Model):
    """Sobrou apenas para o aviso de sobrecarga de professor: os grupos da
    unidade que recebem o aviso quando uma reserva leva o docente além do
    limite diário (EVENT_TEACHER_DAILY_LIMIT, criado na gravação da reserva).
    Os avisos de atividade próxima são configurados na própria reserva
    (ReservationNotificationConfig)."""
    __tablename__ = 'unity_notification_configs'
    id = db.Column(db.Integer, primary_key=True)
    unity_id = db.Column(db.Integer, db.ForeignKey('unities.id'), nullable=False,
                         unique=True, index=True)
    # Grupos que recebem o aviso de sobrecarga de professor (regra de carga
    # docente) — seleção própria; vazia, ninguém recebe o aviso.
    overload_groups = db.relationship('NotificationGroup',
                                      secondary='notification_config_overload_groups',
                                      lazy='select', order_by='NotificationGroup.name')

    def __repr__(self):
        return f'<UnityNotificationConfig unity={self.unity_id}>'


class Notification(db.Model):
    """Aviso individual por destinatário, gerado pela varredura de reservas
    próximas. read_at nulo = não lida (contador do sino); sent_at fica
    reservado para canais futuros (ex.: e-mail) consumirem como fila."""
    __tablename__ = 'notifications'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'event_type', 'reservation_id', 'milestone',
                            name='uq_notification_destinatario_evento'),
        db.Index('ix_notifications_user_read', 'user_id', 'read_at'),
    )
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
                        nullable=False, index=True)
    reservation_id = db.Column(db.Integer,
                               db.ForeignKey('reservations.id', ondelete='CASCADE'),
                               nullable=True, index=True)
    event_type = db.Column(db.String(40), nullable=False, default=EVENT_RESERVATION_UPCOMING)
    # Marco que gerou o aviso ('7d', '24h', '1h', 'dia', 'diario', 'status') —
    # junto com user/reserva/evento forma a chave de unicidade.
    milestone = db.Column(db.String(10), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text)
    url = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    read_at = db.Column(db.DateTime)
    sent_at = db.Column(db.DateTime)
    # Espelho por e-mail: tentativas de envio já feitas. Passado o limite
    # (MAIL_MAX_ATTEMPTS), a notificação sai da fila do dreno para não
    # travá-la — falhas de SMTP não são perdidas, só deixam de reprocessar.
    send_attempts = db.Column(db.Integer, nullable=False, default=0,
                              server_default='0')

    user = db.relationship('User', backref='notifications')
    reservation = db.relationship('Reservation', backref='notifications')

    @property
    def is_read(self):
        return self.read_at is not None

    def __repr__(self):
        return f'<Notification user={self.user_id} {self.event_type}/{self.milestone}>'