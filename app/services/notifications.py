"""Varredura de reservas próximas → notificações por destinatário.

Regras do módulo:
- A configuração é por reserva (ReservationNotificationConfig, formulário de
  criar/editar): quem cria a reserva opta por avisar (padrão desativado),
  escolhe os destinatários — usuários individuais e grupos personalizados da
  unidade, mais o próprio criador (padrão ligado) — e os marcos de aviso:
  7 dias, 24h e/ou 1h antes do início e/ou o marco "no dia" (07:00 do próprio
  dia da atividade).
- A cada varredura, a reserva dispara o marco mais iminente já vencido
  (agora >= gatilho — janela aberta: atraso do timer não pula o aviso mais
  próximo). Marcos vencidos anteriores ficam absorvidos: dispará-los
  tardiamente criaria avisos redundantes. A notificação é única por
  (destinatário, reserva, marco) — constraint no banco — então rodar a
  varredura de novo não duplica.
- O marco "no dia" é ancorado a um horário fixo (HORARIO_AVISO_DIA), não a
  uma antecedência: atividade que começa até esse horário nunca o recebe —
  quando o gatilho passa, ela já começou e a varredura a pula.
- A varredura de pendências (varrer_pendentes) roda no mesmo comando e avisa
  os aprovadores da unidade sobre reservas pendentes de aprovação (24h e 48h
  após a criação) — independe da configuração da reserva.
- Só entram reservas approved que ainda não começaram; pendentes, canceladas
  e em andamento não avisam (as pendentes têm varredura própria).
- O usuário pode silenciar os avisos no perfil (UserNotificationPref): todos
  ou apenas os de salas de um tipo (RoomCategory). Vale para os avisos de
  atividade próxima e para os lembretes de pendência.
- O aviso de sobrecarga de professor (EVENT_TEACHER_DAILY_LIMIT) é criado no
  momento da gravação da reserva e não passa por esta varredura nem pelos
  silenciamentos. Idem os avisos de mudança de status e de exclusão
  (notificar_mudanca_status/notificar_exclusao) — criados na ação, para o
  criador da reserva.
"""
from datetime import datetime, time, timedelta

from app.extensions import db
from app.models import (Reservation, User, UnityNotificationConfig, Notification,
                        EVENT_RESERVATION_UPCOMING, EVENT_TEACHER_DAILY_LIMIT,
                        EVENT_RESERVATION_APPROVED, EVENT_RESERVATION_CANCELLED,
                        EVENT_RESERVATION_DELETED,
                        EVENT_RESERVATION_PENDING_REMINDER)
from app.services.scheduling import count_teacher_reservations

# Marco único da notificação de sobrecarga (não é antecedência em horas):
# uma reserva gera no máximo um aviso deste tipo por destinatário.
_MILESTONE_SOBRECARGA = 'diario'

# Marco único dos avisos de mudança de status (aprovada/cancelada/excluída).
_MILESTONE_STATUS = 'status'

# Hora local em que o marco "no dia" passa a valer, no próprio dia da
# atividade.
HORARIO_AVISO_DIA = time(7, 0)

# Marcos de aviso por código. O gatilho recebe o início da reserva e devolve
# o instante a partir do qual o aviso está vencido: os de horas antecedem o
# início; o "dia" é ancorado ao HORARIO_AVISO_DIA do próprio dia.
MARCOS = {
    '7d': ('Em 7 dias', lambda inicio: inicio - timedelta(days=7)),
    '24h': ('Em 24 horas', lambda inicio: inicio - timedelta(hours=24)),
    '1h': ('Em 1 hora', lambda inicio: inicio - timedelta(hours=1)),
    'dia': ('Hoje', lambda inicio: datetime.combine(inicio.date(), HORARIO_AVISO_DIA)),
}

# Lembretes de pendência: horas após a criação da reserva, do menor para o
# maior — vencidos os dois, dispara só o mais recente (mesma regra de
# absorção dos marcos de antecedência).
LEMBRETES_PENDENTE_HORAS = ((24, 'Pendente há 1 dia'), (48, 'Pendente há 2 dias'))


def marcos_da_config(config):
    """Códigos dos marcos habilitados na configuração da reserva."""
    codigos = []
    if config.notify_7d:
        codigos.append('7d')
    if config.notify_24h:
        codigos.append('24h')
    if config.notify_1h:
        codigos.append('1h')
    if config.notify_dia:
        codigos.append('dia')
    return codigos


