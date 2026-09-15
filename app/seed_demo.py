"""Seed de demonstração abrangente do SIGerE.

Diferente do `flask seed` (dados genéricos gerados aleatoriamente), este
comando cria um CENÁRIO completo e determinístico que exercita cada parte do
sistema: multi-unidade (com módulo desligado e unidade inativa), todos os
papéis, professores e funcionários, categorias e tipos de sala variados,
reservas em todas as situações (hoje, pendente, conflito de professor,
cancelada, passada, futuras e série de repetição), feriados, hora extra,
vale-transporte (com os grupos de exportação e as inconsistências visuais),
módulo de Cozinha (receitas, escala de porções, ingrediente inativo, ficha
pendente) e um token fixo para testar a API de reservas.

As datas são calculadas a partir de HOJE, então o cenário continua útil
mesmo meses depois de executado: há sempre reservas na semana corrente para
o totem, o cronograma, o dashboard e o calendário exibirem.

Uso:  flask --app run seed-demo            (cria o cenário)
      flask --app run seed-demo --reset    (apaga a demonstração anterior e recria)

⚠️  Contas e token de demonstração NUNCA devem existir em produção — lá use
    `seed-admin`. Ver docs/implantacao-producao.md.
"""
import hashlib
import json
import os
import uuid
import zipfile
from datetime import date, time, timedelta
from decimal import Decimal
from xml.sax.saxutils import escape

import click
from flask import current_app
from flask.cli import with_appcontext

from app.commands import sync_permissions_impl, _seed_admin
from app.extensions import db
from app.models import (
    ApiToken, Classroom, Course, Holiday, KitchenPreparation, KitchenRecipe,
    KitchenRecipeIngredient, Reservation, Role, RoomCategory, Subject,
    TeacherOvertimePay, TechnicalSheet, Unity, User, VtRecord, user_roles,
)

# Senha única de todas as contas de demonstração (documentada na saída/README).
DEMO_PASSWORD = 'demo1234'

# Valor fixo do token da API de reservas — conhecido de propósito para que a
# integração (ex.: examples/quadro-sala) possa ser testada sem gerar token no
# painel. O banco guarda só o SHA-256; revogue no Painel Admin se necessário.
DEMO_API_TOKEN = 'sige_demo_token_de_demonstracao_troque_em_producao'

# Códigos que identificam os dados deste seed (base do gate de idempotência
# e do --reset).
DEMO_UNITY_CODES = ('DEM-CTR', 'DEM-NORTE', 'DEM-SUL')
DEMO_CATEGORY_CODES = ('classroom', 'auditorium', 'kitchen', 'computer_lab',
                       'health_lab', 'sports_court', 'meeting_room')
# Logins (e-mails) das contas de demonstração — o login é feito pelo e-mail.
DEMO_EMAILS = (
    # Papéis da sede (Centro)
    'gestor.marina@demo.edu.br', 'analista.rafael@demo.edu.br',
    # Professores
    'prof.ana@demo.edu.br', 'prof.bruno@demo.edu.br', 'prof.carla@demo.edu.br',
    'prof.diego@demo.edu.br', 'prof.elisa@demo.edu.br',
    'prof.felipe@demo.edu.br', 'prof.gustavo@demo.edu.br',
    'prof.helena@demo.edu.br', 'prof.talita@demo.edu.br',
    # Funcionários
    'func.juliana@demo.edu.br', 'func.marcos@demo.edu.br',
    'func.patricia@demo.edu.br', 'func.roberto@demo.edu.br',
)
DEMO_API_TOKEN_NAME = 'Token de Demonstração'


# ── Utilitários de data ──────────────────────────────────────────────────────

def _proximo_dia_semana(d, weekday, incluir_hoje=False):
    """Próxima ocorrência do dia da semana (0=segunda … 6=domingo) a partir
    de d. Com incluir_hoje, o próprio dia vale se já for o dia pedido."""
    delta = (weekday - d.weekday()) % 7
    if delta == 0 and not incluir_hoje:
        delta = 7
    return d + timedelta(days=delta)


def _data_livre(d, feriados, unidade_id):
    """Afasta a data para frente até sair de domingos e de feriados ativos da
    unidade — reservas de demonstração não devem nascer em dia que o próprio
    sistema bloqueia."""
    guard = 0
    while d.weekday() == 6 or (d, unidade_id) in feriados:
        d += timedelta(days=7)
        guard += 1
        if guard > 26:  # improvável; evita loop infinito em base maliciosa
            break
    return d


def _dia_passado_livre(d, feriados, unidade_id):
    """O mesmo que _data_livre, mas caminhando para trás — para as reservas
    de histórico (passada/cancelada) que precisam ficar ANTES de hoje."""
    d -= timedelta(days=1)
    guard = 0
    while d.weekday() == 6 or (d, unidade_id) in feriados:
        d -= timedelta(days=1)
        guard += 1
        if guard > 366:
            break
    return d


# ── Peças do cenário ─────────────────────────────────────────────────────────

def _seed_unidades_demo():
    """3 unidades: principal completa, Norte com o módulo Cozinha desligado e
    Sul inativa (teste do unity:toggle e do isolamento de dados)."""
    unidades = {
        'DEM-CTR': Unity(
            name='Unidade Centro (Demo)', code='DEM-CTR',
            address='Rua Exemplo, 100 — Centro, Florianópolis/SC',
            phone='(48) 3211-0100',
            weather_latitude=-27.5954, weather_longitude=-48.5480,
            weather_city='Florianópolis, SC', is_active=True,
        ),
        'DEM-NORTE': Unity(
            name='Unidade Norte (Demo)', code='DEM-NORTE',
            address='Av. Demonstração, 200 — Norte, Joinville/SC',
            phone='(47) 3211-0200',
            weather_latitude=-26.3045, weather_longitude=-48.8487,
            weather_city='Joinville, SC', is_active=True,
            kitchen_enabled=False,  # demonstra unidade sem o módulo Cozinha
        ),
        'DEM-SUL': Unity(
            name='Unidade Sul (Demo)', code='DEM-SUL',
            address='Rua Teste, 300 — Centro, Criciúma/SC',
            phone='(48) 3211-0300',
            weather_latitude=-28.6721, weather_longitude=-49.3696,
            weather_city='Criciúma, SC', is_active=False,  # unidade desativada
        ),
    }
    for unity in unidades.values():
        db.session.add(unity)
    db.session.flush()
    return unidades


