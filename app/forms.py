from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from wtforms import (StringField, PasswordField, SubmitField, IntegerField, FloatField, DateField, TimeField, TextAreaField, SelectField, BooleanField, SelectMultipleField)
from wtforms.validators import (DataRequired, Email, EqualTo, Length, ValidationError, Optional, NumberRange)
from datetime import datetime, date
import re
# CORREÇÃO: Holiday e Role não estavam importados — os validadores de
# HolidayForm.validate_date e RoleForm.validate_name geravam NameError (erro 500).
from app.models import (User, Course, Subject, RoomCategory, Holiday, Role, Unity)
from app.unity_context import current_unity_id

# =============================================================================
# BASE COMUM A TODOS OS FORMULÁRIOS
# =============================================================================

# Traduções pt-BR para as mensagens padrão do WTForms (validadores sem
# message= explícita e falhas de conversão de campo) — sem este mapa o usuário
# recebia textos como "This field is required." ou "Not a valid choice.".
_TRADUCOES = {
    # Validadores
    'This field is required.': 'Este campo é obrigatório.',
    'Invalid email address.': 'Endereço de e-mail inválido.',
    'Field must be equal to %(other_name)s.': 'Deve ser igual ao campo %(other_name)s.',
    'Field must be at least %(min)d character long.': 'O campo deve ter pelo menos %(min)d caractere.',
    'Field must be at least %(min)d characters long.': 'O campo deve ter pelo menos %(min)d caracteres.',
    'Field cannot be longer than %(max)d character.': 'O campo não pode ter mais de %(max)d caractere.',
    'Field cannot be longer than %(max)d characters.': 'O campo não pode ter mais de %(max)d caracteres.',
    'Field must be exactly %(max)d character long.': 'O campo deve ter exatamente %(max)d caractere.',
    'Field must be exactly %(max)d characters long.': 'O campo deve ter exatamente %(max)d caracteres.',
    'Field must be between %(min)d and %(max)d characters long.': 'O campo deve ter entre %(min)d e %(max)d caracteres.',
    'Number must be at least %(min)s.': 'O número deve ser maior ou igual a %(min)s.',
    'Number must be at most %(max)s.': 'O número deve ser menor ou igual a %(max)s.',
    'Number must be between %(min)s and %(max)s.': 'O número deve estar entre %(min)s e %(max)s.',
    'Invalid input.': 'Valor inválido.',
    'Invalid URL.': 'URL inválida.',
    'Invalid UUID.': 'UUID inválido.',
    'Invalid IP address.': 'Endereço IP inválido.',
    'Invalid value, must be one of: %(values)s.': 'Valor inválido; deve ser um de: %(values)s.',
    "Invalid value, can't be any of: %(values)s.": 'Valor inválido; não pode ser nenhum de: %(values)s.',
    # Falhas de conversão dos campos
    'Not a valid integer value.': 'Informe um número inteiro válido.',
    'Not a valid decimal value.': 'Informe um número decimal válido.',
    'Not a valid float value.': 'Informe um número válido.',
    'Not a valid choice.': 'Selecione uma opção válida.',
    'Invalid Choice: could not coerce.': 'Opção inválida: não foi possível interpretar o valor.',
    'Not a valid datetime value.': 'Informe uma data e hora válidas.',
    'Not a valid date value.': 'Informe uma data válida.',
    'Not a valid time value.': 'Informe um horário válido.',
    'Not a valid week value.': 'Informe uma semana válida.',
    # flask_wtf (campo CSRF, exibido quando form.errors é renderizado)
    'The CSRF token is missing.': 'O token de segurança (CSRF) está ausente.',
    'The CSRF session token is missing.': 'O token de segurança da sessão está ausente.',
    'The CSRF token is invalid.': 'O token de segurança (CSRF) é inválido.',
    'The CSRF token has expired.': 'O token de segurança (CSRF) expirou.',
}


class _TraducoesPTBR:
    """Objeto de traduções pt-BR entregue ao WTForms via Meta.get_translations.
    É por aqui que passam TODAS as mensagens dos validadores e dos campos."""

    def gettext(self, string):
        return _TRADUCOES.get(string, string)

    def ngettext(self, singular, plural, n):
        chave = singular if n == 1 else plural
        return _TRADUCOES.get(chave, chave)