def _silenciado(user, reservation):
    """Preferências do perfil podem tirar o usuário dos avisos desta reserva:
    mute_all silencia tudo; senão, silencia se o tipo de sala da reserva
    (categoria da classroom) estiver na lista de silenciados."""
    pref = user.notification_pref
    if pref is None:
        return False
    if pref.mute_all:
        return True
    categorias = {c.id for c in pref.muted_categories}
    if not categorias:
        return False
    sala = reservation.classroom
    return sala is not None and sala.category_id in categorias


def destinatarios_da_reserva(reservation, config):
    """Usuários que recebem o aviso da reserva, deduplicados por id.

    Destinatários explícitos da configuração (usuários individuais e membros
    dos grupos selecionados) mais o criador da reserva, quando notify_criador
    está ligado (padrão). Inativos nunca recebem; quem silenciou a notificação
    no perfil (todos ou o tipo de sala desta reserva) é filtrado à parte por
    _silenciado."""
    destino = {}

    def add(user):
        if user is not None and user.is_active_user and user.id not in destino:
            destino[user.id] = user

    if config.notify_criador:
        add(reservation.user)
    for user in config.users:
        add(user)
    for grupo in config.groups:
        for user in grupo.members:
            add(user)
    return list(destino.values())


def _notificacao_existente(user_id, reservation_id, milestone,
                           event_type=EVENT_RESERVATION_UPCOMING):
    return Notification.query.filter_by(
        user_id=user_id, event_type=event_type,
        reservation_id=reservation_id, milestone=milestone,
    ).first()


def varrer_reservas(agora=None, dry_run=False):
    """Cria as notificações de reservas próximas que ainda não existem.

    Percorre as reservas approved com notificações ativadas e configuração
    salva, calcula os instantes de gatilho dos marcos (24h/1h antes do início
    e o "no dia" às 07:00 da data) já vencidos e, no mais iminente, cria o
    aviso por destinatário (get-or-create pela constraint de unicidade),
    respeitando os silenciamentos do perfil. Com dry_run=True nada é gravado
    — a contagem mostra o que seria criado. Retorna estatísticas para o log
    do comando."""
    agora = agora or datetime.now()
    stats = {'reservas': 0, 'criadas': 0, 'existentes': 0}

    reservas = Reservation.query.filter(
        Reservation.status == 'approved',
        Reservation.notify_enabled == True,  # noqa: E712 — comparação de coluna
        Reservation.date >= agora.date(),
    ).all()

    for reservation in reservas:
        config = reservation.notification_config
        if config is None:
            continue
        marcos = marcos_da_config(config)
        if not marcos:
            continue
        inicio = datetime.combine(reservation.date, reservation.start_time)
        # A atividade já começou: avisos de antecedência perderam a função.
        if agora >= inicio:
            continue
        # Marcos vencidos: agora >= gatilho (janela aberta — se o timer ficar
        # horas parado, o aviso mais próximo não se perde). Entre os vencidos
        # dispara só o de gatilho mais recente (o mais iminente): os
        # anteriores foram absorvidos e sairiam com conteúdo redundante.
        vencidos = [(MARCOS[c][1](inicio), c) for c in marcos
                    if agora >= MARCOS[c][1](inicio)]
        if not vencidos:
            continue
        codigo = max(vencidos)[1]
        stats['reservas'] += 1

        destinatarios = [u for u in destinatarios_da_reserva(reservation, config)
                         if not _silenciado(u, reservation)]
        if not destinatarios:
            continue

        titulo = f'{MARCOS[codigo][0]}: {reservation.title}'
        sala = reservation.classroom.code if reservation.classroom else '—'
        corpo = (f'{sala} · {reservation.date.strftime("%d/%m/%Y")} · '
                 f'{reservation.start_time.strftime("%H:%M")}–'
                 f'{reservation.end_time.strftime("%H:%M")}')
        # Deep link: o criador vai para o detalhe da reserva (sempre pode
        # vê-la); os demais, para o calendário na data da atividade — a
        # página aceita ?initialDate= e pré-filtra o dia.
        if reservation.user_id is not None and any(
                u.id == reservation.user_id for u in destinatarios):
            url = f'/reservations/{reservation.id}'
        else:
            url = f'/calendar/?initialDate={reservation.date.isoformat()}'

        milestone = codigo
        for user in destinatarios:
            if _notificacao_existente(user.id, reservation.id, milestone):
                stats['existentes'] += 1
                continue
            if dry_run:
                stats['criadas'] += 1
                continue
            db.session.add(Notification(
                user_id=user.id, reservation_id=reservation.id,
                event_type=EVENT_RESERVATION_UPCOMING, milestone=milestone,
                title=titulo, body=corpo, url=url))
            stats['criadas'] += 1

    if not dry_run:
        db.session.commit()
    return stats