def _seed_usuarios_demo(unidades):
    """Usuários de todos os papéis, incluindo os cantos: funcionário que
    também leciona (is_teacher), professor com papel adicional Módulo Cozinha,
    usuário inativo e usuário que força troca de senha no primeiro login."""
    roles = {r.name: r for r in Role.query.all()}
    kitchen_role = Role.query.filter_by(name='kitchen').first()
    ctr, norte, sul = (unidades[c] for c in DEMO_UNITY_CODES)

    perfis = [
        # (identificador, nome, papel principal, perfil, unidade, extras)
        # O identificador compõe o e-mail de login: <ident>@demo.edu.br.
        ('gestor.marina', 'Marina Albuquerque', 'room_manager', 'employee',
         ctr, {'department': 'Coordenação', 'function': 'Gestora de Salas'}),
        ('analista.rafael', 'Rafael Mendes', 'coordinator', 'employee',
         ctr, {'department': 'Planejamento', 'function': 'Analista de Ensino'}),
        ('prof.ana', 'Ana Paula Souza', 'teacher', 'teacher', ctr,
         {'department': 'Gastronomia', 'registration': 'MAT-2024-0001',
          'extra_roles': [kitchen_role]}),  # Gastronomia + papel Módulo Cozinha
        ('prof.bruno', 'Bruno Costa', 'teacher', 'teacher', ctr,
         {'department': 'Informática', 'registration': 'MAT-2024-0002'}),
        ('prof.carla', 'Carla Dias', 'teacher', 'teacher', ctr,
         {'department': 'Enfermagem', 'registration': 'MAT-2024-0003'}),
        ('prof.diego', 'Diego Nunes', 'teacher', 'teacher', ctr,
         {'department': 'Administração', 'registration': 'MAT-2024-0004'}),
        ('prof.elisa', 'Elisa Ferreira', 'teacher', 'teacher', ctr,
         {'department': 'Estética', 'registration': 'MAT-2024-0005',
          'is_active_user': False}),  # conta desativada (sem exclusão)
        ('prof.felipe', 'Felipe Ramos', 'teacher', 'teacher', ctr,
         {'department': 'Informática', 'registration': 'MAT-2024-0006',
          'force_password_change': True}),  # troca obrigatória no 1º login
        ('prof.gustavo', 'Gustavo Oliveira', 'teacher', 'teacher', norte,
         {'department': 'Informática', 'registration': 'MAT-2024-0007'}),
        ('prof.helena', 'Helena Prado', 'teacher', 'teacher', norte,
         {'department': 'Administração', 'registration': 'MAT-2024-0008'}),
        ('prof.talita', 'Talita Gomes', 'teacher', 'teacher', sul,
         {'department': 'Estética', 'registration': 'MAT-2024-0009'}),
        ('func.juliana', 'Juliana Castro', 'employee', 'employee', ctr,
         {'sector': 'Secretaria', 'function': 'Assistente Administrativo'}),
        ('func.marcos', 'Marcos Lima', 'employee', 'employee', ctr,
         {'sector': 'Infraestrutura', 'function': 'Técnico de Laboratório',
          'is_teacher': True}),  # funcionário que também atua como professor
        ('func.patricia', 'Patrícia Rocha', 'employee', 'employee', ctr,
         {'sector': 'Logística', 'function': 'Auxiliar de Logística'}),
        ('func.roberto', 'Roberto Silva', 'employee', 'employee', norte,
         {'sector': 'Apoio', 'function': 'Auxiliar de Portaria'}),
    ]

    usuarios = {}
    for ident, nome, role_name, profile_type, unity, extras in perfis:
        user = User(
            email=f'{ident}@demo.edu.br',
            full_name=nome,
            role='room',  # coluna legada (usada apenas para ordenação)
            profile_type=profile_type,
            unity_id=unity.id,
            role_id=roles[role_name].id,
            force_password_change=extras.get('force_password_change', False),
            is_active_user=extras.get('is_active_user', True),
            is_teacher=extras.get('is_teacher', False),
            department=extras.get('department'),
            sector=extras.get('sector'),
            function=extras.get('function'),
            registration=extras.get('registration'),
        )
        user.set_password(DEMO_PASSWORD)
        if extras.get('extra_roles'):
            user.extra_roles.extend(extras['extra_roles'])
        db.session.add(user)
        usuarios[ident] = user
    db.session.flush()
    return usuarios


def _seed_categorias_demo():
    """Categorias com cor, ícone e janela do totem — a tela do totem se monta
    a partir destes cadastros. Auditório usa janela semanal (agenda de
    eventos); laboratórios de informática controlam computadores."""
    defs = [
        dict(name='Sala de Aula', code='classroom', abbr='SA',
             color='#0d6efd', icon='bi-door-closed'),
        dict(name='Auditório', code='auditorium', abbr='AU',
             color='#004b8d', icon='bi-buildings',
             totem_window=RoomCategory.TOTEM_WINDOW_WEEK),
        dict(name='Cozinha Pedagógica', code='kitchen', abbr='CO',
             color='#f0ad4e', icon='bi-cup-hot'),
        dict(name='Laboratório de Informática', code='computer_lab', abbr='LI',
             color='#0dcaf0', icon='bi-pc-display',
             controla_computadores=True),
        dict(name='Laboratório de Saúde', code='health_lab', abbr='LS',
             color='#dc3545', icon='bi-heart-pulse'),
        dict(name='Quadra de Esportes', code='sports_court', abbr='QE',
             color='#198754', icon='bi-volleyball'),
        dict(name='Sala de Reunião', code='meeting_room', abbr='SR',
             color='#6f42c1', icon='bi-people'),
    ]
    categorias = {}
    for d in defs:
        # Reaproveita a categoria se o `flask seed` interativo já a criou
        # (mesmos codes), atualizando a aparência.
        cat = RoomCategory.query.filter_by(code=d['code']).first()
        if cat is None:
            cat = RoomCategory(**d)
            db.session.add(cat)
        else:
            for attr, valor in d.items():
                setattr(cat, attr, valor)
        categorias[d['code']] = cat
    db.session.flush()
    return categorias


