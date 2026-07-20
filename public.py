from flask import Blueprint, render_template, request
from models import User, Classroom
from flask import redirect, url_for
from flask_login import current_user

bp = Blueprint('public', __name__)

@bp.route('/')
def home():
    # If the user is already logged in, redirect them to their dashboard
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    return render_template('home.html')

@bp.route('/search')
def search():
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'classroom')
    
    results_rooms = []
    results_teachers = []
    
    if query:
        if search_type == 'classroom':
            # Only search ACTIVE classrooms
            results_rooms = Classroom.query.filter(
                Classroom.is_active == True,
                (Classroom.name.ilike(f'%{query}%') | Classroom.code.ilike(f'%{query}%'))
            ).order_by(Classroom.code).all()
            
        elif search_type == 'teacher':
            # Only search ACTIVE teachers
            results_teachers = User.query.filter(
                User.is_active_user == True,
                User.profile_type == 'teacher',
                User.full_name.ilike(f'%{query}%')
            ).order_by(User.full_name).all()

    return render_template(
        'search.html', 
        query=query, 
        search_type=search_type, 
        results_rooms=results_rooms, 
        results_teachers=results_teachers
    )