def notificar_sobrecarga_professor(reservation):
    """Aviso imediato da regra de carga docente: a reserva gravada levou o
    professor além do limite diário e nasceu Pendente — os grupos com a
    seleção dedicada na configuração da unidade (overload_groups) recebem um
    aviso para avaliar.

    Diferente da varredura (notify-scan), este aviso é criado no momento em
    que a reserva é gravada. Sem configuração salva ou sem grupos escolhidos,
    ninguém recebe — a pendência da reserva independe do aviso.

    Idempotente pela unicidade de (destinatário, evento, reserva, marco):
    regravar a reserva (ex.: editar) não duplica avisos. Retorna quantos
    avisos criou. A reserva já deve estar em flush (id preenchido).
    """
    config = UnityNotificationConfig.query.filter_by(
        unity_id=reservation.unity_id).first()
    grupos = config.overload_groups if config is not None else []
    if not grupos:
        return 0

    professor = reservation.teacher.full_name if reservation.teacher else 'Professor'
    qtd = count_teacher_reservations(reservation.teacher_id, reservation.date)
    sala = reservation.classroom.code if reservation.classroom else '—'
    titulo = f'Sobrecarga de professor: {reservation.title}'[:200]
    corpo = (f'{professor} ficará com {qtd} reservas em '
             f'{reservation.date.strftime("%d/%m/%Y")} — '
             f'{sala} · {reservation.start_time.strftime("%H:%M")}–'
             f'{reservation.end_time.strftime("%H:%M")}. '
             f'A reserva "{reservation.title}" aguarda aprovação.')

    criadas = 0
    vistos = set()
    for grupo in grupos:
        for user in grupo.members:
            if not user.is_active_user or user.id in vistos:
                continue
            vistos.add(user.id)
            if Notification.query.filter_by(
                    user_id=user.id, event_type=EVENT_TEACHER_DAILY_LIMIT,
                    reservation_id=reservation.id,
                    milestone=_MILESTONE_SOBRECARGA).first():
                continue
            # Deep link: o criador vai ao detalhe da reserva (sempre pode
            # vê-la); os demais, ao calendário no dia da atividade.
            if user.id == reservation.user_id:
                url = f'/reservations/{reservation.id}'
            else:
                url = f'/calendar/?initialDate={reservation.date.isoformat()}'
            db.session.add(Notification(
                user_id=user.id, reservation_id=reservation.id,
                event_type=EVENT_TEACHER_DAILY_LIMIT,
                milestone=_MILESTONE_SOBRECARGA,
                title=titulo, body=corpo, url=url))
            criadas += 1
    return criadas


def notificar_mudanca_status(reservation, status_anterior, ator_id=None):
    """Aviso ao criador quando a reserva dele é aprovada ou cancelada por
    outra pessoa (rotas approve/cancel e cancelamento de série). Criado no
    momento da ação, dentro da transação da rota — não passa pela varredura
    notify-scan nem pelos silenciamentos do perfil: é sobre a própria reserva
    de quem a criou.

    A ação do próprio criador não gera aviso (ator_id == criador — cobre
    também a exclusão de série feita por quem a criou). Sem criador ativo,
    ninguém recebe. Idempotente pela unicidade de (destinatário, evento,
    reserva, marco): reaprovar a reserva não duplica o aviso de aprovação.
    Retorna quantos avisos criou. Chamar após a mudança de status, com a
    reserva em flush (id preenchido).
    """
    criador = reservation.user
    if criador is None or not criador.is_active_user:
        return 0
    if ator_id is not None and ator_id == criador.id:
        return 0

    if reservation.status == 'approved':
        evento = EVENT_RESERVATION_APPROVED
        titulo = f'Reserva aprovada: {reservation.title}'[:200]
        situacao = 'aprovada'
    elif reservation.status == 'cancelled':
        evento = EVENT_RESERVATION_CANCELLED
        titulo = f'Reserva cancelada: {reservation.title}'[:200]
        situacao = ('cancelada — ainda aguardava aprovação'
                    if status_anterior == 'pending' else 'cancelada')
    else:
        return 0

    sala = reservation.classroom.code if reservation.classroom else '—'
    corpo = (f'{sala} · {reservation.date.strftime("%d/%m/%Y")} · '
             f'{reservation.start_time.strftime("%H:%M")}–'
             f'{reservation.end_time.strftime("%H:%M")}. '
             f'A reserva "{reservation.title}" foi {situacao}.')

    if Notification.query.filter_by(
            user_id=criador.id, event_type=evento,
            reservation_id=reservation.id,
            milestone=_MILESTONE_STATUS).first():
        return 0
    db.session.add(Notification(
        user_id=criador.id, reservation_id=reservation.id,
        event_type=evento, milestone=_MILESTONE_STATUS,
        title=titulo, body=corpo, url=f'/reservations/{reservation.id}'))
    return 1