class MetaPTBR(FlaskForm.Meta):
    """Meta comum: traduz as mensagens padrão do WTForms para pt-BR e
    renderiza o atributo required nos campos obrigatórios."""

    _traducoes = _TraducoesPTBR()

    def get_translations(self, form):
        return self._traducoes

    def render_field(self, field, render_kw):
        # Campos com DataRequired/InputRequired ganham o atributo required no
        # HTML (os forms usam novalidate, então a validação continua no
        # servidor; o atributo serve de gancho para a marcação visual).
        if field.flags.required:
            render_kw.setdefault('required', True)
        return super().render_field(field, render_kw)


class BaseForm(FlaskForm):
    Meta = MetaPTBR


# =============================================================================
# LOGIN & PASSWORD FORMS
# =============================================================================

class LoginForm(BaseForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(max=64)])
    password = PasswordField('Senha', validators=[DataRequired()])
    submit = SubmitField('Entrar')


class ChangePasswordForm(BaseForm):
    current_password = PasswordField('Senha Atual', validators=[DataRequired()])
    password = PasswordField('Nova Senha', validators=[DataRequired(), Length(min=8, message='A nova senha deve ter pelo menos 8 caracteres.')])
    confirm_password = PasswordField('Confirmar Nova Senha', validators=[DataRequired(), EqualTo('password', message='As senhas não coincidem.')])
    submit = SubmitField('Atualizar Senha')


# =============================================================================
# TEACHER FORM
# =============================================================================

class TeacherForm(BaseForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('E-mail', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(max=120)])
    registration = StringField('Matrícula / ID do Professor', validators=[DataRequired(message='Informe a matrícula/ID do professor.'), Length(max=50)])
    department = StringField('Departamento', validators=[Optional(), Length(max=120)])
    unity_id = SelectField('Unidade Educacional', coerce=int, validators=[DataRequired()])
    role_id = SelectField('Papel (Role)', coerce=int, validators=[DataRequired()])
    password = PasswordField('Senha', validators=[Length(min=8, message='A senha deve ter pelo menos 8 caracteres.')])
    is_active_user = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Professor')

    def __init__(self, *args, **kwargs):
        super(TeacherForm, self).__init__(*args, **kwargs)
        # CORREÇÃO: _obj_id pode vir como kwarg explícito (obj_id=user.id) ou ser extraído
        # do objeto passado via obj=user. Sem isso, _obj_id era sempre None em edições,
        # causando falsa detecção de duplicidade nas validações de username/email/registration.
        obj = kwargs.get('obj', None)
        self._obj_id = kwargs.get('obj_id', None) or (obj.id if obj and hasattr(obj, 'id') else None)
        # Senha obrigatória apenas na criação (sem obj_id). NÃO usar
        # validators.insert(): Field compartilha a lista com a definição de
        # classe e o insert vazaria o DataRequired para as instâncias de
        # edição seguintes. O flag também é ajustado à mão — os campos já
        # foram vinculados em super().__init__.
        if not self._obj_id:
            self.password.validators = [DataRequired()] + list(self.password.validators)
            self.password.flags.required = True

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_username(self, field):
        # CORREÇÃO: regex anterior barrava usernames com números ou underscore (ex: joao_silva, prof2).
        # Username agora aceita letras, números, underscore e espaços.
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ0-9_.\-\s]+$', field.data):
            raise ValidationError('Nome de Usuário deve conter apenas letras, números, ponto, hífen e underscore.')
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

    def validate_registration(self, field):
        if field.data:
            existing = User.query.filter_by(registration=field.data).first()
            if existing and existing.id != getattr(self, '_obj_id', None):
                raise ValidationError('Esta Matrícula já está em uso.')


# =============================================================================
# EMPLOYEE FORM
# =============================================================================

