from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, IntegerField, DateField, TimeField, TextAreaField, SelectField, BooleanField, FloatField)
from wtforms.validators import (DataRequired, Email, EqualTo, Length, ValidationError, Optional, NumberRange)
from datetime import datetime, timedelta
from models import User, Classroom, Course, Subject, TeacherBasePay, TeacherAdditivePayment, TeacherOvertimePay 

# Form for user login
class LoginForm(FlaskForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(max=64)])
    password = PasswordField('Senha', validators=[DataRequired()])
    submit = SubmitField('Entrar')

# Form for changing password on first login
class ChangePasswordForm(FlaskForm):
    password = PasswordField('Nova Senha', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirmar Nova Senha', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Atualizar Senha')

# Form for creating/editing Teachers
class TeacherForm(FlaskForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('E-mail', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(max=120)])
    registration = StringField('Matrícula / ID do Professor', validators=[Optional(), Length(max=50)])
    department = StringField('Departamento', validators=[Optional(), Length(max=120)])
    unity = StringField('Unidade', validators=[Optional(), Length(max=120)])
    role = SelectField('Nível de Acesso', choices=[
        ('viewer', 'Visualizador (Somente Leitura)'),
        ('room', 'Agendador (Room Booker)'), 
        ('admin', 'Administrador')
    ], default='room')
    password = PasswordField('Senha', validators=[DataRequired(), Length(min=6)])
    is_active_user = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Professor')

    # Validate username uniqueness
    def validate_username(self, field):
        existing = User.query.filter_by(username=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este nome de usuário já está em uso.')

    # Validate email uniqueness
    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este e-mail já está cadastrado.')

    # Validate registration ID uniqueness
    def validate_registration(self, field):
        if field.data:
            existing = User.query.filter_by(registration=field.data).first()
            if existing and existing.id != getattr(self, '_obj_id', None):
                raise ValidationError('Esta Matrícula já está em uso.')

# Form for creating/editing Employees
class EmployeeForm(FlaskForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('E-mail', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(max=120)])
    registration = StringField('Matrícula / ID do Funcionário', validators=[Optional(), Length(max=50)])
    sector = StringField('Setor', validators=[Optional(), Length(max=120)])
    function = StringField('Função', validators=[Optional(), Length(max=120)])
    unity = StringField('Unidade', validators=[Optional(), Length(max=120)])
    role = SelectField('Nível de Acesso', choices=[
        ('viewer', 'Visualizador (Somente Leitura)'),
        ('room', 'Agendador (Room Booker)'), 
        ('admin', 'Administrador')
    ], default='viewer')
    is_teacher = BooleanField('Também cadastrar como Professor (pode ser designado para reservas)')
    password = PasswordField('Senha', validators=[DataRequired(), Length(min=6)])
    is_active_user = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Funcionário')

    def validate_username(self, field):
        existing = User.query.filter_by(username=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este nome de usuário já está em uso.')

    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este e-mail já está cadastrado.')

    def validate_registration(self, field):
        if field.data:
            existing = User.query.filter_by(registration=field.data).first()
            if existing and existing.id != getattr(self, '_obj_id', None):
                raise ValidationError('Esta Matrícula já está em uso.')

# Form for creating/editing Classrooms
class ClassroomForm(FlaskForm):
    name = StringField('Nome da Sala', validators=[DataRequired(), Length(max=64)])
    room_number = StringField('Número da Sala', validators=[DataRequired(), Length(max=20)])
    building = StringField('Prédio', validators=[Optional(), Length(max=120)])
    floor = StringField('Andar', validators=[Optional(), Length(max=20)])
    capacity = IntegerField('Capacidade', validators=[DataRequired()])
    category = SelectField('Categoria', choices=[
        ('classroom', 'Sala de Aula'), 
        ('auditorium', 'Auditório'),
        ('kitchen', 'Cozinha'),
        ('computer_lab', 'Laboratório de Informática'),
        ('health_lab', 'Laboratório de Saúde')
    ], default='classroom')
    computer_count = IntegerField('Número de Computadores', validators=[Optional()])
    description = TextAreaField('Descrição', validators=[Optional()])
    is_active = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Sala')

# Form for creating/editing Reservations
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

    # Validate that end time is after start time
    def validate_date(self, field):
        if field.data < date.today():
            raise ValidationError('Não é possível reservar uma data no passado.')

# Form for creating/editing Courses
class CourseForm(FlaskForm):
    name = StringField('Nome do Curso', validators=[DataRequired(), Length(max=120)])
    code = StringField('Código do Curso', validators=[DataRequired(), Length(max=20)])
    description = TextAreaField('Descrição', validators=[Optional()])
    is_active = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Curso')

    def validate_code(self, field):
        existing = Course.query.filter_by(code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este código de curso já existe.')

# Form for creating/editing Subjects
class SubjectForm(FlaskForm):
    name = StringField('Nome da Disciplina', validators=[DataRequired(), Length(max=120)])
    code = StringField('Código da Disciplina', validators=[DataRequired(), Length(max=20)])
    course_id = SelectField('Pertence ao Curso', coerce=int, validators=[Optional()])
    description = TextAreaField('Descrição', validators=[Optional()])
    is_active = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Disciplina')

    def validate_code(self, field):
        existing = Subject.query.filter_by(code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este código de disciplina já existe.')

# Form for creating/editing Holidays
class HolidayForm(FlaskForm):
    name = StringField('Nome do Feriado', validators=[DataRequired(), Length(max=120)])
    date = DateField('Data', validators=[DataRequired()])
    is_active = BooleanField('Ativo (Bloquear Reservas)', default=True)
    submit = SubmitField('Salvar Feriado')


class FormTeacherBasePay(FlaskForm):
    teacher = SelectField('Professor', coerce=int, validators=[DataRequired()])
    course = SelectField('Curso', coerce=int, validators=[Optional()])
    month_start = StringField('Mês Início (YYYY-MM)', validators=[DataRequired()])
    month_end = StringField('Mês Fim (YYYY-MM)', validators=[DataRequired()])
    budget_code = IntegerField('Código Orçamentário (90000-100000)', validators=[DataRequired()])
    complement = StringField('Complemento', validators=[Optional(), Length(max=100)])
    weekly_workload = IntegerField('Carga Horária Semanal (1-40)', validators=[DataRequired()])
    submit = SubmitField('Lançar')

class FormTeacherAdditivePay(FlaskForm):
    base_release = SelectField('Lançamento Base', coerce=int, validators=[DataRequired()])
    course = SelectField('Curso', coerce=int, validators=[Optional()])
    month_start = StringField('Mês Início (YYYY-MM)', validators=[DataRequired()])
    month_end = StringField('Mês Fim (YYYY-MM)', validators=[DataRequired()])
    additional_hour = IntegerField('Horas Adicionais (1-40)', validators=[DataRequired()])
    complement = StringField('Complemento', validators=[Optional(), Length(max=100)])
    submit = SubmitField('Lançar Aditivo')

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
    # Validação: Deve ser número e maior que 0
    weekly_workload = IntegerField('Carga Horária Semanal', validators=[DataRequired(), NumberRange(min=1, message="A carga horária deve ser maior que 0.")])
    hourly_value = StringField('Valor H/a (ex: 15,50)', validators=[DataRequired()])
    budget_code = StringField('Código Orçamentário', validators=[DataRequired()])
    shift = SelectField('Turno', choices=[('Matutino', 'Matutino'), ('Vespertino', 'Vespertino'), ('Noturno', 'Noturno')], validators=[DataRequired()])
    multiple_dates = StringField('Múltiplas Datas', validators=[Optional(), Length(max=255)])
    justification = StringField('Justificativa', validators=[Optional(), Length(max=100)])
    month_base = StringField('Mês Base', validators=[DataRequired()], render_kw={'type': 'month'})
    submit = SubmitField('Lançar Hora Extra')

    # Validação customizada: O código deve ter pelo menos 9 dígitos
    def validate_budget_code(self, field):
        if not field.data.isdigit():
            raise ValidationError('O código orçamentário deve conter apenas números.')
        if len(field.data) < 9:
            raise ValidationError('O código orçamentário deve ter pelo menos 9 dígitos.')