def notificar_exclusao(reservation, ator_id=None):
    """Aviso ao criador quando a reserva dele é excluída permanentemente
    (hard delete nas rotas de exclusão individual e de série).

    Criado com reservation_id nulo: a FK da notificação apaga em cascata
    junto com a reserva, então este aviso não pode referenciá-la — sala,
    data e horário vão no corpo e o aviso não tem link. Ação do próprio
    criador não gera aviso. Não passa pelos silenciamentos do perfil (é
    sobre a própria reserva de quem a criou). Retorna quantos avisos criou.
    """
    criador = reservation.user
    if criador is None or not criador.is_active_user:
        return 0
    if ator_id is not None and ator_id == criador.id:
        return 0

    sala = reservation.classroom.code if reservation.classroom else '—'
    titulo = f'Reserva excluída: {reservation.title}'[:200]
    corpo = (f'{sala} · {reservation.date.strftime("%d/%m/%Y")} · '
             f'{reservation.start_time.strftime("%H:%M")}–'
             f'{reservation.end_time.strftime("%H:%M")}. '
             f'A reserva "{reservation.title}" foi excluída permanentemente.')

    db.session.add(Notification(
        user_id=criador.id, reservation_id=None,
        event_type=EVENT_RESERVATION_DELETED, milestone=_MILESTONE_STATUS,
        title=titulo, body=corpo, url=None))
    return 1


def varrer_pendentes(agora=None, dry_run=False):
    """Lembretes de reservas pendentes aguardando aprovação.

    Percorre as reservas pending criadas há pelo menos um lembrete (24h/48h
    após a criação, LEMBRETES_PENDENTE_HORAS) e ainda com data futura ou de
    hoje, e avisa os aprovadores da unidade — quem tem a permissão
    reservation:approve e escopo nela. Respeita os silenciamentos do perfil.
    Independente da configuração de notificações da reserva (notify_enabled):
    o lembrete é do fluxo de aprovação, não um aviso de atividade próxima.
    Dispara o lembrete mais recente vencido (janela aberta, mesma regra dos
    marcos de antecedência). Retorna estatísticas para o log do comando."""
    agora = agora or datetime.now()
    stats = {'reservas': 0, 'criadas': 0, 'existentes': 0}

    reservas = Reservation.query.filter(
        Reservation.status == 'pending',
        Reservation.date >= agora.date(),
        Reservation.created_at <= agora - timedelta(hours=LEMBRETES_PENDENTE_HORAS[0][0]),
    ).all()

    for reservation in reservas:
        vencidos = [horas for horas, _ in LEMBRETES_PENDENTE_HORAS
                    if agora >= reservation.created_at + timedelta(hours=horas)]
        if not vencidos:
            continue
        horas = max(vencidos)
        aprovadores = [u for u in User.query.filter(
                           User.is_active_user == True,  # noqa: E712 — comparação de coluna
                           User.escopo_unidade(reservation.unity_id)).all()
                       if u.has_permission('reservation:approve')
                       and not _silenciado(u, reservation)]
        if not aprovadores:
            continue
        stats['reservas'] += 1

        titulo = f'{dict(LEMBRETES_PENDENTE_HORAS)[horas]}: {reservation.title}'[:200]
        sala = reservation.classroom.code if reservation.classroom else '—'
        corpo = (f'{sala} · {reservation.date.strftime("%d/%m/%Y")} · '
                 f'{reservation.start_time.strftime("%H:%M")}–'
                 f'{reservation.end_time.strftime("%H:%M")}. '
                 f'A reserva "{reservation.title}" aguarda aprovação.')
        milestone = f'{horas}h'
        for user in aprovadores:
            # Link para a fila de pendências (quem aprova em geral lê todas);
            # sem permissão de leitura global, aviso sem link — o detalhe da
            # reserva seria 403 para ele.
            url = ('/reservations/all?status=pending'
                   if user.has_permission('reservation:read_all') else None)
            if _notificacao_existente(user.id, reservation.id, milestone,
                                      EVENT_RESERVATION_PENDING_REMINDER):
                stats['existentes'] += 1
                continue
            if dry_run:
                stats['criadas'] += 1
                continue
            db.session.add(Notification(
                user_id=user.id, reservation_id=reservation.id,
                event_type=EVENT_RESERVATION_PENDING_REMINDER,
                milestone=milestone, title=titulo, body=corpo, url=url))
            stats['criadas'] += 1

    if not dry_run:
        db.session.commit()
    return stats
