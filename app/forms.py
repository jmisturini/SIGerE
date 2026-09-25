from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SubmitField, IntegerField, FloatField, DateField, TimeField, TextAreaField, SelectField, BooleanField, SelectMultipleField, RadioField)
from wtforms.validators import (DataRequired, Email, EqualTo, Length, ValidationError, Optional, NumberRange)
from datetime import datetime, date
import re
from sqlalchemy import func
# CORREÇÃO: Holiday e Role não estavam importados — os validadores de
# HolidayForm.validate_date e RoleForm.validate_name geravam NameError (erro 500).
from app.models import (User, Course, Subject, RoomCategory, Holiday, Role, Unity,
                        VtEmpresa, VtConfig)
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


# Textos de formulário (títulos de reserva, nomes, rótulos) carregam números,
# ordinais e pontuação real ("2º Concurso", "Senac T.I.", "Coord. Geral",
# "D'Ávila"): o filtro "apenas alfabético" herdado dos forms antigos recusava
# esses valores legítimos — um único padrão permissivo serve a todos os campos.
_PADRAO_TEXTO = re.compile(r"^[A-Za-zÀ-ÿºª0-9\s\-.,()/&']+$")


def _validar_texto(field, field_name):
    if field.data and not _PADRAO_TEXTO.match(field.data):
        raise ValidationError(
            f'{field_name} contém caracteres não permitidos. '
            f"Use letras, números, espaços ou . , - ( ) / & ' º ª")


# =============================================================================
# LOGIN & PASSWORD FORMS
# =============================================================================

class LoginForm(BaseForm):
    # O e-mail é o identificador de login (não há username no sistema).
    email = StringField('E-mail', validators=[DataRequired(), Length(max=120)])
    password = PasswordField('Senha', validators=[DataRequired()])
    submit = SubmitField('Entrar')


class ChangePasswordForm(BaseForm):
    current_password = PasswordField('Senha Atual', validators=[DataRequired()])
    password = PasswordField('Nova Senha', validators=[DataRequired(), Length(min=8, message='A nova senha deve ter pelo menos 8 caracteres.')])
    confirm_password = PasswordField('Confirmar Nova Senha', validators=[DataRequired(), EqualTo('password', message='As senhas não coincidem.')])
    submit = SubmitField('Atualizar Senha')


class ProfileForm(BaseForm):
    """Autoatendimento do usuário: nome, departamento e troca opcional de senha.
    O e-mail não é editável aqui — ele é o login do usuário e só um
    administrador pode alterá-lo (página de edição de usuários)."""
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(max=120)])
    department = StringField('Departamento', validators=[Optional(), Length(max=120)])
    # Sem Optional(): ele solta StopValidation com campo vazio e pularia o
    # validate_current_password (último da cadeia) — a exigência da senha
    # atual quando há troca é coberta no próprio validador inline.
    current_password = PasswordField('Senha Atual')
    password = PasswordField('Nova Senha', validators=[Optional(), Length(min=8, message='A nova senha deve ter pelo menos 8 caracteres.')])
    confirm_password = PasswordField('Confirmar Nova Senha', validators=[Optional(), EqualTo('password', message='As senhas não coincidem.')])
    submit = SubmitField('Salvar Alterações')

    def validate_full_name(self, field):
        _validar_texto(field, 'Nome Completo')

    def validate_department(self, field):
        _validar_texto(field, 'Departamento')

    def validate_current_password(self, field):
        # A senha atual só é exigida quando o usuário está trocando a senha
        if self.password.data:
            from flask_login import current_user
            if not field.data:
                raise ValidationError('Informe sua senha atual para alterar a senha.')
            if not current_user.check_password(field.data):
                raise ValidationError('Senha atual incorreta.')

    def validate_password(self, field):
        if field.data:
            from flask_login import current_user
            if current_user.check_password(field.data):
                raise ValidationError('A nova senha não pode ser igual à senha atual. Escolha uma senha diferente.')