def _seed_salas_demo(unidades, categorias):
    """Salas de todos os tipos nas unidades — incluindo uma sala inativa
    (SR001, demonstra room:toggle sem exclusão)."""
    ctr, norte, sul = (unidades[c] for c in DEMO_UNITY_CODES)

    salas = [
        # (unidade, categoria, nome, número, bloco, andar, capacidade, pcs, ativa)
        (ctr, 'classroom', 'Sala de Aula 101', '101', 'Bloco A', '1º Andar', 30, 0, True),
        (ctr, 'classroom', 'Sala de Aula 102', '102', 'Bloco A', '1º Andar', 30, 0, True),
        (ctr, 'classroom', 'Sala de Aula 201', '201', 'Bloco A', '2º Andar', 35, 0, True),
        (ctr, 'auditorium', 'Auditório Principal', '101', 'Bloco B', 'Térreo', 180, 0, True),
        (ctr, 'kitchen', 'Cozinha Pedagógica', '102', 'Bloco B', '1º Andar', 16, 0, True),
        (ctr, 'kitchen', 'Cozinha Demonstrativa', '103', 'Bloco B', '1º Andar', 10, 0, True),
        (ctr, 'computer_lab', 'Lab de Informática 1', '105', 'Bloco A', '1º Andar', 25, 25, True),
        (ctr, 'computer_lab', 'Lab de Informática 2', '201', 'Bloco A', '2º Andar', 30, 30, True),
        (ctr, 'health_lab', 'Lab de Enfermagem', '301', 'Bloco C', '3º Andar', 20, 0, True),
        (ctr, 'health_lab', 'Lab de Estética', '302', 'Bloco C', '3º Andar', 15, 0, True),
        (ctr, 'sports_court', 'Quadra Poliesportiva', '001', 'Bloco D', 'Térreo', 200, 0, True),
        (ctr, 'meeting_room', 'Sala de Reunião Integrada', '106', 'Bloco A', '1º Andar', 12, 0, True),
        (ctr, 'meeting_room', 'Sala de Reunião — Direção', '001', 'Bloco A', '1º Andar', 8, 0, False),
        (norte, 'classroom', 'Sala de Aula 101', '101', 'Bloco Único', '1º Andar', 30, 0, True),
        (norte, 'computer_lab', 'Lab de Informática 1', '102', 'Bloco Único', '1º Andar', 24, 24, True),
        (norte, 'auditorium', 'Auditório Norte', '201', 'Bloco Único', '2º Andar', 120, 0, True),
        (sul, 'classroom', 'Sala de Aula 101', '101', 'Bloco Único', '1º Andar', 28, 0, True),
    ]
    salas_obj = []
    for unity, cat_code, nome, numero, bloco, andar, cap, pcs, ativa in salas:
        cat = categorias[cat_code]
        sala = Classroom(
            code=f'{cat.abbr}{numero}', name=nome, room_number=numero,
            building=bloco, floor=andar, capacity=cap,
            category_id=cat.id, computer_count=pcs, is_active=ativa,
            unity_id=unity.id,
        )
        db.session.add(sala)
        salas_obj.append(sala)
    db.session.flush()
    return salas_obj


def _seed_cursos_demo(unidades):
    """Cursos e disciplinas com nomes realistas por unidade — um curso é
    criado inativo para demonstrar o toggle acadêmico."""
    ctr, norte, sul = (unidades[c] for c in DEMO_UNITY_CODES)
    cursos, disciplinas_obj = {}, {}

    definicoes = [
        (ctr, 'GAS', 'Técnico em Gastronomia', [
            ('GAS-001', 'Técnicas de Cozinha Brasileira'),
            ('GAS-002', 'Panificação e Confeitaria'),
            ('GAS-003', 'Bebidas e Bar'),
        ]),
        (ctr, 'INF', 'Técnico em Informática', [
            ('INF-001', 'Programação Web'),
            ('INF-002', 'Banco de Dados'),
        ]),
        (ctr, 'ENF', 'Técnico em Enfermagem', [
            ('ENF-001', 'Anatomia e Fisiologia'),
            ('ENF-002', 'Primeiros Socorros'),
        ]),
        (ctr, 'ADM', 'Aprendizagem em Administração', [
            ('ADM-001', 'Rotinas Administrativas'),
            ('ADM-002', 'Gestão de Estoques'),
        ]),
        (ctr, 'EST', 'Técnico em Estética', [  # nasce INATIVO (toggle)
            ('EST-001', 'Técnicas de Massoterapia'),
        ]),
        (norte, 'INF', 'Técnico em Informática', [
            ('INF-101', 'Redes de Computadores'),
            ('INF-102', 'Programação Web'),
        ]),
        (norte, 'ADM', 'Administração', [
            ('ADM-101', 'Contabilidade Básica'),
        ]),
        (sul, 'EST', 'Técnico em Estética', [
            ('EST-101', 'Visagismo'),
        ]),
    ]
    for unity, code, nome, disciplinas in definicoes:
        curso = Course(name=nome, code=code, unity_id=unity.id)
        if unity.id == ctr.id and code == 'EST':
            curso.is_active = False
        db.session.add(curso)
        cursos[(unity.id, code)] = curso
    db.session.flush()

    for unity, code_curso, _, disciplinas in definicoes:
        for code_disc, nome_disc in disciplinas:
            disc = Subject(name=nome_disc, code=code_disc,
                           course_id=cursos[(unity.id, code_curso)].id,
                           unity_id=unity.id, is_active=True)
            db.session.add(disc)
            disciplinas_obj[(unity.id, code_disc)] = disc
    db.session.flush()
    return cursos, disciplinas_obj


def _seed_feriados_demo(unidades):
    """Feriados nacionais do ano corrente em cada unidade, feriado municipal
    só no Centro e um ponto facultativo INATIVO (registro desligado, que não
    bloqueia). Retorna o conjunto {(data, unity_id)} ativos para o gerador de
    reservas desviar deles."""
    ano = date.today().year
    nacionais = [
        ('Confraternização Universal', date(ano, 1, 1)),
        ('Tiradentes', date(ano, 4, 21)),
        ('Independência do Brasil', date(ano, 9, 7)),
        ('Nossa Senhora Aparecida', date(ano, 10, 12)),
        ('Finados', date(ano, 11, 2)),
        ('Proclamação da República', date(ano, 11, 15)),
        ('Natal', date(ano, 12, 25)),
    ]
    ativos = set()
    for unity in unidades.values():
        for nome, d in nacionais:
            db.session.add(Holiday(name=nome, date=d, unity_id=unity.id))
            ativos.add((d, unity.id))
        if unity.code == 'DEM-CTR':
            db.session.add(Holiday(name='Aniversário de Florianópolis',
                                   date=date(ano, 3, 23), unity_id=unity.id))
            ativos.add((date(ano, 3, 23), unity.id))
        # Inativo: aparece no cadastro, mas NÃO bloqueia reservas
        db.session.add(Holiday(name='Ponto Facultativo (exemplo inativo)',
                               date=date(ano, 12, 31), unity_id=unity.id,
                               is_active=False))
    db.session.flush()
    return ativos


