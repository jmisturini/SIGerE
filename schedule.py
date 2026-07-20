from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required
from models import Reservation
from datetime import datetime

bp = Blueprint('schedule', __name__, url_prefix='/calendar')

@bp.route('/')
def view():
    return render_template('calendar.html')

@bp.route('/api/events')
def events():
    start_str = request.args.get('start')
    end_str = request.args.get('end')

    query = Reservation.query.filter_by(status='approved')

    if start_str and end_str:
        try:
            start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
            query = query.filter(
                Reservation.date >= start_date,
                Reservation.date <= end_date
            )
        except ValueError:
            pass

    reservations = query.all()
    events = []
    for r in reservations:
        start_dt = datetime.combine(r.date, r.start_time)
        end_dt = datetime.combine(r.date, r.end_time)
        
        events.append({
            'id': r.id,
            'title': f"{r.classroom.code} - {r.title}",
            'start': start_dt.isoformat(),
            'end': end_dt.isoformat(),
            'url': f"/reservations/{r.id}",
            'backgroundColor': '#2563eb', 
            'borderColor': '#2563eb'
        })
    
    return jsonify(events)