# =============================================================================
# USER FORM — cadastro unificado de Professor e Funcionário
# =============================================================================

class UserForm(BaseForm):
    """Formulário único para criação/edição de Professor e Funcionário.

    Os dois perfis persistem na mesma tabela (users, coluna profile_type) e
    compartilham todos os campos básicos; o seletor profile_type escolhe o
    grupo de campos específico (Departamento × Setor/Função) e determina o
    papel legado aplicado (ROLE_POR_PERFIL em app.models). As rotas
    /users/create-teacher e /users/create-employee apenas pré-selecionam o
    perfil — o usuário pode trocar o tipo no próprio formulário.
    """

    profile_type = SelectField('Tipo de Perfil',
                               choices=[('teacher', 'Professor'), ('employee', 'Funcionário')],
                               validators=[DataRequired(message='Selecione o tipo de perfil.')])
    email = StringField('E-mail', validators=[DataRequired(), Email(), Length(max=120)])
    full_name = StringField('Nome Completo', validators=[DataRequired(), Length(max=120)])
    # Sem DataRequired/Optional na declaração: o Optional soltaria StopValidation
    # e pularia o validate_registration (último da cadeia), perdendo a mensagem
    # dinâmica de obrigatoriedade — o requisito é coberto no próprio validador.
    registration = StringField('Matrícula / ID', validators=[Length(max=50)])
    department = StringField('Departamento', validators=[Optional(), Length(max=120)])
    sector = StringField('Setor', validators=[Optional(), Length(max=120)])
    function = StringField('Função', validators=[Optional(), Length(max=120)])
    is_teacher = BooleanField('Também cadastrar como Professor (pode ser designado para reservas)')
    unity_id = SelectField('Unidade Educacional', coerce=int, validators=[DataRequired()])
    role_id = SelectField('Papel (Role)', coerce=int, validators=[DataRequired()])
    extra_roles = SelectMultipleField('Módulos Adicionais', coerce=int, validators=[Optional()],
                                      description='Somados ao papel principal (ex.: Módulo Cozinha).')
    password = PasswordField('Senha', validators=[Length(min=8, message='A senha deve ter pelo menos 8 caracteres.')])
    is_active_user = BooleanField('Ativo', default=True)
    submit = SubmitField('Salvar')

    def __init__(self, *args, **kwargs):
        super(UserForm, self).__init__(*args, **kwargs)
        # _obj_id pode vir como kwarg explícito (obj_id=user.id) ou ser extraído
        # do objeto passado via obj=user. Sem isso, _obj_id seria None em edições,
        # causando falsa detecção de duplicidade nas validações de email/registration.
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
            self.registration.flags.required = True

    def _perfil(self):
        return self.profile_type.data or 'employee'

    def validate_email(self, field):
        existing = User.query.filter_by(email=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Este e-mail já está cadastrado.')

    def validate_full_name(self, field):
        _validar_texto(field, 'Nome Completo')

    def validate_department(self, field):
        _validar_texto(field, 'Departamento')

    def validate_sector(self, field):
        _validar_texto(field, 'Setor')

    def validate_function(self, field):
        _validar_texto(field, 'Função')

    def validate_registration(self, field):
        # A matrícula é obrigatória para ambos os perfis; a mensagem cita o
        # perfil escolhido ("do professor" / "do funcionário").
        if not field.data:
            raise ValidationError(f"Informe a matrícula/ID do "
                                  f"{'professor' if self._perfil() == 'teacher' else 'funcionário'}.")
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

    def validate_name(self, field):
        _validar_texto(field, 'Nome da Sala')

    def validate_building(self, field):
        _validar_texto(field, 'Prédio')


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
    submit = SubmitField('Cadastrar Reserva')

    def validate_title(self, field):
        _validar_texto(field, 'Título / Assunto')

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

    def validate_name(self, field):
        _validar_texto(field, 'Nome do Curso')

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

    def validate_name(self, field):
        _validar_texto(field, 'Nome da Disciplina')

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
        # CORREÇÃO: mesma correção do RoomCategoryForm — extrai _obj_id do
        # objeto passado via obj= para não validar unicidade contra si mesmo.
        obj = kwargs.get('obj', None)
        self._obj_id = kwargs.get('obj_id', None) or (obj.id if obj and hasattr(obj, 'id') else None)

    def validate_name(self, field):
        # "7 de Setembro", "Aniversário da unidade 2": nomes com números são
        # legítimos — mesmo padrão permissivo dos demais textos.
        _validar_texto(field, 'Nome do Feriado')

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
    # Módulos opcionais da unidade (Reservas de Sala é o core e não é
    # configurável). Marcados por padrão: unidade nova começa com tudo ligado.
    kitchen_enabled = BooleanField('Cozinha (fichas técnicas, preparações e compras)', default=True)
    finance_enabled = BooleanField('Financeiro (hora extra e vale transporte)', default=True)
    is_active = BooleanField('Ativa', default=True)
    submit = SubmitField('Salvar Unidade')

    def __init__(self, *args, **kwargs):
        super(UnityForm, self).__init__(*args, **kwargs)
        self._obj_id = kwargs.get('obj_id', None)

    def validate_name(self, field):
        _validar_texto(field, 'Nome da Unidade')
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
    # Carga Horária Semanal em dois campos (hora e minuto): a conversão para
    # hora decimal fica em workload_decimal() — é esse valor que é gravado,
    # exportado na planilha e exibido na consulta. A validação do total (> 0)
    # fica na rota, junto das demais checagens de negócio.
    weekly_workload_hours = IntegerField('Carga Horária Semanal (hora)',
                                         validators=[Optional(), NumberRange(min=0, message='As horas não podem ser negativas.')])
    weekly_workload_minutes = IntegerField('Carga Horária Semanal (minuto)',
                                           validators=[Optional(), NumberRange(min=0, max=59, message='Os minutos devem estar entre 0 e 59.')])
    hourly_value = StringField('Valor H/a (ex: 15,50)', validators=[DataRequired()])
    budget_code = StringField('Código Orçamentário', validators=[DataRequired()])
    shift = SelectField('Turno', choices=[('Matutino', 'Matutino'), ('Vespertino', 'Vespertino'), ('Noturno', 'Noturno')], validators=[DataRequired()])
    multiple_dates = StringField('Múltiplas Datas', validators=[Optional(), Length(max=255)])
    justification = StringField('Justificativa', validators=[Optional(), Length(max=100)])
    # Renderizado como campo oculto: a interface usa dois selects (mês e ano)
    # porque o Firefox não tem seletor nativo para <input type="month">.
    month_base = StringField('Mês Base', validators=[DataRequired()], render_kw={'type': 'hidden'})
    submit = SubmitField('Lançar Hora Extra')

    def workload_decimal(self):
        """Hora + minuto informados convertidos para hora decimal com 2 casas
        (arredondamento comercial: 4h20 → 4.33). None quando algum campo não
        é um número válido — a rota decide o que fazer com isso."""
        if self.weekly_workload_hours.data is None or self.weekly_workload_minutes.data is None:
            return None
        total = (Decimal(self.weekly_workload_hours.data)
                 + Decimal(self.weekly_workload_minutes.data) / Decimal(60))
        return total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def validate_justification(self, field):
        _validar_texto(field, 'Justificativa')

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
        # CORREÇÃO: mesma correção do RoomCategoryForm — extrai _obj_id do
        # objeto passado via obj= para não validar unicidade contra si mesmo.
        obj = kwargs.get('obj', None)
        self._obj_id = kwargs.get('obj_id', None) or (obj.id if obj and hasattr(obj, 'id') else None)

    def validate_label(self, field):
        # Rótulos reais têm abreviações ("Coord. Geral", "Módulo TI 2").
        _validar_texto(field, 'Rótulo de Exibição')
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
        # CORREÇÃO: extrai _obj_id do objeto passado via obj= quando obj_id
        # não é passado explicitamente como kwarg. Sem isso, _obj_id é None
        # em edições e a validação de unicidade encontra o próprio registro.
        obj = kwargs.get('obj', None)
        self._obj_id = kwargs.get('obj_id', None) or (obj.id if obj and hasattr(obj, 'id') else None)

    def validate_name(self, field):
        _validar_texto(field, 'Nome da Categoria')
        existing = RoomCategory.query.filter_by(name=field.data).first()
        if existing and existing.id != getattr(self, '_obj_id', None):
            raise ValidationError('Já existe uma categoria com este nome.')

    def validate_abbr(self, field):
        _validar_texto(field, 'Abreviação')

    def validate_color(self, field):
        if field.data and not re.match(r'^#[0-9a-fA-F]{6}$', field.data):
            raise ValidationError('A cor deve estar no formato hexadecimal #rrggbb.')





# =============================================================================
# PEDIDO PÚBLICO DE VALE-TRANSPORTE (/vt/pedido, sem login)
# =============================================================================

# Opções fiéis ao formulário "Pedido de Vale-Transporte" (Microsoft Forms)
# que este sistema substitui, com empresa e tarifa separadas: cada empresa
# tem sua lista de tarifas vigentes — o formulário mostra só os nomes e o
# campo de valor (logo abaixo) oferece as tarifas da empresa escolhida. Os
# textos de vínculo coincidem com VtRecord.link, e a resposta chega pronta
# para conferência do RH.
VT_VINCULOS_PEDIDO = ['Técnico - Administrativo', 'Professor(a)']
VT_TRAJETOS_PEDIDO = ['Somente Volta', 'Ida e Volta']


def parse_tarifa_linhas(identificacoes, valores):
    """Combina as linhas do formulário dinâmico de tarifas (uma
    identificação e um valor por linha) em [(identificacao, Decimal), ...]
    ordenada. A identificação é texto livre que rotula a tarifa aplicada
    (ex.: "Patamar 3", da tabela da empresa). Linhas totalmente vazias são
    ignoradas; ValueError com mensagem amigável para linha incompleta,
    valor inválido ou identificação repetida."""
    linhas, vistos = [], set()
    for identificacao, bruto in zip(identificacoes, valores):
        identificacao = (identificacao or '').strip()
        bruto = (bruto or '').strip().upper().replace('R$', '').strip()
        if not identificacao and not bruto:
            continue  # linha vazia acrescentada e não preenchida
        if not identificacao:
            raise ValueError('Informe a identificação de cada tarifa '
                             '(ex.: Patamar 3).')
        if len(identificacao) > 100:
            raise ValueError(f'A identificação "{identificacao[:30]}…" é muito '
                             'longa (máximo de 100 caracteres).')
        if identificacao.casefold() in vistos:
            raise ValueError(f'A identificação "{identificacao}" tem mais de '
                             'uma tarifa — cada identificação deve aparecer '
                             'uma única vez.')
        vistos.add(identificacao.casefold())
        if not bruto:
            raise ValueError(f'Informe o valor da tarifa "{identificacao}".')
        if ',' in bruto:
            bruto = bruto.replace('.', '').replace(',', '.')
        try:
            valor = Decimal(bruto).quantize(Decimal('0.01'))
        except InvalidOperation:
            raise ValueError(f'Valor de tarifa inválido: "{bruto}". '
                             'Use reais com vírgula decimal (ex.: 7,24).')
        linhas.append((identificacao, valor))
    if not linhas:
        raise ValueError('Adicione pelo menos uma tarifa (identificação + valor).')
    return sorted(linhas, key=lambda l: l[0].casefold())


class FormVtEmpresa(BaseForm):
    """Empresa de ônibus do pedido de VT (formulário público) e suas tarifas
    vigentes — gerenciada na área de administração (/admin/vt-empresas). As
    tarifas são linhas dinâmicas (identificação + valor) tratadas pela rota,
    que valida com parse_tarifa_linhas()."""
    nome = StringField('Nome da empresa', validators=[DataRequired(), Length(max=100)])
    is_active = BooleanField('Disponível no formulário público', default=True)
    submit = SubmitField('Salvar empresa')


class FormVtConfig(BaseForm):
    """Configurações do pedido público de VT da unidade: números base de
    vales por trajeto (quando definidos, o pedido os usa automaticamente em
    vez de pedir que o colaborador digite) e data de fechamento do
    formulário (último dia para preencher)."""
    vales_somente_ida = IntegerField(
        'Nº base de vales — Somente Volta',
        validators=[Optional(), NumberRange(min=1, max=999,
                                            message='Informe um número entre 1 e 999.')])
    vales_ida_e_volta = IntegerField(
        'Nº base de vales — Ida e Volta',
        validators=[Optional(), NumberRange(min=1, max=999,
                                            message='Informe um número entre 1 e 999.')])
    fecha_em = DateField('Fechamento do formulário', validators=[Optional()])
    submit = SubmitField('Salvar configurações')

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        # Os números base valem em par: informar só um deles deixaria o
        # pedido sem valor para o outro trajeto.
        if ((self.vales_somente_ida.data is None)
                != (self.vales_ida_e_volta.data is None)):
            self.vales_somente_ida.errors.append(
                'Informe os dois números base de vales (ou deixe ambos vazios '
                'para o colaborador digitar).')
            return False
        return True


class FormVtPedido(BaseForm):
    """Pedido público de Vale-Transporte: replica as perguntas do formulário
    do Microsoft Forms, com a identificação por e-mail exigido pelo acesso
    anônimo. A ramificação (deseja VT → vínculo → nº de empresas) é guiada
    pelo JavaScript da página e espelhada aqui no servidor — o POST forjado
    sem os campos obrigatórios do ramo escolhido é rejeitado. As empresas e
    tarifas são as cadastradas em /admin/vt-empresas: os choices são
    preenchidos pela rota antes da validação."""

    email = StringField('E-mail', validators=[
        DataRequired(), Email(), Length(max=255)])
    full_name = StringField('Nome', validators=[DataRequired(), Length(max=255)])
    registration = StringField('Matrícula', validators=[DataRequired(), Length(max=20)])
    optant = RadioField('Deseja Vale-Transporte para o mês',
                        choices=[('Sim', 'Sim'), ('Não', 'Não')],
                        validators=[DataRequired()])
    # Campos do ramo "Sim": obrigatórios via validate(), não por validador.
    # Sem pergunta de unidade: o pedido já fica registrado na unidade do link
    # usado pelo colaborador.
    link = RadioField('Vínculo',
                      choices=[(v, v) for v in VT_VINCULOS_PEDIDO],
                      validators=[Optional()])
    company_count = RadioField(
        'Selecione o número de empresas de ônibus você usa para se deslocar',
        choices=[('1', '1'), ('2', '2')], validators=[Optional()])
    # O valor é uma LINHA de tarifa do cadastro (id de VtEmpresaValor): a
    # opção mostra "Trajeto — R$ valor" e já define o trajeto do pedido.
    # Choices preenchidos pela rota antes da validação.
    company_a_name = SelectField('Selecione uma empresa de ônibus',
                                 choices=[('', 'Selecione…')], validators=[Optional()])
    company_a_value = SelectField('Valor do vale (tarifa)',
                                  choices=[('', 'Selecione…')], validators=[Optional()])
    company_a_passes = IntegerField(
        'Digite o número de vales necessários',
        validators=[Optional(), NumberRange(min=1, max=49,
                                            message='Informe um número de vales menor que 50.')])
    company_b_name = SelectField('Selecione uma empresa de ônibus',
                                 choices=[('', 'Selecione…')], validators=[Optional()])
    company_b_value = SelectField('Valor do vale (tarifa)',
                                  choices=[('', 'Selecione…')], validators=[Optional()])
    company_b_passes = IntegerField(
        'Digite o número de vales necessários',
        validators=[Optional(), NumberRange(min=1, max=49,
                                            message='Informe um número de vales menor que 50.')])
    # Trajeto: pergunta separada do formulário original (Somente Volta /
    # Ida e Volta) — independente da tarifa (linha) escolhida.
    company_a_route = RadioField('Selecione o número de trajetos',
                                 choices=[(v, v) for v in VT_TRAJETOS_PEDIDO],
                                 validators=[Optional()])
    company_b_route = RadioField('Selecione o número de trajetos',
                                 choices=[(v, v) for v in VT_TRAJETOS_PEDIDO],
                                 validators=[Optional()])
    submit = SubmitField('Enviar pedido')

    def _identificar_por_email(self):
        """Quando o e-mail informado é de uma conta ATIVA, nome, matrícula e
        vínculo vêm do cadastro e sobrescrevem o POST (no navegador os campos
        ficam travados; aqui é a trava de verdade)."""
        if not self.email.data:
            return None
        usuario = (User.query
                   .filter(func.lower(User.email) == self.email.data.strip().lower(),
                           User.is_active_user == True)
                   .first())
        if usuario is None:
            return None
        self.full_name.data = usuario.full_name
        self.registration.data = usuario.registration or self.registration.data
        self.link.data = ('Professor(a)' if usuario.profile_type == 'teacher'
                          else 'Técnico - Administrativo')
        return usuario

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        self._identificar_por_email()
        if self.optant.data != 'Sim':
            return True

        # Ramo "Sim": as perguntas seguintes do formulário viram obrigatórias
        # (no Microsoft Forms o desvio "Não" simplesmente pula o restante).
        # Sem pergunta de unidade: o pedido pertence à unidade do link.
        obrigatorio = [
            (self.link, 'Selecione o vínculo.'),
            (self.company_count, 'Selecione o número de empresas de ônibus.'),
            (self.company_a_name, 'Selecione a empresa de ônibus.'),
            (self.company_a_value, 'Selecione o valor do vale.'),
            (self.company_a_passes, 'Digite o número de vales necessários.'),
            (self.company_a_route, 'Selecione o trajeto.'),
        ]
        valido = True
        for campo, mensagem in obrigatorio:
            if campo.data in (None, ''):
                campo.errors.append(mensagem)
                valido = False
        if self.company_count.data == '2':
            for campo, mensagem in [
                (self.company_b_name, 'Selecione a segunda empresa de ônibus.'),
                (self.company_b_value, 'Selecione o valor do vale da segunda empresa.'),
                (self.company_b_passes, 'Digite o número de vales da segunda empresa.'),
                (self.company_b_route, 'Selecione o trajeto da segunda empresa.'),
            ]:
                if campo.data in (None, ''):
                    campo.errors.append(mensagem)
                    valido = False

        # Empresa x tarifa: a linha selecionada (id) precisa pertencer à
        # empresa escolhida no cadastro da unidade (o select da página já
        # filtra; aqui cobre POST forjado com combinação inválida). A linha
        # resolvida fornece o valor gravado no pedido (o trajeto é a resposta
        # própria do formulário).
        mapa = VtEmpresa.mapa_tarifas(self._unity_id)
        self._linha_a = self._linha_b = None
        for nome_campo, valor_campo, atributo in (
                (self.company_a_name, self.company_a_value, '_linha_a'),
                (self.company_b_name, self.company_b_value, '_linha_b')):
            if not (nome_campo.data and valor_campo.data):
                continue
            linha = next((v for v in mapa.get(nome_campo.data, [])
                          if str(v.id) == str(valor_campo.data)), None)
            if linha is None:
                valor_campo.errors.append(
                    'A tarifa selecionada não pertence à empresa escolhida.')
                valido = False
            else:
                setattr(self, atributo, linha)
        return valido