def _seed_reservas_demo(unidades, salas, disciplinas, usuarios, feriados):
    """Reservas em todas as situações do fluxo. Consulte os comentários por
    bloco: cada grupo existe para uma tela/regra específica do sistema."""
    ctr, norte, _ = (unidades[c] for c in DEMO_UNITY_CODES)

    def sala(unity, code):
        return next(s for s in salas if s.unity_id == unity.id and s.code == code)

    def disc_ids(unity_id, code):
        disc = disciplinas.get((unity_id, code))
        if disc is None:
            return None, None
        return disc.course_id, disc.id

    def professor_de(quem):
        """Teacher da reserva: usuários do perfil Professor e funcionários
        marcados como "também atuam como professor"."""
        user = usuarios[quem]
        return user.id if (user.profile_type == 'teacher' or user.is_teacher) \
            else None

    hoje = date.today()
    dia_util = hoje + timedelta(days=1) if hoje.weekday() == 6 else hoje
    eh_sabado = dia_util.weekday() == 5
    admin = User.query.filter_by(email='admin@school.edu').first()

    def reservar(**kwargs):
        r = Reservation(**kwargs)
        db.session.add(r)
        return r

    # 1) HOJE aprovado — alimenta totem, cronograma público, dashboard e a
    #    detecção "aulas em andamento" do período atual. Aos sábados não há
    #    reservas noturnas (regra: até 18h).
    slots_hoje = [
        (sala(ctr, 'CO102'), time(8, 0), time(12, 0), 'prof.ana',
         'GAS-001', 'Aula Prática: Cozinha Brasileira'),
        (sala(ctr, 'LS301'), time(8, 0), time(11, 0), 'prof.carla',
         'ENF-001', 'Laboratório de Curativos'),
        (sala(ctr, 'LI105'), time(13, 0), time(17, 0), 'prof.bruno',
         'INF-001', 'Oficina de Programação Web'),
        (sala(ctr, 'SR106'), time(14, 0), time(15, 30), 'gestor.marina',
         None, 'Reunião de Coordenação'),
    ]
    if eh_sabado:
        slots_hoje += [
            (sala(ctr, 'QE001'), time(14, 0), time(16, 0), 'func.marcos',
             None, 'Treino de Vôlei — Seleção'),
        ]
    else:
        slots_hoje += [
            (sala(ctr, 'QE001'), time(18, 0), time(20, 0), 'func.marcos',
             None, 'Treino de Vôlei — Seleção'),
            (sala(ctr, 'LI105'), time(19, 0), time(21, 0), 'prof.bruno',
             'INF-002', 'Aula Noturna: Banco de Dados'),
            (sala(ctr, 'SA101'), time(19, 0), time(21, 0), 'prof.diego',
             'ADM-001', 'Aula Noturna: Rotinas Administrativas'),
        ]
    # Unidade Norte no mesmo dia: outra base de dados — demonstra isolamento
    slots_hoje.append(
        (sala(norte, 'LI102'), time(13, 0), time(17, 0), 'prof.gustavo',
         'INF-101', 'Aula de Redes de Computadores'))
    for room, inicio, fim, quem, disc_code, titulo in slots_hoje:
        course_id, subject_id = disc_ids(room.unity_id, disc_code) \
            if disc_code else (None, None)
        reservar(user_id=usuarios[quem].id, classroom_id=room.id,
                 unity_id=room.unity_id, teacher_id=professor_de(quem),
                 course_id=course_id, subject_id=subject_id,
                 title=titulo, description='Aula agendada para alunos.',
                 date=dia_util, start_time=inicio, end_time=fim,
                 status='approved')

    # 2) PENDENTES — ciclo de aprovação. A primeira cria de propósito um
    #    CONFLITO DE PROFESSOR (Bruno já tem reserva aprovada no mesmo
    #    horário), que é exatamente o cenário em que o sistema pendenta
    #    automaticamente.
    if eh_sabado:
        conflito_inicio, conflito_fim = time(15, 0), time(16, 30)
    else:
        conflito_inicio, conflito_fim = time(19, 30), time(21, 0)
    reservar(
        user_id=usuarios['prof.bruno'].id, classroom_id=sala(ctr, 'SA101').id,
        unity_id=ctr.id, teacher_id=usuarios['prof.bruno'].id,
        course_id=disciplinas[(ctr.id, 'INF-001')].course_id,
        subject_id=disciplinas[(ctr.id, 'INF-001')].id,
        title='Reforço de Programação (conflito de professor)',
        description='Criada sobreposta a outra reserva do mesmo professor — '
                    'exemplo de reserva pendente por conflito de docente.',
        date=dia_util, start_time=conflito_inicio, end_time=conflito_fim,
        status='pending')
    sexta_livre = _data_livre(_proximo_dia_semana(dia_util, 4), feriados,
                              ctr.id)
    reservar(user_id=usuarios['func.patricia'].id,
             classroom_id=sala(ctr, 'QE001').id, unity_id=ctr.id,
             title='Manutenção Preventiva — Quadra',
             description='Equipe de manutenção solicitou a quadra integral; '
                         'aguarda aprovação do gestor.',
             date=sexta_livre, start_time=time(8, 0), end_time=time(12, 0),
             status='pending')

    # 3) CANCELADA e PASSADA — histórico: cancelada mantém registro no
    #    sistema; passada abre o detalhe em modo somente leitura.
    ontem = _dia_passado_livre(dia_util, feriados, ctr.id)
    reservar(user_id=usuarios['prof.diego'].id,
             classroom_id=sala(ctr, 'SA102').id, unity_id=ctr.id,
             teacher_id=usuarios['prof.diego'].id,
             course_id=disciplinas[(ctr.id, 'ADM-001')].course_id,
             subject_id=disciplinas[(ctr.id, 'ADM-001')].id,
             title='Aula de Campo: Mercado Municipal',
             description='Cancelada pelo professor — chuva prevista.',
             date=ontem, start_time=time(8, 0), end_time=time(11, 0),
             status='cancelled')
    semana_passada = _dia_passado_livre(ontem - timedelta(days=7), feriados,
                                        ctr.id)
    reservar(user_id=usuarios['prof.ana'].id,
             classroom_id=sala(ctr, 'CO102').id, unity_id=ctr.id,
             teacher_id=usuarios['prof.ana'].id,
             course_id=disciplinas[(ctr.id, 'GAS-002')].course_id,
             subject_id=disciplinas[(ctr.id, 'GAS-002')].id,
             title='Aula de Panificação: Pães Artesanais',
             description='Aula realizada — registro permanente.',
             date=semana_passada, start_time=time(13, 0), end_time=time(17, 0),
             status='approved')

    # 4) FUTURAS avulsas — calendário, busca de aula, portal e API. Datas
    #    espalhadas na próxima semana e sempre desviadas de feriados.
    proxima_semana = [
        (sala(ctr, 'CO102'), 0, time(8, 0), time(12, 0), 'prof.ana',
         'GAS-002', 'Confeitaria: Bolos e Tortas'),
        (sala(ctr, 'LS301'), 2, time(14, 0), time(17, 0), 'prof.carla',
         'ENF-002', 'Simulação de Atendimento'),
        (sala(ctr, 'SA201'), 3, time(8, 0), time(11, 0), 'prof.diego',
         'ADM-002', 'Gestão de Estoques'),
        (sala(ctr, 'LI105'), 4, time(13, 0), time(17, 0), 'func.marcos',
         None, 'Oficina: Manutenção de Computadores'),
    ]
    for room, weekday, inicio, fim, quem, disc_code, titulo in proxima_semana:
        d = _data_livre(_proximo_dia_semana(dia_util, weekday), feriados,
                        room.unity_id)
        course_id, subject_id = disc_ids(room.unity_id, disc_code) \
            if disc_code else (None, None)
        reservar(user_id=usuarios[quem].id, classroom_id=room.id,
                 unity_id=room.unity_id, teacher_id=professor_de(quem),
                 course_id=course_id, subject_id=subject_id,
                 title=titulo, description='Aula agendada para alunos.',
                 date=d, start_time=inicio, end_time=fim, status='approved')

    # 5) AUDITÓRIO — a categoria usa janela semanal no totem ("Próximos 7
    #    dias"), então precisa de eventos futuros dentro da semana.
    for weekday, titulo, quem, inicio, fim in [
            (0, 'Formatura — Técnico em Gastronomia', 'gestor.marina',
             time(19, 0), time(21, 30)),
            (2, 'Palestra: Carreiras em TI', 'analista.rafael',
             time(14, 0), time(17, 0))]:
        d = _data_livre(_proximo_dia_semana(dia_util, weekday), feriados,
                        ctr.id)
        reservar(user_id=usuarios[quem].id, classroom_id=sala(ctr, 'AU101').id,
                 unity_id=ctr.id, title=titulo,
                 description='Evento aberto à comunidade.',
                 date=d, start_time=inicio, end_time=fim, status='approved')

    # 6) SÉRIE DE REPETIÇÃO — origem + 5 aulas semanais com o mesmo
    #    repeat_group_id (editável/excluível em lote em "Gerenciar Série").
    origem_d = _data_livre(_proximo_dia_semana(dia_util, 3), feriados, ctr.id)
    serie = reservar(
        user_id=usuarios['prof.bruno'].id, classroom_id=sala(ctr, 'LI201').id,
        unity_id=ctr.id, teacher_id=usuarios['prof.bruno'].id,
        course_id=disciplinas[(ctr.id, 'INF-001')].course_id,
        subject_id=disciplinas[(ctr.id, 'INF-001')].id,
        title='Programação Web — Turma Noturna',
        description='Série semanal criada pela tela "Repetir".',
        date=origem_d, start_time=time(19, 0), end_time=time(21, 0),
        status='approved')
    db.session.flush()
    for semana in range(1, 6):
        d = origem_d + timedelta(days=7 * semana)  # quinta+7 nunca é domingo
        reservar(user_id=serie.user_id, classroom_id=serie.classroom_id,
                 unity_id=serie.unity_id, teacher_id=serie.teacher_id,
                 course_id=serie.course_id, subject_id=serie.subject_id,
                 title=serie.title, description=serie.description,
                 date=d, start_time=serie.start_time, end_time=serie.end_time,
                 status='approved', repeat_group_id=serie.id)

    # 7) APROVADA COM PARECER — demonstra os campos reviewed_by/review_note
    #    do fluxo administrativo.
    d_aprovada = _data_livre(_proximo_dia_semana(dia_util, 0), feriados,
                             ctr.id)
    reservar(user_id=usuarios['func.juliana'].id,
             classroom_id=sala(ctr, 'SA102').id, unity_id=ctr.id,
             title='Evento Interno — Semana do Servidor',
             description='Espaço para dinâmica da equipe administrativa.',
             date=d_aprovada, start_time=time(8, 0), end_time=time(10, 0),
             status='approved', reviewed_by=admin.id,
             review_note='Aprovada pela direção — sem conflito de aulas.')

    # 8) NORTE — reservas futuras próprias (professores e salas isolados).
    d_norte = _data_livre(_proximo_dia_semana(dia_util, 1), feriados,
                          norte.id)
    reservar(user_id=usuarios['prof.helena'].id,
             classroom_id=sala(norte, 'SA101').id, unity_id=norte.id,
             teacher_id=usuarios['prof.helena'].id,
             course_id=disciplinas[(norte.id, 'ADM-101')].course_id,
             subject_id=disciplinas[(norte.id, 'ADM-101')].id,
             title='Contabilidade Básica — Noturno',
             description='Aula agendada para alunos.',
             date=d_norte, start_time=time(19, 0), end_time=time(21, 0),
             status='approved')

    db.session.flush()


