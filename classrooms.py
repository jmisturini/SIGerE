from flask import Blueprint, render_template, redirect, url_for, flash, request, Response
from flask_login import login_required, current_user
from models import Classroom, Reservation
from forms import ClassroomForm
from extensions import db
from datetime import datetime, date, time
import csv
import io
import calendar

bp = Blueprint('classrooms', __name__, url_prefix='/classrooms')


from flask import Blueprint, render_template, redirect, url_for, flash, request, Response, make_response
from flask_login import login_required, current_user
from models import Classroom, Reservation
from forms import ClassroomForm
from extensions import db
from datetime import datetime, date, time
import csv
import io
from fpdf import FPDF

bp = Blueprint('classrooms', __name__, url_prefix='/classrooms')

def get_filtered_classrooms(args):
    """Helper function to apply filters and return a query."""
    query = Classroom.query.filter_by(is_active=True)
    
    available_date_str = args.get('available_date')
    available_period = args.get('available_period')
    available_now = args.get('available_now')
    selected_category = args.get('category', '')
    
    if selected_category:
        query = query.filter(Classroom.category == selected_category)
        
    if available_now:
        now = datetime.now()
        today = date.today()
        current_time = now.time()
        occupied_ids = db.session.query(Reservation.classroom_id).filter(
            Reservation.date == today,
            Reservation.status == 'approved',
            Reservation.start_time <= current_time,
            Reservation.end_time > current_time
        ).distinct().all()
        occupied_flat = [r[0] for r in occupied_ids]
        if occupied_flat:
            query = query.filter(~Classroom.id.in_(occupied_flat))
            
    elif available_date_str and available_period:
        try:
            filter_date = datetime.strptime(available_date_str, '%Y-%m-%d').date()
        except ValueError:
            filter_date = date.today()
            
        if available_period == 'morning':
            p_start, p_end = time(0, 0), time(12, 0)
        elif available_period == 'afternoon':
            p_start, p_end = time(12, 0), time(18, 0)
        else: 
            p_start, p_end = time(18, 0), time(23, 59)
            
        occupied_ids = db.session.query(Reservation.classroom_id).filter(
            Reservation.date == filter_date,
            Reservation.status == 'approved',
            Reservation.start_time < p_end,
            Reservation.end_time > p_start
        ).distinct().all()
        occupied_flat = [r[0] for r in occupied_ids]
        if occupied_flat:
            query = query.filter(~Classroom.id.in_(occupied_flat))

    return query.order_by(Classroom.building, Classroom.code).all()


@bp.route('/')
@login_required
def list_classrooms():
    classrooms = get_filtered_classrooms(request.args)
    
    is_filtered = False
    filter_message = ""
    if request.args.get('available_now'):
        is_filtered = True
        filter_message = "Showing rooms available right now."
    elif request.args.get('available_date') and request.args.get('available_period'):
        is_filtered = True
        filter_message = f"Showing rooms available on <strong>{request.args.get('available_date')}</strong> during the <strong class='text-capitalize'>{request.args.get('available_period')}</strong>."
    elif request.args.get('category'):
        is_filtered = True
        filter_message = f"Showing only <strong class='text-capitalize'>{request.args.get('category').replace('_', ' ')}</strong>."

    return render_template(
        'classrooms/list.html', 
        classrooms=classrooms,
        is_filtered=is_filtered,
        filter_message=filter_message,
        selected_category=request.args.get('category', '')
    )


@bp.route('/export')
@login_required
def export_classrooms():
    classrooms = get_filtered_classrooms(request.args)
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Code', 'Room Number', 'Category', 'Building', 'Floor', 'Capacity', 'Computers', 'Status'])
    
    for c in classrooms:
        writer.writerow([
            c.name, c.code, c.room_number or 'N/A',
            c.category.replace('_', ' ').title(),
            c.building or 'N/A', c.floor or 'N/A', c.capacity,
            c.computer_count if c.category == 'computer_lab' else 0,
            'Active' if c.is_active else 'Inactive'
        ])
    
    output.seek(0)
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=classrooms_export.csv'}
    )

@bp.route('/export_pdf')
@login_required
def export_pdf():
    classrooms = get_filtered_classrooms(request.args)
    
    # Create PDF object (Landscape, A4)
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Title
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, "Classroom Export Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    
    # Table Header
    pdf.set_font("Helvetica", 'B', 10)
    pdf.set_fill_color(37, 99, 235) # Bootstrap Primary Blue
    pdf.set_text_color(255, 255, 255)
    
    headers = ['Name', 'Code', 'Category', 'Building', 'Floor', 'Cap', 'PCs']
    col_widths = [70, 25, 45, 55, 30, 15, 20]
    
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, align='C', fill=True)
    pdf.ln()
    
    # Table Rows
    pdf.set_font("Helvetica", '', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(248, 250, 252) # Light gray for alternating rows
    
    for index, c in enumerate(classrooms):
        # Alternate row colors
        if index % 2 == 0:
            pdf.set_fill_color(248, 250, 252)
        else:
            pdf.set_fill_color(255, 255, 255)
            
        row_data = [
            c.name[:35], # Truncate long names
            c.code,
            c.category.replace('_', ' ').title(),
            c.building or 'N/A',
            c.floor or 'N/A',
            str(c.capacity),
            str(c.computer_count) if c.category == 'computer_lab' else '0'
        ]
        
        for i, data in enumerate(row_data):
            pdf.cell(col_widths[i], 7, data, border=1, align='C', fill=True)
        pdf.ln()
        
    # Output PDF
    pdf_output = pdf.output()
    response = make_response(bytes(pdf_output))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=classrooms_export.pdf'
    return response

@bp.route('/<int:classroom_id>')
@login_required
def detail(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)
    today = date.today()
    upcoming = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= today,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()
    return render_template(
        'classrooms/detail.html', classroom=classroom, upcoming=upcoming
    )
    
@bp.route('/<int:classroom_id>/availability')
@login_required
def availability(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)
    
    # Get requested month/year from query params, or default to current
    req_year = request.args.get('year', type=int)
    req_month = request.args.get('month', type=int)
    
    today = date.today()
    if req_year and req_month:
        year, month = req_year, req_month
    else:
        year, month = today.year, today.month

    # Calculate first and last day of the month
    first_day = date(year, month, 1)
    last_day_num = calendar.monthrange(year, month)[1]
    last_day = date(year, month, last_day_num)

    # Fetch all approved reservations for this classroom in this month
    month_reservations = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= first_day,
        Reservation.date <= last_day,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()

    # Group reservations by the day of the month
    reservations_by_day = {}
    for r in month_reservations:
        if r.date.day not in reservations_by_day:
            reservations_by_day[r.date.day] = []
        reservations_by_day[r.date.day].append(r)

    # Get calendar matrix (list of weeks, each week is a list of days)
    # firstweekday=6 means Sunday is the first day of the week (0=Monday)
    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)

    # Calculate previous and next month for navigation
    if month == 1:
        prev_month, prev_year = 12, year - 1
        next_month, next_year = 2, year + 1
    elif month == 12:
        prev_month, prev_year = 11, year
        next_month, next_year = 1, year + 1
    else:
        prev_month, prev_year = month - 1, year
        next_month, next_year = month + 1, year

    return render_template(
        'classrooms/availability.html',
        classroom=classroom,
        year=year,
        month=month,
        month_name=calendar.month_name[month],
        month_days=month_days,
        reservations_by_day=reservations_by_day,
        today=today,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month
    )