class EmployeeForm(BaseForm):
    username = StringField('Nome de Usuário', validators=[DataRequired(), Length(min=3, max=64)])
    email = StringField('E-mail', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(max=120)])
    registration = StringField('Matrícula / ID do Funcionário', validators=[DataRequired(message='Informe a matrícula/ID do funcionário.'), Length(max=50)])
    sector = StringField('Setor', validators=[Optional(), Length(max=120)])
    function = StringField('Função', validators=[Optional(), Length(max=120)])
    unity_id = SelectField('Unidade Educacional', coerce=int, validators=[DataRequired()])
    role_id = SelectField('Papel (Role)', coerce=int, validators=[DataRequired()])
    is_teacher = BooleanField('Também cadastrar como Professor (pode ser designado para reservas)')
    password = PasswordField('Senha', validators=[Length(min=8, message='A senha deve ter pelo menos 8 caracteres.')])
    is_active_user = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar Funcionário')

    def __init__(self, *args, **kwargs):
        super(EmployeeForm, self).__init__(*args, **kwargs)
        # CORREÇÃO: mesma correção do TeacherForm — extrai _obj_id do objeto passado via obj=
        # quando obj_id não é passado explicitamente como kwarg.
        obj = kwargs.get('obj', None)
        self._obj_id = kwargs.get('obj_id', None) or (obj.id if obj and hasattr(obj, 'id') else None)
        # Senha obrigatória apenas na criação (sem obj_id). NÃO usar
        # validators.insert(): Field compartilha a lista com a definição de
        # classe e o insert vazaria o DataRequired para as instâncias de
        # edição seguintes. O flag também é ajustado à mão — os campos já
        # foram vinculados em super().__init__.
        if not self._obj_id:
            self.password.validators = [DataRequired()] + list(self.password.validators)
            self.password.flags.required = True

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_username(self, field):
        # CORREÇÃO: regex anterior barrava usernames com números ou underscore (ex: joao_silva, func2).
        # Username agora aceita letras, números, underscore e espaços.
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ0-9_.\-\s]+$', field.data):
            raise ValidationError('Nome de Usuário deve conter apenas letras, números, ponto, hífen e underscore.')
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

    def validate_registration(self, field):
        if field.data:
            existing = User.query.filter_by(registration=field.data).first()
            if existing and existing.id != getattr(self, '_obj_id', None):
                raise ValidationError('Esta Matrícula já está em uso.')


# =============================================================================
# CLASSROOM FORM
# =============================================================================

class ClassroomForm(BaseForm):
    # Nome é opcional: sem ele, a sala é identificada pelo código gerado
    # (categoria + número), gravado também como nome no servidor.
    name = StringField('Nome da Sala (opcional)', validators=[Optional(), Length(max=64)])
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

class ReservationForm(BaseForm):
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

