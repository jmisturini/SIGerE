"""Importador one-shot do sistema legado (Django + MySQL, dump do phpMyAdmin).

Lê o arquivo .sql diretamente — não precisa de servidor MySQL — e popula os
models do SIGERE. Uso:

    flask --app run import-legacy --dump caminho/para/sigere_active.sql

Pré-requisito: banco vazio (criado por `flask db upgrade`). O comando recusa
bancos com dados, exceto com --force.

Decisões de mapeamento documentadas (ver docs/migracao-legado.md):
- `authenticator_customuser` + `authenticator_teachersuser` fundidos em User
  por `registration`; professores recebem perfil/role de professor.
- Senhas Django `pbkdf2_sha256$iter$salt$hash` são transcodificadas para o
  formato do Werkzeug `pbkdf2:sha256:iter$salt$hash` (mesmo algoritmo), então
  o usuário entra com a senha antiga e é forçado a trocá-la. Hashes corrompidos
  no legado (prefixo estranho) viram senha inutilizável + troca obrigatória.
- `class_control` vira Reservation; o turno (`shifts`) define start/end
  (07-12, 12-18, 18-22 — mesmo padrão dos horários do auditorium legado).
- Tudo é importado para a unidade única "Faculdade Senac Florianópolis"
  (código FLO, mesmo cadastro do seed padrão) — decisão do usuário.
- `auditorium_control` vira Reservation na sala sintética "Auditório".
- Status legado 1 → approved; 2 → cancelled (hipótese: cancelado/nao ocorrido).
  O status numérico original fica em review_note para re-mapeamento via SQL.
- `teacher_overtime_pay` vira TeacherOvertimePay. Tabelas de pagamento base/
  aditivo não têm equivalente no SIGERE e são apenas contadas no relatório.
"""
import re
from datetime import date, datetime, time, timezone

import click
from sqlalchemy import select

from app.extensions import db
from app.models import (Classroom, Course, Reservation, RoomCategory, Role,
                        Subject, TeacherOvertimePay, Unity, User)

# ─────────────────────────────────────────────────────────────────────────────
# Parser do dump phpMyAdmin (estrutura regular: INSERT INTO `t` (...) VALUES
# com tuplas em linhas, strings escapadas no estilo MySQL.
# ─────────────────────────────────────────────────────────────────────────────

_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "b": "\b", "Z": "\x1a"}


