from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, IntegerField, DateField, TimeField, TextAreaField, SelectField, BooleanField, FloatField, SelectMultipleField)
from wtforms.validators import (DataRequired, Email, EqualTo, Length, ValidationError, Optional, NumberRange)
from datetime import datetime, timedelta, date
import re
# CORREÇÃO: Holiday e Role não estavam importados — os validadores de
# HolidayForm.validate_date e RoleForm.validate_name geravam NameError (erro 500).
from models import User, Classroom, Course, Subject, TeacherBasePay, TeacherAdditivePayment, TeacherOvertimePay, RoomCategory, Holiday, Role

# =============================================================================
# LOGIN & PASSWORD FORMS
# =============================================================================

class LoginForm(FlaskForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(max=64)])
    password = PasswordField('Senha', validators=[DataRequired()])
    submit = SubmitField('Entrar')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Senha Atual', validators=[DataRequired()])
    password = PasswordField('Nova Senha', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirmar Nova Senha', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Atualizar Senha')


# =============================================================================
# TEACHER FORM
# =============================================================================

class TeacherForm(FlaskForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('E-mail', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(max=120)])
    registration = StringField('Matrícula / ID do Professor', validators=[Optional(), Length(max=50)])
    department = StringField('Departamento', validators=[Optional(), Length(max=120)])
    unity = StringField('Unidade', validators=[Optional(), Length(max=120)])
    role_id = SelectField('Papel (Role)', coerce=int, validators=[DataRequired()])
    password = PasswordField('Senha', validators=[Length(min=6)])
    is_active_user = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Professor')

    def __init__(self, *args, **kwargs):
        super(TeacherForm, self).__init__(*args, **kwargs)
        # CORREÇÃO: _obj_id pode vir como kwarg explícito (obj_id=user.id) ou ser extraído
        # do objeto passado via obj=user. Sem isso, _obj_id era sempre None em edições,
        # causando falsa detecção de duplicidade nas validações de username/email/registration.
        obj = kwargs.get('obj', None)
        self._obj_id = kwargs.get('obj_id', None) or (obj.id if obj and hasattr(obj, 'id') else None)
        # Senha obrigatória apenas na criação (sem obj_id)
        if not self._obj_id:
            self.password.validators.insert(0, DataRequired())

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_username(self, field):
        # CORREÇÃO: regex anterior barrava usernames com números ou underscore (ex: joao_silva, prof2).
        # Username agora aceita letras, números, underscore e espaços.
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ0-9_\s]+$', field.data):
            raise ValidationError('Nome de Usuário deve conter apenas letras, números e underscore.')
        existing = User.query.filter_by(username=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este nome de usuário já está em uso.')

    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este e-mail já está cadastrado.')

    def validate_full_name(self, field):
        self._validate_alpha_only(field, 'Nome Completo')

    def validate_department(self, field):
        self._validate_alpha_only(field, 'Departamento')

    def validate_unity(self, field):
        self._validate_alpha_only(field, 'Unidade')

    def validate_registration(self, field):
        if field.data:
            existing = User.query.filter_by(registration=field.data).first()
            if existing and existing.id != getattr(self, '_obj_id', None):
                raise ValidationError('Esta Matrícula já está em uso.')


# =============================================================================
# EMPLOYEE FORM
# =============================================================================

class EmployeeForm(FlaskForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('E-mail', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(max=120)])
    registration = StringField('Matrícula / ID do Funcionário', validators=[Optional(), Length(max=50)])
    sector = StringField('Setor', validators=[Optional(), Length(max=120)])
    function = StringField('Função', validators=[Optional(), Length(max=120)])
    unity = StringField('Unidade', validators=[Optional(), Length(max=120)])
    role_id = SelectField('Papel (Role)', coerce=int, validators=[DataRequired()])
    is_teacher = BooleanField('Também cadastrar como Professor (pode ser designado para reservas)')
    password = PasswordField('Senha', validators=[Length(min=6)])
    is_active_user = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Funcionário')

    def __init__(self, *args, **kwargs):
        super(EmployeeForm, self).__init__(*args, **kwargs)
        # CORREÇÃO: mesma correção do TeacherForm — extrai _obj_id do objeto passado via obj=
        # quando obj_id não é passado explicitamente como kwarg.
        obj = kwargs.get('obj', None)
        self._obj_id = kwargs.get('obj_id', None) or (obj.id if obj and hasattr(obj, 'id') else None)
        # Senha obrigatória apenas na criação (sem obj_id)
        if not self._obj_id:
            self.password.validators.insert(0, DataRequired())

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_username(self, field):
        # CORREÇÃO: regex anterior barrava usernames com números ou underscore (ex: joao_silva, func2).
        # Username agora aceita letras, números, underscore e espaços.
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ0-9_\s]+$', field.data):
            raise ValidationError('Nome de Usuário deve conter apenas letras, números e underscore.')
        existing = User.query.filter_by(username=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este nome de usuário já está em uso.')

    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este e-mail já está cadastrado.')

    def validate_full_name(self, field):
        self._validate_alpha_only(field, 'Nome Completo')

    def validate_sector(self, field):
        self._validate_alpha_only(field, 'Setor')

    def validate_function(self, field):
        self._validate_alpha_only(field, 'Função')

    def validate_unity(self, field):
        self._validate_alpha_only(field, 'Unidade')

    def validate_registration(self, field):
        if field.data:
            existing = User.query.filter_by(registration=field.data).first()
            if existing and existing.id != getattr(self, '_obj_id', None):
                raise ValidationError('Esta Matrícula já está em uso.')


# =============================================================================
# CLASSROOM FORM
# =============================================================================

class ClassroomForm(FlaskForm):
    name = StringField('Nome da Sala', validators=[DataRequired(), Length(max=64)])
    room_number = StringField('Número da Sala', validators=[DataRequired(), Length(max=20)])
    building = StringField('Prédio', validators=[Optional(), Length(max=120)])
    floor = StringField('Andar', validators=[Optional(), Length(max=20)])
    capacity = IntegerField('Capacidade', validators=[DataRequired(), NumberRange(min=1, message='A capacidade deve ser um número inteiro positivo.')])
    category_id = SelectField('Categoria', coerce=int, validators=[DataRequired()])
    computer_count = IntegerField('Número de Computadores', validators=[Optional(), NumberRange(min=0, message='O número de computadores deve ser um número inteiro positivo.')])
    description = TextAreaField('Descrição', validators=[Optional()])
    is_active = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Sala')

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_name(self, field):
        self._validate_alpha_only(field, 'Nome da Sala')

    def validate_building(self, field):
        self._validate_alpha_only(field, 'Prédio')


# =============================================================================
# RESERVATION FORM
# =============================================================================

class ReservationForm(FlaskForm):
    classroom = SelectField('Sala', coerce=int, validators=[DataRequired()])
    course = SelectField('Curso', coerce=int, validators=[Optional()])
    subject = SelectField('Disciplina', coerce=int, validators=[Optional()])
    teacher = SelectField('Professor', coerce=int, validators=[Optional()])
    title = StringField('Título / Assunto', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Descrição / Finalidade', validators=[Optional()])
    date = DateField('Data', validators=[DataRequired()])
    start_time = TimeField('Horário de Início', validators=[DataRequired()])
    end_time = TimeField('Horário de Término', validators=[DataRequired()])
    submit = SubmitField('Solicitar Reserva')

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_title(self, field):
        self._validate_alpha_only(field, 'Título / Assunto')

    def validate_date(self, field):
        if field.data < date.today():
            raise ValidationError('Não é possível reservar uma data no passado.')

    def validate_start_time(self, field):
        if self.date.data == date.today() and field.data:
            now = datetime.now().time()
            if field.data < now:
                raise ValidationError('O horário de início não pode estar no passado.')

    def validate_end_time(self, field):
        if self.start_time.data and field.data:
            if field.data <= self.start_time.data:
                raise ValidationError('O horário de término deve ser posterior ao horário de início.')


# =============================================================================
# COURSE FORM
# =============================================================================

class CourseForm(FlaskForm):
    name = StringField('Nome do Curso', validators=[DataRequired(), Length(max=120)])
    code = StringField('Código do Curso', validators=[DataRequired(), Length(max=20)])
    description = TextAreaField('Descrição', validators=[Optional()])
    is_active = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Curso')

    def __init__(self, *args, **kwargs):
        super(CourseForm, self).__init__(*args, **kwargs)
        self._obj_id = kwargs.get('obj_id', None)

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_name(self, field):
        self._validate_alpha_only(field, 'Nome do Curso')

    def validate_code(self, field):
        existing = Course.query.filter_by(code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este código de curso já existe.')


# =============================================================================
# SUBJECT FORM
# =============================================================================

class SubjectForm(FlaskForm):
    name = StringField('Nome da Disciplina', validators=[DataRequired(), Length(max=120)])
    code = StringField('Código da Disciplina', validators=[DataRequired(), Length(max=20)])
    course_id = SelectField('Pertence ao Curso', coerce=int, validators=[Optional()])
    description = TextAreaField('Descrição', validators=[Optional()])
    is_active = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Disciplina')

    def __init__(self, *args, **kwargs):
        super(SubjectForm, self).__init__(*args, **kwargs)
        self._obj_id = kwargs.get('obj_id', None)

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_name(self, field):
        self._validate_alpha_only(field, 'Nome da Disciplina')

    def validate_code(self, field):
        existing = Subject.query.filter_by(code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este código de disciplina já existe.')


# =============================================================================
# HOLIDAY FORM
# =============================================================================

class HolidayForm(FlaskForm):
    name = StringField('Nome do Feriado', validators=[DataRequired(), Length(max=120)])
    date = DateField('Data', validators=[DataRequired()])
    is_active = BooleanField('Ativo (Bloquear Reservas)', default=True)
    submit = SubmitField('Salvar Feriado')

    def __init__(self, *args, **kwargs):
        super(HolidayForm, self).__init__(*args, **kwargs)
        self._obj_id = kwargs.get('obj_id', None)

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_name(self, field):
        self._validate_alpha_only(field, 'Nome do Feriado')

    def validate_date(self, field):
        if field.data < date.today():
            raise ValidationError('Não é possível cadastrar um feriado no passado.')
        existing = Holiday.query.filter_by(date=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Já existe um feriado cadastrado para esta data.')


# =============================================================================
# TEACHER BASE PAY FORM
# =============================================================================

class FormTeacherBasePay(FlaskForm):
    teacher = SelectField('Professor', coerce=int, validators=[DataRequired()])
    course = SelectField('Curso', coerce=int, validators=[Optional()])
    month_start = StringField('Mês Início (YYYY-MM)', validators=[DataRequired()])
    month_end = StringField('Mês Fim (YYYY-MM)', validators=[DataRequired()])
    budget_code = IntegerField('Código Orçamentário (90000-100000)', validators=[DataRequired(), NumberRange(min=90000, max=100000)])
    complement = StringField('Complemento', validators=[Optional(), Length(max=100)])
    weekly_workload = IntegerField('Carga Horária Semanal (1-40)', validators=[DataRequired(), NumberRange(min=1, max=40)])
    submit = SubmitField('Lançar')

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_complement(self, field):
        self._validate_alpha_only(field, 'Complemento')

    def _validate_month_format(self, field):
        if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', field.data):
            raise ValidationError('Formato inválido. Use YYYY-MM (ex: 2024-01).')

    def validate_month_start(self, field):
        self._validate_month_format(field)

    def validate_month_end(self, field):
        self._validate_month_format(field)
        if self.month_start.data and field.data:
            if field.data < self.month_start.data:
                raise ValidationError('O mês de término deve ser igual ou posterior ao mês de início.')


# =============================================================================
# TEACHER ADDITIVE PAY FORM
# =============================================================================

class FormTeacherAdditivePay(FlaskForm):
    base_release = SelectField('Lançamento Base', coerce=int, validators=[DataRequired()])
    course = SelectField('Curso', coerce=int, validators=[Optional()])
    month_start = StringField('Mês Início (YYYY-MM)', validators=[DataRequired()])
    month_end = StringField('Mês Fim (YYYY-MM)', validators=[DataRequired()])
    additional_hour = IntegerField('Horas Adicionais (1-40)', validators=[DataRequired(), NumberRange(min=1, max=40)])
    complement = StringField('Complemento', validators=[Optional(), Length(max=100)])
    submit = SubmitField('Lançar Aditivo')

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_complement(self, field):
        self._validate_alpha_only(field, 'Complemento')

    def _validate_month_format(self, field):
        if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', field.data):
            raise ValidationError('Formato inválido. Use YYYY-MM (ex: 2024-01).')

    def validate_month_start(self, field):
        self._validate_month_format(field)

    def validate_month_end(self, field):
        self._validate_month_format(field)
        if self.month_start.data and field.data:
            if field.data < self.month_start.data:
                raise ValidationError('O mês de término deve ser igual ou posterior ao mês de início.')


# =============================================================================
# TEACHER OVERTIME PAY FORM
# =============================================================================

class FormTeacherOvertimePay(FlaskForm):
    teacher = SelectField('Professor', coerce=int, validators=[DataRequired()])
    teaching_level = SelectField('Nível de Ensino', choices=[
        ('Técnico', 'Técnico'), 
        ('Superior', 'Superior'),
        ('FIC', 'FIC'),
        ('FIC I', 'FIC I'),
        ('FIC II', 'FIC II'),
        ('FIC III', 'FIC III')
    ], validators=[DataRequired()])
    weekly_workload = IntegerField('Carga Horária Semanal', validators=[DataRequired(), NumberRange(min=1, message="A carga horária deve ser maior que 0.")])
    hourly_value = StringField('Valor H/a (ex: 15,50)', validators=[DataRequired()])
    budget_code = StringField('Código Orçamentário', validators=[DataRequired()])
    shift = SelectField('Turno', choices=[('Matutino', 'Matutino'), ('Vespertino', 'Vespertino'), ('Noturno', 'Noturno')], validators=[DataRequired()])
    multiple_dates = StringField('Múltiplas Datas', validators=[Optional(), Length(max=255)])
    justification = StringField('Justificativa', validators=[Optional(), Length(max=100)])
    month_base = StringField('Mês Base', validators=[DataRequired()], render_kw={'type': 'month'})
    submit = SubmitField('Lançar Hora Extra')

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_justification(self, field):
        self._validate_alpha_only(field, 'Justificativa')

    def validate_hourly_value(self, field):
        # Aceita formatos: 15,50 | 15.50 | 1550 | 15
        if not re.match(r'^(\d{1,3}([,.]\d{1,2})?|\d+)$', field.data.replace(',', '.')):
            raise ValidationError('Formato inválido. Use números com vírgula ou ponto decimal (ex: 15,50).')

    def validate_budget_code(self, field):
        if not field.data.isdigit():
            raise ValidationError('O código orçamentário deve conter apenas números.')
        if len(field.data) < 9:
            raise ValidationError('O código orçamentário deve ter pelo menos 9 dígitos.')

    def validate_month_base(self, field):
        if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', field.data):
            raise ValidationError('Formato inválido. Use YYYY-MM (ex: 2024-01).')


# =============================================================================
# ROLE FORM
# =============================================================================

class RoleForm(FlaskForm):
    name = StringField('Nome do Sistema (ex: coordinator)', validators=[DataRequired(), Length(max=50)])
    label = StringField('Rótulo de Exibição (ex: Coordenador)', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Descrição', validators=[Optional()])
    permissions = SelectMultipleField('Permissões', coerce=int, validators=[Optional()])
    submit = SubmitField('Salvar Papel')

    def __init__(self, *args, **kwargs):
        super(RoleForm, self).__init__(*args, **kwargs)
        self._obj_id = kwargs.get('obj_id', None)

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_label(self, field):
        self._validate_alpha_only(field, 'Rótulo de Exibição')

    def validate_name(self, field):
        # Nome do sistema: apenas minúsculas, underscore e números (snake_case)
        if not re.match(r'^[a-z0-9_]+$', field.data):
            raise ValidationError('O nome do sistema deve conter apenas letras minúsculas, números e underscore (ex: course_manager).')
        existing = Role.query.filter_by(name=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este nome de sistema já está em uso.')


# =============================================================================
# ROOM CATEGORY FORM
# =============================================================================

class RoomCategoryForm(FlaskForm):
    name = StringField('Nome da Categoria (ex: Laboratório de Informática)', validators=[DataRequired(), Length(max=50)])
    code = StringField('Código Interno (ex: computer_lab)', validators=[DataRequired(), Length(max=20)])
    abbr = StringField('Abreviação para Código de Sala (ex: LI - máx 3 letras)', validators=[Optional(), Length(max=3)])
    is_active = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Categoria')

    def __init__(self, *args, **kwargs):
        super(RoomCategoryForm, self).__init__(*args, **kwargs)
        self._obj_id = kwargs.get('obj_id', None)

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_name(self, field):
        self._validate_alpha_only(field, 'Nome da Categoria')

    def validate_abbr(self, field):
        self._validate_alpha_only(field, 'Abreviação')

    def validate_code(self, field):
        existing = RoomCategory.query.filter_by(code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este código interno já está em uso.')
