from flask import Blueprint, render_template
from models import Classroom, Reservation
from datetime import date, time, datetime

bp = Blueprint('totem', __name__, url_prefix='/totem')

@bp.route('/')
def display():
    today = date.today()
    now = datetime.now()

    # Determine current period based on time of day
    if now.hour < 12:
        current_key = 'morning'
        period_start, period_end = time(0, 0), time(12, 0)
        period_label = "Morning"
        period_icon = "bi-sunrise"
    elif now.hour < 18:
        current_key = 'afternoon'
        period_start, period_end = time(12, 0), time(18, 0)
        period_label = "Afternoon"
        period_icon = "bi-sun"
    else:
        current_key = 'night'
        period_start, period_end = time(18, 0), time(23, 59)
        period_label = "Night"
        period_icon = "bi-moon-stars"

    # Get all active rooms
    rooms = Classroom.query.filter_by(is_active=True).order_by(Classroom.code).all()
    
    # Get all approved reservations for today
    reservations = Reservation.query.filter(
        Reservation.date == today,
        Reservation.status == 'approved'
    ).all()

    # Data Structure: { 'Floor 1': [ {room, events}, ... ], ... }
    data = {}

    for room in rooms:
        floor_name = room.floor or 'General Floor'
        
        # Find reservations for this room today
        room_res = [r for r in reservations if r.classroom_id == room.id]
        
        # Find events that overlap with the CURRENT period
        overlapping = []
        for r in room_res:
            if r.start_time < period_end and r.end_time > period_start:
                overlapping.append(r)
        
        # ONLY add the room if it has overlapping events (is occupied)
        if overlapping:
            if floor_name not in data:
                data[floor_name] = []
                
            data[floor_name].append({
                'room': room,
                'events': overlapping
            })

    # Sort floors alphabetically
    sorted_data = dict(sorted(data.items()))

    return render_template(
        'totem.html', 
        data=sorted_data, 
        period_label=period_label,
        period_icon=period_icon
    )