def _seed_pagamentos_demo(unidades, usuarios, admin):
    """Financeiro — Hora Extra: lançamentos no MÊS BASE atual (regra da tela:
    não lança mês passado), com níveis/turnos/códigos variados."""
    mes_atual = date.today().strftime('%Y-%m')
    ctr, norte, _ = (unidades[c] for c in DEMO_UNITY_CODES)
    lancamentos = [
        ('prof.ana', ctr, 'Superior', 4, '45.00', '10.01.2345.6', 'Noturno',
         '10, 17, 24', 'Substituição de aula — Gastronomia'),
        ('prof.bruno', ctr, 'Técnico', 2, '38.50', '95.00.1234.5', 'Noturno',
         '12, 19', 'Recuperação de aula — Informática'),
        ('prof.carla', ctr, 'Superior', 6, '52.30', '10.02.9876.5',
         'Vespertino', '08, 15, 22, 29', 'Plantão de dúvidas — Enfermagem'),
        ('prof.gustavo', norte, 'Técnico', 2, '36.20', '95.00.4321.0',
         'Noturno', '11, 18', 'Manutenção de laboratório — Informática'),
    ]
    for quem, unity, nivel, carga, valor, codigo, turno, datas, motivo \
            in lancamentos:
        db.session.add(TeacherOvertimePay(
            teacher_id=usuarios[quem].id, unity_id=unity.id,
            teaching_level=nivel, weekly_workload=carga,
            hourly_value=Decimal(valor), budget_code=codigo, shift=turno,
            multiple_dates=datas, justification=motivo, month_base=mes_atual,
            accountable_id=admin.id))
    db.session.flush()


