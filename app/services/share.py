"""Textos amigáveis para compartilhar uma reserva (botão "Compartilhar" no
detalhe). O servidor só monta as mensagens — o envio acontece no navegador:
mailto: abre o programa de e-mail do usuário e wa.me abre o WhatsApp, então
não há SMTP, credenciais nem nova dependência.

Conteúdo enxuto, definido com o usuário: sala, curso, disciplina, professor,
data e hora juntos na mesma linha e descrição/finalidade.
"""

# Nomes de dia da semana em pt-BR: strftime('%A') depende do locale do
# servidor, que pode não ter pt_BR instalado.
WEEKDAYS_PTBR = ('segunda-feira', 'terça-feira', 'quarta-feira', 'quinta-feira',
                 'sexta-feira', 'sábado', 'domingo')


def format_reservation_date(day):
    """Data por extenso amigável, ex: 'sexta-feira, 11/09/2026'."""
    return f'{WEEKDAYS_PTBR[day.weekday()]}, {day.strftime("%d/%m/%Y")}'


def _reservation_fields(reservation):
    """Pares (rótulo, valor) da mensagem — campos vazios ficam fora."""
    fields = [('Sala', f'{reservation.classroom.code} - {reservation.classroom.name}')]
    if reservation.course:
        fields.append(('Curso', reservation.course.name))
    if reservation.subject:
        fields.append(('Disciplina', reservation.subject.name))
    if reservation.teacher:
        fields.append(('Professor', reservation.teacher.full_name))
    fields.append(('Data e hora',
                   f'{format_reservation_date(reservation.date)}, '
                   f'das {reservation.start_time.strftime("%H:%M")} '
                   f'às {reservation.end_time.strftime("%H:%M")}'))
    return fields


def build_email_subject(reservation):
    """Assunto curto do e-mail, ex: 'Reserva de sala: Aula — 11/09/2026 14:00'."""
    return (f'Reserva de sala: {reservation.title} — '
            f'{reservation.date.strftime("%d/%m/%Y")} '
            f'{reservation.start_time.strftime("%H:%M")}')


def build_reservation_share_texts(reservation):
    """Mensagens prontas para compartilhar a reserva.

    Retorna {'email': {'subject', 'body'}, 'whatsapp': {'text'}}: o e-mail é
    texto puro organizado; o WhatsApp usa a formatação dele (*negrito*) e
    emojis. A descrição/finalidade fecha a mensagem quando existe.
    """
    fields = _reservation_fields(reservation)
    description = (reservation.description or '').strip()

    email_lines = ['Olá!', '', 'Segue os detalhes da reserva de sala:', '']
    email_lines += [f'{label}: {value}' for label, value in fields]
    if description:
        email_lines += ['', f'Descrição/Finalidade: {description}']
    email_lines += ['', '--', 'Mensagem enviada pelo SIGerE.']

    whatsapp_lines = ['📅 *Reserva de sala*', '']
    whatsapp_lines += [f'*{label}:* {value}' for label, value in fields]
    if description:
        whatsapp_lines += ['', f'📝 {description}']
    whatsapp_lines += ['', '_Mensagem enviada pelo SIGerE_ 🕒']

    return {
        'email': {'subject': build_email_subject(reservation),
                  'body': '\n'.join(email_lines)},
        'whatsapp': {'text': '\n'.join(whatsapp_lines)},
    }
