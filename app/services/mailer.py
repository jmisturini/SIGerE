"""Espelho por e-mail das notificações: drena a fila gravada pelo sent_at.

A Notification é a fila: toda notificação criada (varredura notify-scan,
sobrecarga de professor, mudança de status) nasce com sent_at nulo e este
módulo — chamado pelo comando `flask notify-email` — envia o e-mail e carimba
sent_at só no sucesso. Falha de SMTP fica pendente e a próxima rodada tenta
de novo; nada é perdido nem duplicado.

Um e-mail por destinatário por rodada (digest): várias notificações do mesmo
usuário vão num único e-mail, em vez de um por aviso. Falhas repetidas
também não travam a fila: cada notificação conta tentativas (send_attempts)
e sai da fila ao atingir MAIL_MAX_ATTEMPTS.

O envio exige MAIL_SMTP_HOST e MAIL_FROM configurados (app/config.py); sem
eles o dreno é no-op — o sistema inteiro funciona sem SMTP, como antes.
O usuário desliga o espelho no perfil (UserNotificationPref.email_enabled);
o sino in-app nunca é afetado por esta configuração.
"""
import logging
import smtplib
from collections import OrderedDict
from datetime import datetime, timezone
from email.message import EmailMessage

from flask import current_app

from app.extensions import db
from app.models import Notification

logger = logging.getLogger(__name__)


def _montar_digest(user, notificacoes, remetente, base_url):
    """EmailMessage de texto puro com as notificações da rodada do usuário:
    uma só → assunto é o título dela; várias → assunto de resumo. Cada bloco
    traz título, corpo e link absoluto (quando a notificação tem deep link),
    com rodapé apontando para a desativação no perfil."""
    msg = EmailMessage()
    if len(notificacoes) == 1:
        msg['Subject'] = notificacoes[0].title
    else:
        msg['Subject'] = f'SIGERE: {len(notificacoes)} notificações novas'
    msg['From'] = remetente
    msg['To'] = user.email

    partes = []
    for n in notificacoes:
        bloco = n.title
        if n.body:
            bloco += f'\n{n.body}'
        if n.url:
            bloco += f'\nVer no SIGERE: {base_url}{n.url}'
        partes.append(bloco)
    rodape = (f'\n\n—\nVocê recebe este e-mail porque é destinatário de '
              f'notificações do SIGERE. Para desativar o envio, acesse '
              f'{base_url}/perfil.')
    msg.set_content('\n\n'.join(partes) + rodape)
    return msg


def drenar_fila_email(limite=200, dry_run=False):
    """Envia os e-mails das notificações pendentes (sent_at nulo), mais
    antigas primeiro, até o limite da rodada — agrupadas por destinatário:
    um e-mail por usuário com todas as notificações dele na rodada. Sem SMTP
    configurado, não faz nada. Falha no envio de um usuário não trava os
    demais; as notificações dele contam uma tentativa e saem da fila ao
    atingir MAIL_MAX_ATTEMPTS. Com dry_run=True nada é enviado nem gravado.
    Retorna estatísticas para o log do comando."""
    stats = {'pendentes': 0, 'emails': 0, 'notificacoes': 0,
             'falhas': 0, 'puladas': 0, 'excedidas': 0}

    host = current_app.config.get('MAIL_SMTP_HOST')
    remetente = current_app.config.get('MAIL_FROM')
    if not host or not remetente:
        stats['puladas'] = -1  # convenção: envio desativado na configuração
        return stats

    base_url = current_app.config.get('BASE_URL', 'http://localhost:5000').rstrip('/')
    porta = current_app.config.get('MAIL_SMTP_PORT', 587)
    usuario = current_app.config.get('MAIL_SMTP_USER')
    senha = current_app.config.get('MAIL_SMTP_PASSWORD')
    starttls = current_app.config.get('MAIL_SMTP_STARTTLS', True)
    tentativas_max = current_app.config.get('MAIL_MAX_ATTEMPTS', 10)

    pendentes = (Notification.query
                 .filter(Notification.sent_at.is_(None),
                         Notification.send_attempts < tentativas_max)
                 .order_by(Notification.created_at.asc(), Notification.id.asc())
                 .limit(limite).all())
    stats['pendentes'] = len(pendentes)
    # Visibilidade: pendências que já estouraram o limite de tentativas —
    # ficam na base (para auditoria) e fora da fila.
    stats['excedidas'] = (Notification.query
                          .filter(Notification.sent_at.is_(None),
                                  Notification.send_attempts >= tentativas_max)
                          .count())
    if not pendentes:
        return stats

    agora = datetime.now(timezone.utc)

    # Agrupa por destinatário preservando a ordem cronológica.
    por_usuario = OrderedDict()
    for notification in pendentes:
        por_usuario.setdefault(notification.user_id, []).append(notification)

    with smtplib.SMTP(host, porta, timeout=30) as smtp:
        if starttls:
            smtp.starttls()
        if usuario and senha:
            smtp.login(usuario, senha)
        for itens in por_usuario.values():
            user = itens[0].user
            pref = user.notification_pref if user is not None else None
            if (user is None or not user.is_active_user
                    or (pref is not None and not pref.email_enabled)
                    or not user.email):
                # Opt-out no perfil (ou conta sem sentido): tira da fila para
                # sempre — carimba sent_at sem enviar, para não reprocessar.
                stats['puladas'] += len(itens)
                if not dry_run:
                    for n in itens:
                        n.sent_at = agora
                continue
            msg = _montar_digest(user, itens, remetente, base_url)
            if dry_run:
                stats['emails'] += 1
                stats['notificacoes'] += len(itens)
                continue
            try:
                smtp.send_message(msg)
            except Exception:
                logger.exception('Falha ao enviar e-mail para %s com %d '
                                 'notificação(ões)', user.email, len(itens))
                stats['falhas'] += len(itens)
                for n in itens:
                    n.send_attempts = (n.send_attempts or 0) + 1
                continue
            for n in itens:
                n.sent_at = agora
            stats['emails'] += 1
            stats['notificacoes'] += len(itens)

    if not dry_run:
        db.session.commit()
    return stats
