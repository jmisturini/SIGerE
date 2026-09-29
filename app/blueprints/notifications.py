"""Centro de notificações do usuário logado (o sino do topbar).

As notificações são CRIADAS pela varredura `flask notify-scan` (systemd
timer) — este blueprint é apenas leitura, marcação de lida e limpeza das
lidas, sempre escopado ao próprio usuário (id de outro usuário vira 404,
sem revelar que a notificação existe). O contador de não lidas alimenta
o badge do sino, renderizado no servidor e atualizado por um poll leve.
"""
from datetime import datetime, timezone

from flask import (Blueprint, render_template, redirect, url_for, request,
                   jsonify, flash, abort)
from flask_login import login_required, current_user

from app.extensions import db
from app.models import Notification

bp = Blueprint('notifications', __name__, url_prefix='/notificacoes')

POR_PAGINA = 50


def contar_nao_lidas(user_id):
    """Contagem de notificações não lidas do usuário (badge do sino)."""
    return Notification.query.filter_by(user_id=user_id, read_at=None).count()


@bp.route('/')
@login_required
def lista():
    page = request.args.get('page', 1, type=int)
    paginacao = (Notification.query.filter_by(user_id=current_user.id)
                 .order_by(Notification.created_at.desc(), Notification.id.desc())
                 .paginate(page=page, per_page=POR_PAGINA, error_out=False))
    # Contagem global de lidas (não só da página): controla o botão "Limpar lidas"
    qtde_lidas = (Notification.query
                  .filter(Notification.user_id == current_user.id,
                          Notification.read_at.isnot(None))
                  .count())
    return render_template('notifications/lista.html', paginacao=paginacao,
                           qtde_lidas=qtde_lidas)


@bp.route('/api/nao-lidas')
@login_required
def api_nao_lidas():
    return jsonify({'count': contar_nao_lidas(current_user.id)})


@bp.route('/<int:notification_id>/lida', methods=['POST'])
@login_required
def marcar_lida(notification_id):
    notificacao = db.session.get(Notification, notification_id)
    if notificacao is None or notificacao.user_id != current_user.id:
        abort(404)
    if notificacao.read_at is None:
        notificacao.read_at = datetime.now(timezone.utc)
        db.session.commit()
    return redirect(request.referrer or url_for('notifications.lista'))


@bp.route('/marcar-todas', methods=['POST'])
@login_required
def marcar_todas():
    qtde = (Notification.query
            .filter_by(user_id=current_user.id, read_at=None)
            .update({'read_at': datetime.now(timezone.utc)}))
    db.session.commit()
    flash(f'{qtde} notificação(ões) marcada(s) como lida(s).', 'success'
          if qtde else 'info')
    return redirect(url_for('notifications.lista'))


@bp.route('/limpar-lidas', methods=['POST'])
@login_required
def limpar_lidas():
    qtde = (Notification.query
            .filter(Notification.user_id == current_user.id,
                    Notification.read_at.isnot(None))
            .delete(synchronize_session=False))
    db.session.commit()
    flash(f'{qtde} notificação(ões) lida(s) removida(s).', 'success'
          if qtde else 'info')
    return redirect(url_for('notifications.lista'))
