"""Varredura de reservas próximas → notificações por destinatário.

Regras do módulo:
- A configuração por unidade (UnityNotificationConfig) define se o módulo está
  ativo, os marcos de antecedência (dias antes da data da reserva) e os
  destinatários: professor designado, criador da reserva, aprovadores da
  unidade (reservation:approve) e grupos personalizados.
- Um marco dispara quando hoje >= data da reserva - marco (janela aberta) e a
  reserva ainda não passou. A notificação é única por (destinatário, reserva,
  marco) — constraint no banco — então atrasos do timer não duplicam nem pulam
  avisos: a varredura seguinte cria o que ficou faltando.
- Só entram reservas approved com data de hoje em diante; pendentes e
  canceladas não avisam.
"""
from datetime import date, timedelta

from app.extensions import db
from app.models import (Reservation, User, UnityNotificationConfig, Notification,
                        EVENT_RESERVATION_UPCOMING)


def parse_lead_days(texto):
    """CSV de dias ('7,1,0') → lista de ints >= 0 sem duplicatas, maior primeiro.

    Tolerante: ignora partes vazias ou não numéricas (a validação do formulário
    avisa o operador, mas a varredura nunca quebra por causa do valor salvo)."""
    valores = []
    for parte in (texto or '').split(','):
        parte = parte.strip()
        if not parte:
            continue
        try:
            n = int(parte)
        except ValueError:
            continue
        if n >= 0 and n not in valores:
            valores.append(n)
    return sorted(valores, reverse=True)


def rotulo_proximidade(dias_restantes):
    """Rótulo humano do quanto falta: 'Hoje', 'Amanhã', 'Em N dias'."""
    if dias_restantes <= 0:
        return 'Hoje'
    if dias_restantes == 1:
        return 'Amanhã'
    return f'Em {dias_restantes} dias'


def destinatarios_da_reserva(reservation, config):
    """Usuários que recebem o aviso da reserva, deduplicados por id.

    Professor e criador entram direto; aprovadores são os usuários ativos do
    escopo da unidade com reservation:approve; grupos trazem os próprios
    membros. Inativos nunca recebem."""
    destino = {}

    def add(user):
        if user is not None and user.is_active_user and user.id not in destino:
            destino[user.id] = user

    if config.notify_teacher:
        add(reservation.teacher)
    if config.notify_creator:
        add(reservation.user)
    if config.notify_approvers:
        candidatos = User.query.filter(
            User.is_active_user == True,  # noqa: E712 — comparação de coluna
            User.escopo_unidade(reservation.unity_id),
        ).all()
        for u in candidatos:
            if u.has_permission('reservation:approve'):
                add(u)
    for grupo in config.groups:
        for u in grupo.members:
            add(u)
    return list(destino.values())


def _notificacao_existente(user_id, reservation_id, milestone):
    return Notification.query.filter_by(
        user_id=user_id, event_type=EVENT_RESERVATION_UPCOMING,
        reservation_id=reservation_id, milestone=milestone,
    ).first()


def varrer_reservas(hoje=None, dry_run=False):
    """Cria as notificações de reservas próximas que ainda não existem.

    Percorre as configurações ativas, acha as reservas approved dentro da
    maior janela de antecedência e, para cada marco já vencido, cria o aviso
    por destinatário (get-or-create pela constraint de unicidade). Com
    dry_run=True nada é gravado — a contagem mostra o que seria criado.
    Retorna estatísticas para o log do comando."""
    hoje = hoje or date.today()
    stats = {'unidades': 0, 'reservas': 0, 'criadas': 0, 'existentes': 0}

    configs = UnityNotificationConfig.query.filter_by(is_enabled=True).all()
    for config in configs:
        leads = parse_lead_days(config.lead_days)
        if not leads:
            continue
        janela = max(leads)
        reservas = Reservation.query.filter(
            Reservation.status == 'approved',
            Reservation.unity_id == config.unity_id,
            Reservation.date >= hoje,
            Reservation.date <= hoje + timedelta(days=janela),
        ).all()
        if not reservas:
            continue
        stats['unidades'] += 1

        for reservation in reservas:
            stats['reservas'] += 1
            destinatarios = destinatarios_da_reserva(reservation, config)
            if not destinatarios:
                continue
            dias_restantes = (reservation.date - hoje).days
            titulo = (f'{rotulo_proximidade(dias_restantes)}: {reservation.title}')
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

            # Marcos vencidos: lead >= dias restantes (janela aberta — se o
            # timer ficar dias parado, os marcos atrasados disparam de uma vez).
            for lead in leads:
                if lead < dias_restantes:
                    continue
                milestone = f'{lead}d'
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
