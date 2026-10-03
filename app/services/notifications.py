"""Varredura de reservas próximas → notificações por destinatário.

Regras do módulo:
- A configuração é por reserva (ReservationNotificationConfig, formulário de
  criar/editar): quem cria a reserva opta por avisar (padrão desativado),
  escolhe os destinatários — usuários individuais e grupos personalizados da
  unidade — e os marcos de antecedência: 24h e/ou 1h antes do início.
- A cada varredura, a reserva dispara o marco mais iminente já vencido
  (agora >= início − antecedência — janela aberta: atraso do timer não pula
  o aviso mais próximo). Marcos vencidos anteriores ficam absorvidos:
  dispará-los tardiamente criaria avisos redundantes. A notificação é única
  por (destinatário, reserva, marco) — constraint no banco — então rodar a
  varredura de novo não duplica.
- Só entram reservas approved que ainda não começaram; pendentes, canceladas
  e em andamento não avisam.
- O usuário pode silenciar os avisos no perfil (UserNotificationPref): todos
  ou apenas os de salas de um tipo (RoomCategory).
- O aviso de sobrecarga de professor (EVENT_TEACHER_DAILY_LIMIT) é criado no
  momento da gravação da reserva e não passa por esta varredura nem pelos
  silenciamentos.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import (Reservation, User, UnityNotificationConfig, Notification,
                        EVENT_RESERVATION_UPCOMING, EVENT_TEACHER_DAILY_LIMIT)
from app.services.scheduling import count_teacher_reservations

# Marco único da notificação de sobrecarga (não é antecedência em horas):
# uma reserva gera no máximo um aviso deste tipo por destinatário.
_MILESTONE_SOBRECARGA = 'diario'

# Marcos de antecedência por horas antes do início da atividade, do maior
# para o menor: o mais iminente vencido (menor horas) é o que dispara.
MARCOS_HORAS = ((24, 'Em 24 horas'), (1, 'Em 1 hora'))


def marcos_da_config(config):
    """Horas habilitadas na configuração da reserva, maior primeiro."""
    horas = []
    if config.notify_24h:
        horas.append(24)
    if config.notify_1h:
        horas.append(1)
    return horas


def rotulo_marco(horas):
    """Rótulo humano do marco: 'Em 24 horas', 'Em 1 hora'."""
    return dict(MARCOS_HORAS).get(horas, f'Em {horas} horas')


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

    Apenas os destinatários explícitos da configuração: usuários individuais
    e membros dos grupos selecionados. Inativos nunca recebem; quem silenciou
    a notificação no perfil (todos ou o tipo de sala desta reserva) é filtrado
    à parte por _silenciado."""
    destino = {}

    def add(user):
        if user is not None and user.is_active_user and user.id not in destino:
            destino[user.id] = user

    for user in config.users:
        add(user)
    for grupo in config.groups:
        for user in grupo.members:
            add(user)
    return list(destino.values())


def _notificacao_existente(user_id, reservation_id, milestone):
    return Notification.query.filter_by(
        user_id=user_id, event_type=EVENT_RESERVATION_UPCOMING,
        reservation_id=reservation_id, milestone=milestone,
    ).first()


def varrer_reservas(agora=None, dry_run=False):
    """Cria as notificações de reservas próximas que ainda não existem.

    Percorre as reservas approved com notificações ativadas e configuração
    salva, calcula os marcos (24h/1h antes do início) já vencidos e, no mais
    iminente, cria o aviso por destinatário (get-or-create pela constraint de
    unicidade), respeitando os silenciamentos do perfil. Com dry_run=True nada
    é gravado — a contagem mostra o que seria criado. Retorna estatísticas
    para o log do comando."""
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
        # Marcos vencidos: agora >= início − antecedência (janela aberta — se
        # o timer ficar horas parado, o aviso mais próximo não se perde).
        # Entre os vencidos dispara só o mais iminente (menor antecedência):
        # os anteriores foram absorvidos e sairiam com conteúdo redundante.
        vencidos = [horas for horas in marcos
                    if agora >= inicio - timedelta(hours=horas)]
        if not vencidos:
            continue
        horas = min(vencidos)
        stats['reservas'] += 1

        destinatarios = [u for u in destinatarios_da_reserva(reservation, config)
                         if not _silenciado(u, reservation)]
        if not destinatarios:
            continue

        titulo = f'{rotulo_marco(horas)}: {reservation.title}'
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

        milestone = f'{horas}h'
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