def _seed_vt_demo(unidades):
    """Financeiro — Vale-Transporte: colaboradores cobrindo os três grupos da
    exportação (Professores, Faculdade e Restaurante), optantes e não
    optantes, nome padronizado (com original preservado) e as inconsistências
    de matrícula/nome repetidos que ganham selos de aviso na listagem."""
    ctr, _, _ = (unidades[c] for c in DEMO_UNITY_CODES)

    def colaborador(matricula, nome, optant, link, unity_pc, empresa_a=None,
                    passes_a=0, valor_a='0.00', empresa_b=None, passes_b=0,
                    valor_b='0.00', original_name=None):
        valor_a, valor_b = Decimal(valor_a), Decimal(valor_b)
        db.session.add(VtRecord(
            unity_id=ctr.id, registration=matricula, full_name=nome,
            original_name=original_name, optant=optant, link=link,
            unity=unity_pc, company_count=bool(empresa_a) + bool(empresa_b),
            company_a_name=empresa_a, company_a_value=valor_a,
            company_a_passes=passes_a, company_a_total=passes_a * valor_a,
            company_b_name=empresa_b, company_b_value=valor_b,
            company_b_passes=passes_b, company_b_total=passes_b * valor_b,
            total_passes=passes_a + passes_b,
            total_value=(passes_a * valor_a) + (passes_b * valor_b)))

    # Grupo PROFESSORES da exportação (link "Professor(a)")
    colaborador('VT-0001', 'Ana Paula Souza', 'Sim', 'Professor(a)',
                'Faculdade', 'Viação Centro', 44, '5.80', 'Viação Litoral',
                22, '6.40')
    colaborador('VT-0002', 'Bruno Costa', 'Sim', 'Professor(a)', 'Faculdade',
                'Viação Centro', 44, '5.80')
    colaborador('VT-0003', 'Carla Dias', 'Não', 'Professor(a)', 'Faculdade')
    # Grupo FACULDADE (Técnico-Administrativo + unidade do pedido "Faculdade")
    colaborador('VT-0004', 'Juliana Castro', 'Sim', 'Técnico - Administrativo',
                'Faculdade', 'Viação Centro', 44, '5.20', 'Viação Litoral',
                22, '6.10')
    # Grupo RESTAURANTE (Técnico-Administrativo nas unidades do gerador)
    colaborador('VT-0005', 'Roberto Silva', 'Sim', 'Técnico - Administrativo',
                'Restaurante - ALESC/Palácio Barriga Verde',
                'Viação Continental', 26, '4.90')
    colaborador('VT-0006', 'Patrícia Rocha', 'Não',
                'Técnico - Administrativo',
                'Lanchonete - ALESC/Unidade Administrativa')
    # Nome padronizado na importação: selo "nome ajustado" com o original
    colaborador('VT-0007', 'Carlos Eduardo Da Silva', 'Sim', 'Estagiário',
                'Faculdade', 'Viação Centro', 22, '5.80',
                original_name='CARLOS EDUARDO DA SILVA')
    # Optante com 0 passes: aparece na listagem, não vai para a exportação
    colaborador('VT-0008', 'Marcos Lima', 'Sim', 'Técnico - Administrativo',
                'Faculdade')
    # INCONSISTÊNCIAS (selos de aviso): matrícula repetida e nome repetido
    colaborador('VT-0909', 'Diego Nunes', 'Sim', 'Professor(a)', 'Faculdade',
                'Viação Centro', 44, '5.80')
    colaborador('VT-0909', 'Helena Prado', 'Sim', 'Professor(a)', 'Faculdade',
                'Viação Litoral', 44, '6.40')
    colaborador('VT-0010', 'José Carlos De Oliveira', 'Sim',
                'Técnico - Administrativo', 'Faculdade',
                'Viação Centro', 44, '5.20')
    colaborador('VT-0011', 'José Carlos De Oliveira', 'Sim',
                'Técnico - Administrativo', 'Faculdade',
                'Viação Litoral', 22, '6.10')
    db.session.flush()


