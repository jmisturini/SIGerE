from flask import Blueprint, render_template, redirect, url_for, request, session, flash
from flask_login import current_user, login_required
from app.models import Reservation, Unity
from app.extensions import db
from app.permissions import require_module, require_permission
from app.unity_context import (current_unity_id, can_switch_unity,
                               switchable_unities, reset_unity_cache)
from datetime import datetime, date, time
import re

bp = Blueprint('main', __name__)


def _sala_order_key(r):
    # Ordem natural do código da sala ("LI9" antes de "LI10"): compara os
    # trechos numéricos como inteiros e os textuais sem diferenciar maiúsculas.
    code = r.classroom.code or ''
    trechos = [(0, int(p)) if p.isdigit() else (1, p.lower())
               for p in re.split(r'(\d+)', code)]
    return (trechos, r.start_time, r.end_time)

# Dashboard route: Shows today's schedule split by Auditoriums and Classrooms
@bp.route('/dashboard')
@login_required
def index():
    today = date.today()
    now = datetime.now()

    # Determine current period based on time of day (Portuguese labels)
    if now.hour < 12:
        period_start, period_end = time(0, 0), time(12, 0)
        current_period = "Manhã"
    elif now.hour < 18:
        period_start, period_end = time(12, 0), time(18, 0)
        current_period = "Tarde"
    else:
        period_start, period_end = time(18, 0), time(23, 59)
        current_period = "Noite"

    # Format today's date in Portuguese manually to avoid server locale issues
    dias_semana = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira', 'Sexta-feira', 'Sábado', 'Domingo']
    meses = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']

    formatted_today = f"{dias_semana[today.weekday()]}, {today.day} de {meses[today.month - 1]}"

    # Fetch approved reservations for the ACTIVE UNIT overlapping the current period
    today_reservations = Reservation.query.filter(
        Reservation.unity_id == current_unity_id(),
        Reservation.date == today,
        Reservation.status == 'approved',
        Reservation.start_time < period_end,
        Reservation.end_time > period_start
    ).order_by(Reservation.start_time).all()

    # Seções montadas a partir das categorias cadastradas (nome, ícone e cor
    # vêm do banco) — nenhuma categoria é citada no código, então cadastrar
    # uma nova (ex: Quadra de Esportes) já a exibe no painel.
    sections_by_cat = {}
    for r in today_reservations:
        cat = r.classroom.category
        if cat is None:  # defensivo: o schema exige category_id na sala
            continue
        sections_by_cat.setdefault(cat, []).append(r)

    for res in sections_by_cat.values():
        res.sort(key=_sala_order_key)

    category_sections = [
        {'category': cat, 'reservations': res}
        for cat, res in sorted(sections_by_cat.items(), key=lambda kv: kv[0].name.lower())
    ]

    # Atalho de aprovação: contagem de pendências atuais da unidade (mesma
    # janela da listagem "Todas as Reservas", aba Atuais) — só quem aprova
    # e enxerga a listagem paga a query; o card não nasce para os demais.
    pendentes_count = None
    if (current_user.has_permission('reservation:approve')
            and current_user.has_permission('reservation:read_all')):
        pendentes_count = Reservation.query.filter(
            Reservation.unity_id == current_unity_id(),
            Reservation.status == 'pending',
            Reservation.date >= today,
        ).count()

    return render_template(
        'index.html',
        category_sections=category_sections,
        current_period=current_period,
        formatted_today=formatted_today, # Pass the pre-formatted string
        pendentes_count=pendentes_count,
    )

# Tela de novidades: histórico de versões da aplicação (app/version.py).
# Pública — o rodapé (com o link) aparece também para quem não está logado.
@bp.route('/changelog')
def changelog():
    from app.version import APP_VERSION, RELEASES
    return render_template('changelog.html',
                           versao_atual=APP_VERSION, releases=RELEASES)

# ── Centrais de seção (hubs) ─────────────────────────────────────────────
# No modelo do Observatório, as seções da sidebar viraram páginas: cada uma
# mostra os antigos itens de menu (e seus submenus) como cards. As rotas dos
# módulos (/reservations/, /relatorios/, /payments/overtime, /vt/) viram
# redirecionamentos para cá — ficam de compatibilidade para links guardados.

@bp.route('/salas-e-reservas')
@login_required
def hub_salas_reservas():
    """Central de Salas e Reservas: card de Salas e, conforme a permissão,
    os caminhos de Reservas e os Relatórios do módulo."""
    return render_template('hubs/salas_reservas.html')

@bp.route('/financeiro-rh')
@login_required
@require_module('finance')
def hub_financeiro_rh():
    """Central Financeiro/RH: Hora Extra, Vale-Transporte, Vale Alimentação
    e Adicional Noturno — cards-portais que abrem os blocos de conteúdos.
    Os caminhos respeitam a permissão de quem acessa; sem nenhum deles,
    volta ao Painel — a sidebar também esconde o item nesse caso."""
    tem_secao = (current_user.has_permission('payment:read')
                 or current_user.has_permission('vt:read')
                 or current_user.has_permission('meal:read')
                 or current_user.has_permission('an:read'))
    if not tem_secao:
        return redirect(url_for('main.index'))
    return render_template('hubs/financeiro_rh.html')

@bp.route('/financeiro')
@login_required
def hub_financeiro_shim():
    """Compatibilidade: a central do Financeiro foi fundida com a de RH."""
    return redirect(url_for('main.hub_financeiro_rh'))

@bp.route('/rh')
@login_required
def hub_rh_shim():
    """Compatibilidade: a central de RH foi fundida com a do Financeiro."""
    return redirect(url_for('main.hub_financeiro_rh'))

@bp.route('/cozinha')
@login_required
@require_permission('kitchen:read')
@require_module('kitchen')
def hub_cozinha():
    """Central da Cozinha: fichas técnicas, preparações e compras."""
    return render_template('hubs/cozinha.html')

# Multi-unidade: alterna a unidade ativa de operação (armazenada na sessão)
@bp.route('/unity/switch', methods=['POST'])
@login_required
def switch_unity():
    if not can_switch_unity():
        flash('Você não tem permissão para alternar de unidade.', 'danger')
        return redirect(url_for('main.index'))

    unity_id = request.form.get('unity_id', type=int)
    unity = db.session.get(Unity, unity_id) if unity_id else None
    if not unity or not unity.is_active:
        flash('Unidade inválida ou desativada.', 'danger')
        return redirect(request.referrer or url_for('main.index'))
    # O seletor só oferece unidades do escopo do usuário (próprias vínculos ou
    # todas para o super-admin) — um POST forjado com unidade estranha é recusado.
    if unity.id not in {u.id for u in switchable_unities()}:
        flash('Você não tem acesso a essa unidade.', 'danger')
        return redirect(request.referrer or url_for('main.index'))

    session['unity_id'] = unity.id
    reset_unity_cache()
    flash(f'Unidade ativa alterada para "{unity.name}".', 'info')
    return redirect(request.referrer or url_for('main.index'))