def _unescape(s):
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            out.append(_ESCAPES.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _iter_tuple_bodies(block):
    """Gera o corpo interno de cada tupla '( ... )' de um bloco VALUES,
    respeitando strings com escape."""
    depth = in_str = esc = 0
    start = 0
    for i, ch in enumerate(block):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "'":
                in_str = False
            continue
        if ch == "'":
            in_str = 1
        elif ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                yield block[start:i]
        # dentro de tupla, depth >= 1


def _parse_values(body):
    """Corpo de uma tupla -> lista de valores (None para NULL, str p/ resto).

    `pending` marca que há token cru acumulado desde a última vírgula: evita
    emitir um token vazio espúrio na vírgula que segue um valor string.
    """
    values, cur, i, n = [], [], 0, len(body)
    pending = False
    while i < n:
        ch = body[i]
        if ch == "'":
            i += 1
            buf = []
            while i < n:
                c = body[i]
                if c == "\\" and i + 1 < n:
                    buf.append(_ESCAPES.get(body[i + 1], body[i + 1]))
                    i += 2
                elif c == "'":
                    i += 1
                    break
                else:
                    buf.append(c)
                    i += 1
            values.append("".join(buf))
            pending = False
        elif ch == ",":
            if pending:
                tok = "".join(cur).strip()
                values.append(None if tok.upper() == "NULL" else tok)
            cur = []
            pending = False
            i += 1
        elif ch in " \t":
            i += 1
        else:
            cur.append(ch)
            pending = True
            i += 1
    if pending:
        tok = "".join(cur).strip()
        values.append(None if tok.upper() == "NULL" else tok)
    return values


def read_dump_table(content, table):
    """Todas as linhas de `table` no dump como lista de dicts (valor str/None)."""
    pattern = re.compile(
        r"INSERT INTO `" + re.escape(table) + r"` \(([^)]*)\) VALUES\n(.*?)(?=\nINSERT INTO|\n-- |\Z)",
        re.S,
    )
    cols, rows = [], []
    for m in pattern.finditer(content):
        cols = [c.strip().strip("`") for c in m.group(1).split(",")]
        for body in _iter_tuple_bodies(m.group(2)):
            values = _parse_values(body)
            rows.append(dict(zip(cols, values)))
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Conversões de domínio
# ─────────────────────────────────────────────────────────────────────────────

# Turno legado (shifts) -> janela de horário. É o mesmo padrão dos horários
# gravados no auditorium_control (07-12 / 12-18 / 18-22).
SHIFT_TIMES = {
    "1": (time(7, 0), time(12, 0)),    # Matutino
    "2": (time(12, 0), time(18, 0)),   # Vespertino
    "3": (time(18, 0), time(22, 0)),   # Noturno
}

# Categorias de sala derivadas da descrição legada (ordem = precedência).
ROOM_CATEGORY_RULES = [
    ("lab_info", "Laboratório de Informática", ("INFORMATIC", "INFINITY"),
     {"abbr": "LI", "controla_computadores": True, "color": "#0d6efd", "icon": "bi-pc-display"}),
    ("lab_saude", "Laboratório de Saúde", ("SAÚDE", "SAUDE", "MASSO", "PODO", "ESTÉTICA", "ESTETICA"),
     {"abbr": "LS", "color": "#d63384", "icon": "bi-heart-pulse"}),
    ("cozinha", "Cozinha Pedagógica", ("COZINHA",),
     {"abbr": "CP", "color": "#fd7e14", "icon": "bi-egg-fried"}),
    ("auditorio", "Auditório", ("AUDITÓRIO", "AUDITORIO"),
     {"abbr": "AU", "color": "#6f42c1", "icon": "bi-megaphone", "totem_window": "week"}),
    ("sala_aula", "Sala de Aula", (),
     {"abbr": "SA", "color": "#198754", "icon": "bi-easel"}),
]


# Unidade única de destino da migração (mesmo nome/código do seed padrão em
# docs/unidades-senac-sc.json).
TARGET_UNITY_NAME = "Faculdade Senac Florianópolis"
TARGET_UNITY_CODE = "FLO"


# Grupos de permissão do Django legado -> papel no SIGERE (primeira
# correspondência vence; "_full" gerenciava o módulo, "_base" apenas usava).
GROUP_ROLE_RULES = [
    ("power_user", "admin"),
    ("room_control_full", "room_manager"),
    ("reservation_auditorium_full", "room_manager"),
    ("teacher_pay_full", "room_manager"),
    ("general_registration_full", "room_manager"),
    ("room_control_base", "coordinator"),
    ("reservation_auditorium_base", "coordinator"),
    ("teacher_pay_base", "coordinator"),
    ("general_registration_base", "coordinator"),
]


def _legacy_date(s):
    return date.fromisoformat(s[:10]) if s else None


def _transcode_password(raw):
    """Converte hash Django pbkdf2 para o formato Werkzeug. Retorna
    (hash_werkzeug ou None, senha_valida_bool).

    O digest do Django é base64; o Werkzeug 3.x guarda o mesmo PBKDF2-HMAC-
    SHA256 em hex — decodifica e reencoda para o login funcionar.
    """
    import base64
    if not raw:
        return None, False
    raw = raw.strip()
    if not raw.startswith("pbkdf2_sha256$"):
        # Legado tem hashes corrompidos com prefixo arbitrário (ex.: 'S&n@...')
        return None, False
    try:
        _, iterations, salt, digest = raw.split("$")
        int(iterations)
        hex_digest = base64.b64decode(digest).hex()
    except (ValueError, TypeError):
        return None, False
    return f"pbkdf2:sha256:{iterations}${salt}${hex_digest}", True


def _norm_email(raw, fallback):
    email = (raw or "").strip().lower()
    return email or fallback


# ─────────────────────────────────────────────────────────────────────────────
# Importação
# ─────────────────────────────────────────────────────────────────────────────

def _get_or_create_room_categories():
    cats = {}
    for code, name, _keywords, extra in ROOM_CATEGORY_RULES:
        cat = db.session.scalar(select(RoomCategory).where(RoomCategory.code == code))
        if cat is None:
            cat = RoomCategory(code=code, name=name, is_active=True, **extra)
            db.session.add(cat)
        cats[code] = cat
    db.session.flush()
    return cats


def _strip_accents(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _classify_room(description):
    d = _strip_accents((description or "").upper())
    for code, _name, keywords, _extra in ROOM_CATEGORY_RULES:
        if any(_strip_accents(k) in d for k in keywords):
            return code
    return "sala_aula"


def import_legacy(dump_path, force=False):
    """Executa a importação completa. Retorna dict com contagens p/ relatório."""
    with open(dump_path, encoding="utf-8") as f:
        content = f.read()

    counts = {}
    report = []

    # ── Guardas ──────────────────────────────────────────────────────────
    if not force and (Unity.query.count() or User.query.count() or Classroom.query.count()):
        raise RuntimeError(
            "O banco já possui dados. A importação espera um banco vazio "
            "(flask db upgrade em um banco novo). Use --force para importar mesmo assim."
        )

    # Papéis precisam existir para vincular role_id dos usuários.
    from app.commands import sync_permissions_impl
    sync_permissions_impl(verbose=False)
    roles = {r.name: r for r in db.session.scalars(select(Role))}

    # ── Unidade única: todo o acervo do legado vai para a Faculdade Senac
    # Florianópolis (decisão do usuário — o legado tinha "Palhoça" cadastrada,
    # porém sem nenhum dado vinculado). O cadastro é o mesmo do seed padrão
    # (docs/unidades-senac-sc.json), reaproveitado se já existir.
    unity = db.session.scalar(select(Unity).where(
        (Unity.name == TARGET_UNITY_NAME) | (Unity.code == TARGET_UNITY_CODE)))
    if unity is None:
        unity = Unity(
            name=TARGET_UNITY_NAME, code=TARGET_UNITY_CODE, is_active=True,
            address="Rua Silva Jardim, 360 - Prainha, Florianópolis/SC, CEP 88020-200",
            phone="(48) 3229-3200",
            weather_city="Florianópolis, SC",
            weather_latitude=-27.6037202,
            weather_longitude=-48.5491257,
        )
        db.session.add(unity)
        db.session.flush()
    counts["unidades"] = 1
    report.append(f"Unidade única: '{TARGET_UNITY_NAME}' (código {TARGET_UNITY_CODE}) "
                  "recebe todo o acervo importado.")

    def unity_for(_old_unit_id):
        # O legado tinha 2 unidades, mas 100% dos dados apontam para a
        # Florianópolis; Palhoça fica de fora da importação.
        return unity

    # ── Usuários (customuser + teachersuser, dedup por registration) ─────
    legacy_users = read_dump_table(content, "authenticator_customuser")
    legacy_teachers = read_dump_table(content, "authenticator_teachersuser")
    cores = {r["id"]: r["core"] for r in read_dump_table(content, "cores")}
    sectors = {r["id"]: r["sector"] for r in read_dump_table(content, "sectors")}
    functions = {r["id"]: r["function"] for r in read_dump_table(content, "functions")}

    users_by_reg = {}     # registration(int) -> User
    users_by_old = {}     # ('cu', old_id) -> User (accountable_id aponta p/ customuser.id)
    seen_regs = set()     # legado tem matrícula repetida (ex.: 9999); repetida fica sem matrícula

    def create_user(*, registration, email, first_name, last_name, username,
                    is_active, role_name, is_teacher,
                    department=None, sector=None, function=None, unity=None,
                    password_hash=None, password_ok=False, date_joined=None):
        full_name = f"{(first_name or '').strip()} {(last_name or '').strip()}".strip() or username
        email = _norm_email(email, f"{username}@sem-email.legado")
        # Regra do quadro: com setor/departamento/função preenchidos o cadastro
        # é de funcionário — quem leciona segue designável via is_teacher.
        # Só é professor quem não tem nenhum vínculo administrativo.
        tem_lotacao = bool(department or sector or function)
        user = User(
            email=email,
            full_name=full_name,
            role=role_name,
            role_id=roles[role_name].id if role_name in roles else None,
            department=department,
            sector=sector,
            function=function,
            registration=str(registration) if registration and registration not in seen_regs else None,
            profile_type="teacher" if (is_teacher and not tem_lotacao) else "employee",
            is_teacher=is_teacher,
            unity_id=unity.id if unity else None,
            is_active_user=bool(is_active),
            force_password_change=True,
            created_at=date_joined or datetime.now(timezone.utc),
        )
        if registration:
            seen_regs.add(registration)
        if password_ok and password_hash:
            user.password_hash = password_hash          # transcodificado; login com a senha antiga
        else:
            # hash inutilizável: usuário só entra após reset feito por um admin
            import secrets
            from werkzeug.security import generate_password_hash
            user.password_hash = generate_password_hash(secrets.token_hex(32))
        db.session.add(user)
        return user

    def role_for_customuser(row, group_names):
        if row["is_superuser"] == "1":
            return "super_admin"
        if row["is_staff"] == "1":
            return "admin"
        for group, role_name in GROUP_ROLE_RULES:
            if group in group_names:
                return role_name
        return "employee"

    # e-mails já usados para detectar colisão entre registros distintos
    seen_emails = set()

    def unique_email(email, reg):
        base = email
        n = 0
        while email in seen_emails:
            n += 1
            local, _, domain = base.partition("@")
            email = f"{local}+leg{reg}{n if n > 1 else ''}@{domain}"
        seen_emails.add(email)
        return email

    groups_cache = read_dump_table(content, "auth_group")
    groups_by_user = {}
    for link in read_dump_table(content, "authenticator_customuser_groups"):
        gname = next((g["name"] for g in groups_cache if g["id"] == link["group_id"]), "")
        if gname:
            groups_by_user.setdefault(link["customuser_id"], set()).add(gname)

    for r in legacy_users:
        pw_hash, pw_ok = _transcode_password(r["password"])
        reg = int(r["registration"]) if r["registration"] else None
        gnames = groups_by_user.get(r["id"], set())
        department = cores.get(r["core_id"])
        sector = sectors.get(r["sector_id"])
        function = functions.get(r["function_id"])
        is_teacher_profile = (function or "").lower().startswith("prof")
        role_name = role_for_customuser(r, gnames)
        # Regra do quadro: com setor/departamento/função preenchidos o perfil
        # é de funcionário — o papel 'teacher' só entra para quem não tem
        # nenhum vínculo administrativo.
        if role_name == "employee" and is_teacher_profile and not (department or sector or function):
            role_name = "teacher"
        u = create_user(
            registration=reg,
            email=unique_email(_norm_email(r["email"], ""), reg or r["id"]),
            first_name=r["first_name"], last_name=r["last_name"], username=r["username"],
            is_active=r["is_active"] == "1",
            role_name=role_name,
            is_teacher=is_teacher_profile,
            department=department,
            sector=sector,
            function=function,
            unity=unity_for(r["unit_id"]),
            password_hash=pw_hash, password_ok=pw_ok,
            date_joined=_legacy_date(r["date_joined"]),
        )
        users_by_reg[reg] = u
        users_by_old[("cu", r["id"])] = u
    db.session.flush()

    for r in legacy_teachers:
        pw_hash, pw_ok = _transcode_password(r["password"])
        reg = int(r["registration"])
        existing = users_by_reg.get(reg)
        if existing is not None:
            # mesma pessoa: os dados do quadro (customuser) prevalecem. Com
            # setor/departamento/função preenchidos o perfil segue de
            # funcionário; is_teacher=True preserva a designação em reservas.
            existing.is_teacher = True
            if not (existing.department or existing.sector or existing.function):
                existing.profile_type = "teacher"
                if existing.role not in ("admin", "super_admin"):
                    existing.role = "teacher"
                    existing.role_id = roles["teacher"].id
            users_by_old[("tu", reg)] = existing
            continue
        u = create_user(
            registration=reg,
            email=unique_email(r["email"], reg),
            first_name=r["first_name"], last_name=r["last_name"], username=r["username"],
            is_active=r["is_active"] == "1",
            role_name="teacher",
            is_teacher=True,
            unity=unity_for(r["unit_id"]),
            password_hash=pw_hash, password_ok=pw_ok,
            date_joined=_legacy_date(r["date_joined"]),
        )
        users_by_reg[reg] = u
        users_by_old[("tu", reg)] = u
    db.session.flush()
    counts["usuarios"] = User.query.count()
    report.append(f"Usuários criados/fundidos: {counts['usuarios']} "
                  f"({len(legacy_users)} do quadro + {len(legacy_teachers)} professores, dedup por matrícula)")

    # ── Categorias de sala + salas ───────────────────────────────────────
    cats = _get_or_create_room_categories()
    classrooms = read_dump_table(content, "classroom")
    rooms_by_old = {}
    for r in classrooms:
        sem_uso = "SEM USO" in (r["description_class"] or "").upper()
        cat = cats[_classify_room(r["description_class"])]
        desc_parts = [p for p in (r["extra_structure"], r["available_software"]) if p]
        room = Classroom(
            name=(r["description_class"] or f"Sala {r['number_class']}").strip(),
            code=str(r["number_class"]),
            room_number=str(r["number_class"]),
            capacity=int(r["ability"]) if r["ability"] else (0 if sem_uso else 30),
            category_id=cat.id,
            computer_count=int(r["computers_available"] or 0),
            description=" | ".join(desc_parts) or None,
            is_active=not sem_uso,
            unity_id=unity_for("1").id,
        )
        db.session.add(room)
        rooms_by_old[r["id"]] = room
    # Sala sintética para os eventos do auditorium (o legado trata auditório fora de `classroom`)
    auditorium = Classroom(
        name="Auditório", code="AUDITORIO", capacity=250,
        category_id=cats["auditorio"].id, computer_count=0,
        description="Criado na migração: o sistema legado gerenciava o auditório fora da tabela de salas.",
        is_active=True, unity_id=unity_for("1").id,
    )
    db.session.add(auditorium)
    db.session.flush()
    counts["salas"] = len(rooms_by_old) + 1
    report.append(f"Salas importadas: {len(rooms_by_old)} + 1 auditório (sintético)")

    # ── Cursos e matérias ────────────────────────────────────────────────
    legacy_courses = read_dump_table(content, "courses")
    courses_by_old = {}
    for r in legacy_courses:
        course = Course(
            name=(r["course"] or "").strip(),
            code=f"C{int(r['id']):04d}",
            description=f"Importado do legado (núcleo: {cores.get(r['core_id'], '?')})",
            is_active=r["is_active_id"] == "1",
            unity_id=unity_for("1").id,
        )
        db.session.add(course)
        courses_by_old[r["id"]] = course
    db.session.flush()
    counts["cursos"] = len(courses_by_old)

    subjects_by_old = {}
    for r in read_dump_table(content, "matters"):
        subject = Subject(
            name=(r["matter"] or "").strip(),
            code=f"M{int(r['id']):04d}",
            course_id=None,  # no legado matéria não pertence a curso; vínculo fica na reserva
            is_active=r["is_active_id"] == "1",
            unity_id=unity_for("1").id,
        )
        db.session.add(subject)
        subjects_by_old[r["id"]] = subject
    db.session.flush()
    counts["materias"] = len(subjects_by_old)
    report.append(f"Cursos: {counts['cursos']}; matérias: {counts['materias']}")

    # ── Reservas de sala (class_control) ─────────────────────────────────
    skipped_cc = 0
    for r in read_dump_table(content, "class_control"):
        room = rooms_by_old.get(r["classroom_id"])
        account = users_by_old.get(("cu", r["accountable_id"]))
        teacher = users_by_reg.get(int(r["teacher_id"])) if r["teacher_id"] else None
        shift = SHIFT_TIMES.get(r["shift_id"])
        if room is None or account is None or teacher is None or shift is None:
            skipped_cc += 1
            continue
        course = courses_by_old.get(r["course_id"])
        subject = subjects_by_old.get(r["matter_id"])
        title = f"{course.name if course else 'Curso ?'} · {subject.name if subject else 'Matéria ?'}"
        status = "approved" if r["status_course"] == "1" else "cancelled"
        db.session.add(Reservation(
            user_id=account.id,
            classroom_id=room.id,
            course_id=course.id if course else None,
            subject_id=subject.id if subject else None,
            teacher_id=teacher.id,
            unity_id=room.unity_id,
            title=title[:200],
            description=f"Importado do sistema legado (aula; registro {r['id']}).",
            date=_legacy_date(r["reservation"]),
            start_time=shift[0], end_time=shift[1],
            status=status,
            created_at=datetime.combine(_legacy_date(r["reservation_date"]), time(0, 0))
            if r["reservation_date"] else datetime.now(timezone.utc),
            review_note=f"status legado: {r['status_course']}",
        ))
    counts["reservas_aula"] = len(read_dump_table(content, "class_control")) - skipped_cc
    report.append(f"Reservas de aula importadas: {counts['reservas_aula']} (ignoradas sem vínculo: {skipped_cc})")

    # ── Reservas de auditório ────────────────────────────────────────────
    skipped_aud = 0
    for r in read_dump_table(content, "auditorium_control"):
        account = users_by_old.get(("cu", r["accountable_id"]))
        shift = SHIFT_TIMES.get(r["shift_id"])
        if account is None:
            skipped_aud += 1
            continue
        start = _parse_hhmm(r["start_time"]) or (shift[0] if shift else time(7, 0))
        end = _parse_hhmm(r["end_time"]) or (shift[1] if shift else time(12, 0))
        status = "approved" if r["status_reservation"] == "1" else "cancelled"
        db.session.add(Reservation(
            user_id=account.id,
            classroom_id=auditorium.id,
            unity_id=auditorium.unity_id,
            title=(r["name_event"] or "Evento")[:200],
            description=f"{r['description'] or ''} (Importado do legado: evento de auditório, registro {r['id']}; tipo {r['booking_type']})".strip(),
            date=_legacy_date(r["reservation"]),
            start_time=start, end_time=end,
            status=status,
            created_at=datetime.combine(_legacy_date(r["reservation_date"]), time(0, 0))
            if r["reservation_date"] else datetime.now(timezone.utc),
            review_note=f"status legado: {r['status_reservation']}",
        ))
    aud_rows = read_dump_table(content, "auditorium_control")
    counts["reservas_auditorio"] = len(aud_rows) - skipped_aud
    report.append(f"Reservas de auditório importadas: {counts['reservas_auditorio']} (ignoradas: {skipped_aud})")

    # ── Hora extra de professores ────────────────────────────────────────
    teaching_levels = {r["id"]: r["level"] for r in read_dump_table(content, "teaching_level")}
    shifts_name = {r["id"]: r["shift"] for r in read_dump_table(content, "shifts")}
    ot_rows = read_dump_table(content, "teacher_overtime_pay")
    skipped_ot = 0
    for r in ot_rows:
        teacher = users_by_reg.get(int(r["teacher_id"])) if r["teacher_id"] else None
        if teacher is None:
            skipped_ot += 1
            continue
        account = users_by_old.get(("cu", r["accountable_id"]))
        db.session.add(TeacherOvertimePay(
            teacher_id=teacher.id,
            unity_id=teacher.unity_id,
            teaching_level=teaching_levels.get(r["teaching_level_id"], "?"),
            weekly_workload=int(r["weekly_workload"] or 0),
            hourly_value=r["hourly_value"] or "0",
            budget_code=(r["budget_code"] or "")[:18],
            shift=shifts_name.get(r["shift_id"], "?"),
            multiple_dates=(r["multiple_dates"] or "")[:255],
            justification=(r["justification"] or "")[:100],
            month_base=r["month_base"] or "",
            accountable_id=account.id if account else None,
            created_at=datetime.combine(_legacy_date(r["created_at"]) or date(2024, 1, 1), time(0, 0)),
        ))
    counts["hora_extra"] = len(ot_rows) - skipped_ot
    report.append(f"Lançamentos de hora extra importados: {counts['hora_extra']} (ignorados: {skipped_ot})")

    # ── Sem equivalente no SIGERE (apenas relatado) ──────────────────────
    for label, table in [("pagamentos base", "teacher_base_pay"),
                         ("aditivos", "teacher_additive_payment"),
                         ("contratos", "contracts")]:
        n = len(read_dump_table(content, table))
        if n:
            report.append(f"Sem equivalente no SIGERE — {label}: {n} registro(s) NÃO importado(s).")

    db.session.commit()
    counts["relatorio"] = report
    return counts


def _parse_hhmm(raw):
    if not raw:
        return None
    try:
        parts = raw.split(":")
        return time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None