def _escrever_docx_minimo(caminho, titulo, linhas):
    """Gera um .docx mínimo (zip + WordprocessingML) para o arquivo das fichas
    existir de verdade e o download autenticado funcionar na demonstração.
    Não usa python-docx: o formato basta para abrir no Word/LibreOffice."""
    paragrafos = ''.join(
        f'<w:p><w:r><w:t>{escape(linha)}</w:t></w:r></w:p>'
        for linha in [titulo] + linhas)
    conteudo_tipos = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType='
        '"application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType='
        '"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>')
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '</Relationships>')
    documento = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main">'
        f'<w:body>{paragrafos}</w:body></w:document>')
    with zipfile.ZipFile(caminho, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', conteudo_tipos)
        zf.writestr('_rels/.rels', rels)
        zf.writestr('word/document.xml', documento)


def _pasta_fichas():
    folder = os.path.join(current_app.instance_path, 'uploads',
                          'technical_sheets')
    os.makedirs(folder, exist_ok=True)
    return folder


def _ficha_demo(nome_arquivo, titulo, linhas):
    """Grava o .docx na pasta de uploads e devolve (original, armazenado)."""
    armazenado = f'seed_demo_{uuid.uuid4().hex[:8]}_{nome_arquivo}'
    _escrever_docx_minimo(os.path.join(_pasta_fichas(), armazenado),
                          titulo, linhas)
    return nome_arquivo, armazenado


def _seed_cozinha_demo(unidades, usuarios):
    """Módulo Cozinha (Centro — o Norte tem o módulo desligado): receita salva
    com ESCALA de porções e ingrediente INATIVO, receita sem escala e ficha
    PENDENTE aguardando o botão "Salvar Ficha Técnica"."""
    ctr, _, _ = (unidades[c] for c in DEMO_UNITY_CODES)
    ana = usuarios['prof.ana']

    def ingrediente(preparacao, nome, especificacao, quantidade, raw, unidade,
                    posicao, ativo=True):
        preparacao.ingredients.append(KitchenRecipeIngredient(
            name=nome, specification=especificacao, quantity=quantidade,
            quantity_raw=raw, unit=unidade, position=posicao,
            is_active=ativo))

    # Receita 1 — salva a partir de uma ficha, com escala ×3 (10 → 30 porções)
    original1, armazenado1 = _ficha_demo(
        'ficha-bolo-de-cenoura.docx', 'Ficha Técnica — Bolo de Cenoura',
        ['Rendimento: 10 porções'])
    ficha1 = TechnicalSheet(
        unity_id=ctr.id, original_filename=original1,
        stored_filename=armazenado1, uploaded_by_id=ana.id, status='saved')
    db.session.add(ficha1)
    db.session.flush()
    bolo = KitchenRecipe(
        unity_id=ctr.id, technical_sheet_id=ficha1.id,
        name='Bolo de Cenoura com Cobertura de Chocolate',
        equipments='Forno combinado; Liquidificador; Batedeira',
        utensils='Forma de bolo 30cm; Espátula; Bowls de inox',
        prep_time='60 minutos', yield_info='10 porções',
        steps_text='Bata cenoura, ovos e óleo no liquidificador.\n'
                   'Misture os secos e asse a 180°C por 40 minutos.\n'
                   'Derreta o chocolate com a manteiga e cubra o bolo.',
        general_notes='Servir morno. Rende fatias generosas.',
        allergens='Contém glúten (farinha de trigo), ovo, leite e soja.',
        references='Técnica Dietética — FIESC (2023).',
        scaled_portions=30)  # escala salva: quantidades ×3 na tela e na compra
    massa = KitchenPreparation(name='Massa', position=0, recipe=bolo)
    ingrediente(massa, 'Cenoura', 'in natura, raspada', 500, '500', 'g', 0)
    ingrediente(massa, 'Açúcar refinado', 'Tipo 1', 400, '400', 'g', 1)
    ingrediente(massa, 'Farinha de trigo', 'sem fermento', 300, '300', 'g', 2)
    ingrediente(massa, 'Ovos', 'médio', 4, '4', 'un', 3)
    ingrediente(massa, 'Óleo de soja', 'refinado', 120, '120', 'ml', 4)
    ingrediente(massa, 'Nozes picadas', 'decoração', 50, '50', 'g', 5,
                ativo=False)  # desativado: fora da requisição de compra
    cobertura = KitchenPreparation(name='Cobertura', position=1, recipe=bolo)
    ingrediente(cobertura, 'Chocolate meio amargo', '50% cacau', 200, '200',
                'g', 0)
    ingrediente(cobertura, 'Manteiga sem sal', '', 50, '50', 'g', 1)
    ingrediente(cobertura, 'Leite integral', '', 100, '100', 'ml', 2)

    # Receita 2 — sem escala (quantidades originais da ficha)
    risoto = KitchenRecipe(
        unity_id=ctr.id, name='Risoto de Frango com Limão',
        equipments='Cooktop industrial; Frigideira alta',
        utensils='Colher de pau; Concha; Faca de chef',
        prep_time='45 minutos', yield_info='4 a 6 porções (aprox. 20 conchas)',
        steps_text='Grelhe o frango temperado e reserve.\n'
                   'Refogue a cebola, adicione o arroz e o vinho.\n'
                   'Adicione o caldo aos poucos até o ponto cremoso.\n'
                   'Finalize com manteiga, limão e salsinha.',
        general_notes='O caldo deve estar quente antes de adicionar.',
        allergens='Contém leite. Sem glúten.',
        references='Cardápio Escolar — FNDE (2022).')
    arroz = KitchenPreparation(name='Arroz', position=0, recipe=risoto)
    ingrediente(arroz, 'Arroz arbóreo', 'tipo 1', 400, '400', 'g', 0)
    ingrediente(arroz, 'Cebola', 'branca, brunoise', 120, '120', 'g', 1)
    ingrediente(arroz, 'Caldo de galinha', 'diluído', 1000, '1000', 'ml', 2)
    ingrediente(arroz, 'Vinho branco', 'seco', 100, '100', 'ml', 3)
    ingrediente(arroz, 'Manteiga', 'para finalizar', 30, '30', 'g', 4)
    frango = KitchenPreparation(name='Frango', position=1, recipe=risoto)
    ingrediente(frango, 'Peito de frango', 'em cubos', 600, '600', 'g', 0)
    ingrediente(frango, 'Limão siciliano', 'raspas e suco', 2, '2', 'un', 1)
    ingrediente(frango, 'Salsinha', 'picada', 15, '15', 'g', 2)

    # Mesmo padrão do blueprint: a receita entra na sessão só DEPOIS de as
    # preparações estarem montadas — o inverso quebra o cascade e grava a
    # receita sem preparações/ingredientes.
    db.session.add(bolo)
    db.session.add(risoto)

    # Ficha PENDENTE — aparece na fila com o botão "Salvar Ficha Técnica"
    original3, armazenado3 = _ficha_demo(
        'ficha-escondidinho.docx',
        'Ficha Técnica — Escondidinho de Carne Seca',
        ['Rendimento: 8 porções'])
    pendente = TechnicalSheet(
        unity_id=ctr.id, original_filename=original3,
        stored_filename=armazenado3, uploaded_by_id=ana.id, status='pending',
        data_json=json.dumps({
            'nome': 'Escondidinho de Carne Seca',
            'equipamentos': 'Forno combinado; Fogão industrial',
            'utensilios': 'Refratária de vidro; Pilão',
            'tempo_preparo': '90 minutos',
            'rendimento': '8 porções',
            'preparacoes': [{
                'nome': 'Escondidinho de Carne Seca',
                'ingredientes': [
                    {'nome': 'Carne seca', 'especificacao': 'dessalgada',
                     'quantidade': 800, 'quantidade_raw': '800',
                     'unidade': 'g'},
                    {'nome': 'Mandioca', 'especificacao': 'cozida',
                     'quantidade': 1000, 'quantidade_raw': '1000',
                     'unidade': 'g'},
                    {'nome': 'Creme de leite', 'especificacao': '',
                     'quantidade': 200, 'quantidade_raw': '200',
                     'unidade': 'ml'},
                ],
            }],
            'modo_preparo': ['Dessalgue e desfie a carne seca.',
                             'Cozinhe a mandioca e faça um purê.',
                             'Monte em refratária e gratine.'],
            'observacoes': 'Servir com arroz branco.',
            'alergenicos': 'Contém leite.',
            'referencias': 'Ficha Técnica Operacional — Senac SC.',
        }))
    db.session.add(pendente)
    db.session.flush()


def _seed_token_api_demo(admin):
    """Token de API com valor FIXO e documentado para testar /api/v1 sem gerar
    token no painel (o banco guarda apenas o SHA-256, como nos tokens reais)."""
    db.session.add(ApiToken(
        name=DEMO_API_TOKEN_NAME,
        token_hash=hashlib.sha256(DEMO_API_TOKEN.encode('utf-8')).hexdigest(),
        prefix=DEMO_API_TOKEN[:13] + '…',
        created_by_id=admin.id))
    db.session.flush()


# ── Reset ────────────────────────────────────────────────────────────────────

def _reset_demo():
    """Remove TODOS os dados criados por este seed (escopo restrito aos
    códigos/unidades de demonstração), na ordem de dependências. Bulk delete
    não dispara cascata ORM, então cada nível sai explicitamente."""
    unities = Unity.query.filter(Unity.code.in_(DEMO_UNITY_CODES)).all()
    unity_ids = [u.id for u in unities]

    recipe_ids = [r.id for r in KitchenRecipe.query.filter(
        KitchenRecipe.unity_id.in_(unity_ids)).all()]
    prep_ids = [p.id for p in KitchenPreparation.query.filter(
        KitchenPreparation.recipe_id.in_(recipe_ids)).all()] \
        if recipe_ids else []
    if prep_ids:
        KitchenRecipeIngredient.query.filter(
            KitchenRecipeIngredient.preparation_id.in_(prep_ids)) \
            .delete(synchronize_session=False)
    if recipe_ids:
        KitchenPreparation.query.filter(
            KitchenPreparation.recipe_id.in_(recipe_ids)) \
            .delete(synchronize_session=False)
    KitchenRecipe.query.filter(KitchenRecipe.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)
    TechnicalSheet.query.filter(TechnicalSheet.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)

    VtRecord.query.filter(VtRecord.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)
    TeacherOvertimePay.query.filter(TeacherOvertimePay.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)
    Holiday.query.filter(Holiday.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)

    # Reservas: primeiro as filhas da série, depois todas da unidade.
    Reservation.query.filter(Reservation.unity_id.in_(unity_ids),
                             Reservation.repeat_group_id.isnot(None)) \
        .delete(synchronize_session=False)
    Reservation.query.filter(Reservation.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)
    Subject.query.filter(Subject.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)
    Course.query.filter(Course.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)
    Classroom.query.filter(Classroom.unity_id.in_(unity_ids)) \
        .delete(synchronize_session=False)

    user_ids = [u.id for u in User.query.filter(
        User.unity_id.in_(unity_ids)).all()]
    if user_ids:
        db.session.execute(
            user_roles.delete().where(user_roles.c.user_id.in_(user_ids)))
        User.query.filter(User.id.in_(user_ids)) \
            .delete(synchronize_session=False)

    for unity in unities:
        db.session.delete(unity)

    # Categorias: só apaga as que não ficaram referenciadas por salas de
    # fora da demonstração (o `flask seed` antigo usa os mesmos codes).
    for cat in RoomCategory.query.filter(
            RoomCategory.code.in_(DEMO_CATEGORY_CODES)).all():
        if Classroom.query.filter_by(category_id=cat.id).count() == 0:
            db.session.delete(cat)

    db.session.execute(
        ApiToken.__table__.delete().where(
            ApiToken.__table__.c.name == DEMO_API_TOKEN_NAME))
    db.session.commit()


# ── Comando ──────────────────────────────────────────────────────────────────

@click.command('seed-demo')
@click.option('--reset', is_flag=True,
              help='Apaga a demonstração anterior antes de recriar.')
@with_appcontext
def seed_demo_command(reset):
    """Popula o banco com o cenário de demonstração completo do SIGerE.

    Cria unidades (com módulo desligado e unidade inativa), usuários de todos
    os papéis, categorias e salas variadas, cursos, disciplinas, feriados,
    reservas em todas as situações (hoje, pendente, conflito, cancelada,
    passada, futuras, série), hora extra, vale-transporte, cozinha e um token
    da API de reservas. Permissões/papéis e conta 'admin' são criados se o
    banco ainda não os tiver.
    """
    ja_existe = Unity.query.filter(Unity.code.in_(DEMO_UNITY_CODES)).first()
    if ja_existe and not reset:
        click.echo(click.style(
            f"⚠️  A demonstração já existe neste banco (unidade "
            f"'{ja_existe.code}'). Use --reset para apagá-la e recriar.",
            fg='yellow'))
        raise click.ClickException('Nada foi alterado.')
    if reset:
        _reset_demo()
        click.echo(click.style("🧹 Demonstração anterior removida.",
                               fg='yellow'))

    click.echo(click.style("🌱 Populando o cenário de demonstração...",
                           fg='green', bold=True))
    try:
        # Pré-requisitos: permissões/papéis e a conta admin (idempotentes)
        sync_permissions_impl(verbose=False)
        admin = User.query.filter_by(email='admin@school.edu').first()
        if admin is None:
            _seed_admin(password=DEMO_PASSWORD)
            admin = User.query.filter_by(email='admin@school.edu').first()

        unidades = _seed_unidades_demo()
        usuarios = _seed_usuarios_demo(unidades)
        categorias = _seed_categorias_demo()
        salas = _seed_salas_demo(unidades, categorias)
        _, disciplinas = _seed_cursos_demo(unidades)
        feriados = _seed_feriados_demo(unidades)
        _seed_reservas_demo(unidades, salas, disciplinas, usuarios, feriados)
        _seed_pagamentos_demo(unidades, usuarios, admin)
        _seed_vt_demo(unidades)
        _seed_cozinha_demo(unidades, usuarios)
        _seed_token_api_demo(admin)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        click.echo(click.style(
            f"❌ Falha na população. Todas as alterações foram revertidas.\n"
            f"   Erro: {exc}", fg='red', bold=True))
        raise click.ClickException(str(exc))

    # Resumo da execução (contagens pós-commit)
    usuarios_demo = len(DEMO_EMAILS) + 1  # + conta admin
    click.echo(click.style("✅ Cenário de demonstração criado!", fg='green',
                           bold=True))
    click.echo(f"""
   Unidades ............. {len(DEMO_UNITY_CODES)} (Centro, Norte e Sul — Norte sem Cozinha, Sul inativa)
   Usuários ............. {usuarios_demo} (todos os papéis + Módulo Cozinha)
   Categorias/salas ..... {RoomCategory.query.count()}/{Classroom.query.count()} (7 tipos; 1 sala inativa)
   Cursos/disciplinas ... {Course.query.count()}/{Subject.query.count()} (1 curso inativo)
   Feriados ............. {Holiday.query.count()} (nacionais + municipal + 1 inativo)
   Reservas ............. {Reservation.query.count()} (hoje, pendente, conflito, cancelada, passada, série)
   Hora extra ........... {TeacherOvertimePay.query.count()} lançamentos (mês base atual)
   Vale-Transporte ...... {VtRecord.query.count()} colaboradores (3 grupos + inconsistências)
   Cozinha .............. {KitchenRecipe.query.count()} preparações, {TechnicalSheet.query.count()} fichas (1 pendente)

   Logins (senha {DEMO_PASSWORD} para todos):
     admin@school.edu          Super Administrador (global, todas as unidades)
     gestor.marina@demo.edu.br       Gestor — Unidade Centro
     analista.rafael@demo.edu.br     Analista — Unidade Centro
     prof.ana@demo.edu.br            Professor(a) de Gastronomia + Módulo Cozinha
     prof.bruno@demo.edu.br          Professor(a) de Informática
     prof.elisa@demo.edu.br          Professor(a) INATIVA (login recusado)
     prof.felipe@demo.edu.br         Professor(a) com troca de senha obrigatória
     func.marcos@demo.edu.br         Funcionário que também leciona
     func.juliana@demo.edu.br        Assistente/Logística

   Token da API de reservas (Bearer em /api/v1):
     {DEMO_API_TOKEN}

   ⚠️  Dados de demonstração NUNCA em produção — revogue o token e remova as
   contas (ou rode numa base de testes) antes de implantar.
""")