class CourseForm(BaseForm):
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
        # Unicidade por unidade: o mesmo código pode existir em unidades diferentes
        existing = Course.query.filter_by(unity_id=current_unity_id(), code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este código de curso já existe nesta unidade.')


# =============================================================================
# SUBJECT FORM
# =============================================================================

class SubjectForm(BaseForm):
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
        # Unicidade por unidade: o mesmo código pode existir em unidades diferentes
        existing = Subject.query.filter_by(unity_id=current_unity_id(), code=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este código de disciplina já existe nesta unidade.')


# =============================================================================
# HOLIDAY FORM
# =============================================================================

class HolidayForm(BaseForm):
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
        # Só bloqueia data passada na criação — na edição (obj_id definido)
        # permitir editar/desativar feriados já ocorridos.
        if field.data < date.today() and not getattr(self, '_obj_id', None):
            raise ValidationError('Não é possível cadastrar um feriado no passado.')
        # Unicidade por unidade: unidades distintas podem cadastrar o mesmo feriado
        existing = Holiday.query.filter_by(unity_id=current_unity_id(), date=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Já existe um feriado cadastrado nesta unidade para esta data.')


# =============================================================================
# UNITY FORM (Multi-unidade)
# =============================================================================

class UnityForm(BaseForm):
    name = StringField('Nome da Unidade (ex: Unidade Centro)', validators=[DataRequired(), Length(max=120)])
    code = StringField('Código Curto (ex: CTR)', validators=[DataRequired(), Length(min=2, max=20)])
    address = StringField('Endereço', validators=[Optional(), Length(max=255)])
    phone = StringField('Telefone', validators=[Optional(), Length(max=30)])
    weather_latitude = FloatField('Latitude', validators=[Optional(), NumberRange(min=-90, max=90, message='Latitude deve estar entre -90 e 90.')])
    weather_longitude = FloatField('Longitude', validators=[Optional(), NumberRange(min=-180, max=180, message='Longitude deve estar entre -180 e 180.')])
    weather_city = StringField('Cidade exibida no clima', validators=[Optional(), Length(max=120)])
    is_active = BooleanField('Ativa', default=True)
    submit = SubmitField('Salvar Unidade')

    def __init__(self, *args, **kwargs):
        super(UnityForm, self).__init__(*args, **kwargs)
        self._obj_id = kwargs.get('obj_id', None)

    def _validate_alpha_only(self, field, field_name):
        if field.data and not re.match(r'^[A-Za-zÀ-ÿ\s]+$', field.data):
            raise ValidationError(f'{field_name} deve conter apenas caracteres alfabéticos.')

    def validate_name(self, field):
        self._validate_alpha_only(field, 'Nome da Unidade')
        existing = Unity.query.filter_by(name=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Já existe uma unidade com este nome.')

    def validate_code(self, field):
        if not re.match(r'^[A-Za-z0-9]+$', field.data or ''):
            raise ValidationError('O código deve conter apenas letras e números (sem espaços ou símbolos).')
        existing = Unity.query.filter_by(code=field.data.upper()).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este código de unidade já está em uso.')

    def validate_phone(self, field):
        if field.data and not re.match(r'^[0-9()\-\s+]+$', field.data):
            raise ValidationError('O telefone deve conter apenas números, parênteses, traços e "+ ".')


# =============================================================================
# TEACHER OVERTIME PAY FORM
# =============================================================================

class FormTeacherOvertimePay(BaseForm):
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
    # Renderizado como campo oculto: a interface usa dois selects (mês e ano)
    # porque o Firefox não tem seletor nativo para <input type="month">.
    month_base = StringField('Mês Base', validators=[DataRequired()], render_kw={'type': 'hidden'})
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
        # A máscara formata o campo com pontos (xx.xx.xxxx.x ou
        # xx.xx.xxxx.xx.xxxx): aceita dígitos e pontos e valida pelo total.
        if not re.match(r'^[\d.]*$', field.data or ''):
            raise ValidationError('O código orçamentário deve conter apenas números.')
        digits = re.sub(r'\D', '', field.data or '')
        if len(digits) not in (9, 14):
            raise ValidationError('O código orçamentário deve ter 9 ou 14 dígitos.')

    def validate_month_base(self, field):
        if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', field.data):
            raise ValidationError('Formato inválido. Use YYYY-MM (ex: 2024-01).')


# =============================================================================
# ROLE FORM
# =============================================================================

class RoleForm(BaseForm):
    # Sem campo de nome de sistema: ele é gerado automaticamente do rótulo
    # (slug) pela rota — o usuário final só informa o rótulo exibido.
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
        existing = Role.query.filter_by(label=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Já existe um papel com este nome.')


# =============================================================================
# ROOM CATEGORY FORM
# =============================================================================

# Ícones Bootstrap Icons oferecidos no cadastro — a lista é curada para o
# admin não precisar decorar nomes de classes (e evitar ícones inexistentes).
ROOM_CATEGORY_ICONS = [
    ('bi-tag', 'Padrão (etiqueta)'),
    ('bi-door-closed', 'Sala de aula'),
    ('bi-buildings', 'Auditório'),
    ('bi-cup-hot', 'Cozinha'),
    ('bi-pc-display', 'Laboratório de informática'),
    ('bi-heart-pulse', 'Laboratório de saúde'),
    ('bi-volleyball', 'Quadra de esportes'),
    ('bi-book', 'Biblioteca'),
    ('bi-bus-front', 'Van / transporte'),
    ('bi-tools', 'Oficina'),
    ('bi-music-note', 'Música'),
    ('bi-people', 'Reunião / evento'),
]


class RoomCategoryForm(BaseForm):
    name = StringField('Nome da Categoria (ex: Laboratório de Informática)', validators=[DataRequired(), Length(max=50)])
    controla_computadores = BooleanField(
        'Esta categoria controla computadores (laboratório de informática)')
    abbr = StringField('Abreviação para Código de Sala (ex: LI - máx 3 letras)', validators=[Optional(), Length(max=3)])
    # Aparência usada pelo totem e pelo dashboard — a tela se monta a partir
    # do cadastro, sem lógica fixa por tipo de espaço.
    color = StringField('Cor de destaque',
                        render_kw={'type': 'color'},
                        validators=[Optional(), Length(max=7)])
    icon = SelectField('Ícone', choices=ROOM_CATEGORY_ICONS, validators=[Optional()])
    totem_window = SelectField(
        'Janela exibida no Totem',
        choices=[
            ('period', 'Período atual (manhã/tarde/noite)'),
            ('week', 'Próximos 7 dias'),
        ],
        default='period',
        validators=[DataRequired()],
    )
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
        existing = RoomCategory.query.filter_by(name=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Já existe uma categoria com este nome.')

    def validate_abbr(self, field):
        self._validate_alpha_only(field, 'Abreviação')

    def validate_color(self, field):
        if field.data and not re.match(r'^#[0-9a-fA-F]{6}$', field.data):
            raise ValidationError('A cor deve estar no formato hexadecimal #rrggbb.')





# =============================================================================
# VALE TRANSPORTE (FINANCEIRO)
# =============================================================================

class FormVtUpload(BaseForm):
    """Upload do "Pedido de Compra" (.xlsx) com a aba "Vale Transporte"."""
    file = FileField('Arquivo do Pedido de Compra', validators=[
        FileRequired(message='Selecione o arquivo do Pedido de Compra.'),
        FileAllowed(['xlsx'], 'Formato inválido. Envie um arquivo .xlsx.')
    ])
    submit = SubmitField('Importar')


class FormVtRecord(BaseForm):
    """Edição de um colaborador do Vale Transporte — espelha todas as colunas
    da aba "Vale Transporte" do Pedido de Compra (A–P)."""
    registration = StringField('Matrícula', validators=[DataRequired(), Length(max=20)])
    full_name = StringField('Nome', validators=[DataRequired(), Length(max=255)])
    optant = SelectField('Optante VT', choices=[('Sim', 'Sim'), ('Não', 'Não')],
                         validators=[DataRequired()])
    link = SelectField('Vínculo', choices=[
        ('', '—'),
        ('Técnico - Administrativo', 'Técnico - Administrativo'),
        ('Professor(a)', 'Professor(a)'),
    ], validators=[Optional()])
    unity = StringField('Unidade (Pedido de Compra)', validators=[Optional(), Length(max=100)])
    company_count = IntegerField('Nº de Empresas', validators=[Optional(), NumberRange(min=0, max=2)])
    company_a_name = StringField('Empresa A', validators=[Optional(), Length(max=100)])
    company_a_value = StringField('Valor VT A', validators=[Optional(), Length(max=20)])
    company_a_passes = IntegerField('Passes A', validators=[Optional(), NumberRange(min=0)])
    company_a_total = StringField('Total Empresa A', validators=[Optional(), Length(max=20)])
    company_b_name = StringField('Empresa B', validators=[Optional(), Length(max=100)])
    company_b_value = StringField('Valor VT B', validators=[Optional(), Length(max=20)])
    company_b_passes = IntegerField('Passes B', validators=[Optional(), NumberRange(min=0)])
    company_b_total = StringField('Total Empresa B', validators=[Optional(), Length(max=20)])
    total_passes = IntegerField('Total de Passes', validators=[Optional(), NumberRange(min=0)])
    total_value = StringField('Valor Total dos Passes', validators=[Optional(), Length(max=20)])
    submit = SubmitField('Salvar')

    def _validate_money_format(self, field):
        if not field.data:
            return
        raw = field.data.strip()
        # Aceita 15,50 | 15.50 | 1.234,56 | 1550 (mesma semântica do parser
        # de moeda usado na gravação).
        if not re.match(r'^\d{1,3}(\.\d{3})*(,\d{1,2})?$|^\d+([.,]\d{1,2})?$', raw):
            raise ValidationError('Formato inválido. Use vírgula decimal (ex: 15,50).')

    def validate_company_a_value(self, field):
        self._validate_money_format(field)

    def validate_company_a_total(self, field):
        self._validate_money_format(field)

    def validate_company_b_value(self, field):
        self._validate_money_format(field)

    def validate_company_b_total(self, field):
        self._validate_money_format(field)

    def validate_total_value(self, field):
        self._validate_money_format(field)
