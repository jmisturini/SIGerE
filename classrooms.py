from flask import Blueprint, render_template, redirect, url_for, flash, request, Response, make_response
from flask_login import login_required, current_user
from models import Classroom, Reservation, RoomCategory
from forms import ClassroomForm
from extensions import db
from datetime import datetime, date, time
import calendar
from fpdf import FPDF
from permissions import require_permission

bp = Blueprint('classrooms', __name__, url_prefix='/classrooms')

# Helper function to apply filters and return a query
def get_filtered_classrooms(args):
    query = Classroom.query.filter_by(is_active=True)
    
    available_date_str = args.get('available_date')
    available_period = args.get('available_period')
    available_now = args.get('available_now')
    selected_category = args.get('category', '')
    
    if selected_category:
        query = query.filter(Classroom.category_id == selected_category)
        
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

# Route to list classrooms with filters
@bp.route('/')
@login_required
def list_classrooms():
    # Get filtered rooms from helper function
    classrooms = get_filtered_classrooms(request.args)
    
    categories = RoomCategory.query.filter_by(is_active=True).order_by(RoomCategory.name).all()

    
    # Group by floor and sort by room number
    grouped_rooms = {}
    for c in classrooms:
        floor_name = c.floor or 'Outros'
        if floor_name not in grouped_rooms:
            grouped_rooms[floor_name] = []
        grouped_rooms[floor_name].append(c)
        
    # Sort rooms inside each floor by room_number (numerically if possible)
    for floor in grouped_rooms:
        grouped_rooms[floor].sort(key=lambda x: int(x.room_number) if x.room_number and x.room_number.isdigit() else 9999)
        
    # Sort floors logically
    floor_order = {"Térreo": 0, "Ground Floor": 0, "1º Andar": 1, "1st Floor": 1, "2º Andar": 2, "2nd Floor": 2, "3º Andar": 3, "3rd Floor": 3, "4º Andar": 4, "4th Floor": 4, "5º Andar": 5, "5th Floor": 5}
    sorted_floors = dict(sorted(grouped_rooms.items(), key=lambda item: floor_order.get(item[0], 99)))

    # Check filters for alert message
    is_filtered = False
    filter_message = ""
    if request.args.get('available_now'):
        is_filtered = True
        filter_message = "Mostrando salas disponíveis agora."
    elif request.args.get('available_date') and request.args.get('available_period'):
        is_filtered = True
        period_map = {
            'morning': 'Manhã',
            'afternoon': 'Tarde', 
            'evening': 'Noite'
        }
        period_pt = period_map.get(request.args.get('available_period'), request.args.get('available_period'))
        filter_message = f"Mostrando salas disponíveis em <strong>{request.args.get('available_date')}</strong> durante a <strong>{period_pt}</strong>."
    elif request.args.get('category'):
        is_filtered = True
        cat_id = request.args.get('category', type=int)
        cat_obj = RoomCategory.query.get(cat_id) if cat_id else None
        cat_name = cat_obj.name if cat_obj else "Categoria"
        filter_message = f"Mostrando apenas <strong>{cat_name}</strong>."

    return render_template(
        'classrooms/list.html', 
        grouped_rooms=sorted_floors, # Pass the grouped dictionary instead of flat list
        categories=categories,
        is_filtered=is_filtered,
        filter_message=filter_message,
        selected_category=request.args.get('category', '')
    )

# Route to export filtered classrooms to PDF
@bp.route('/export_pdf')
@login_required
@require_permission('system:export')
def export_pdf():
    classrooms = get_filtered_classrooms(request.args)
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, "Relatório de Salas", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    
    pdf.set_font("Helvetica", 'B', 10)
    pdf.set_fill_color(37, 99, 235)
    pdf.set_text_color(255, 255, 255)
    headers = ['Nome', 'Código', 'Categoria', 'Prédio', 'Andar', 'Cap', 'PCs']
    col_widths = [70, 25, 45, 55, 30, 15, 20]
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, align='C', fill=True)
    pdf.ln()
    
    pdf.set_font("Helvetica", '', 9)
    pdf.set_text_color(0, 0, 0)
    for index, c in enumerate(classrooms):
        if index % 2 == 0:
            pdf.set_fill_color(248, 250, 252)
        else:
            pdf.set_fill_color(255, 255, 255)
        row_data = [
            c.name[:35], c.code, c.category.name.title(),
            c.building or 'N/A', c.floor or 'N/A', str(c.capacity),
            str(c.computer_count) if c.category.code == 'computer_lab' else '0'
        ]
        for i, data in enumerate(row_data):
            pdf.cell(col_widths[i], 7, data, border=1, align='C', fill=True)
        pdf.ln()
        
    pdf_output = pdf.output()
    response = make_response(bytes(pdf_output))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = 'attachment; filename=exportacao_salas.pdf'
    return response

# Route to view details of a specific classroom
@bp.route('/<int:classroom_id>')
@login_required
def detail(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)
    today = date.today()
    upcoming = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= today,
        Reservation.status.in_(['approved', 'pending'])
    ).order_by(Reservation.date, Reservation.start_time).all()
    return render_template('classrooms/detail.html', classroom=classroom, upcoming=upcoming)

# Route to view monthly availability of a classroom
@bp.route('/<int:classroom_id>/availability')
@login_required
def availability(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)
    req_year = request.args.get('year', type=int)
    req_month = request.args.get('month', type=int)
    today = date.today()
    if req_year and req_month:
        year, month = req_year, req_month
    else:
        year, month = today.year, today.month

    first_day = date(year, month, 1)
    last_day_num = calendar.monthrange(year, month)[1]
    last_day = date(year, month, last_day_num)

    month_reservations = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= first_day,
        Reservation.date <= last_day,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()

    reservations_by_day = {}
    for r in month_reservations:
        if r.date.day not in reservations_by_day:
            reservations_by_day[r.date.day] = []
        reservations_by_day[r.date.day].append(r)

    cal = calendar.Calendar(firstweekday=6)
    month_days = cal.monthdayscalendar(year, month)

    if month == 1:
        prev_month, prev_year = 12, year - 1
        next_month, next_year = 2, year      # CORRIGIDO: Fevereiro é do mesmo ano
    elif month == 12:
        prev_month, prev_year = 11, year
        next_month, next_year = 1, year + 1  # Janeiro é do ano seguinte
    else:
        prev_month, prev_year = month - 1, year
        next_month, next_year = month + 1, year

    return render_template(
        'classrooms/availability.html', classroom=classroom, year=year, month=month,
        month_name=calendar.month_name[month], month_days=month_days,
        reservations_by_day=reservations_by_day, today=today,
        prev_year=prev_year, prev_month=prev_month, next_year=next_year, next_month=next_month
    )

# Route to export a specific classroom's monthly reservations to PDF
@bp.route('/<int:classroom_id>/export_availability')
@login_required
@require_permission('system:export')
def export_availability(classroom_id):
    classroom = Classroom.query.get_or_404(classroom_id)
    
    req_year = request.args.get('year', type=int)
    req_month = request.args.get('month', type=int)
    today = date.today()
    
    if req_year and req_month:
        year, month = req_year, req_month
    else:
        year, month = today.year, today.month

    first_day = date(year, month, 1)
    last_day_num = calendar.monthrange(year, month)[1]
    last_day = date(year, month, last_day_num)

    # Fetch approved reservations for this period
    reservations = Reservation.query.filter(
        Reservation.classroom_id == classroom_id,
        Reservation.date >= first_day,
        Reservation.date <= last_day,
        Reservation.status == 'approved'
    ).order_by(Reservation.date, Reservation.start_time).all()

    # Generate PDF (Landscape, mm, A4)
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    
    # Get month name in Portuguese
    meses = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']
    month_name = meses[month - 1]
    
    # Title
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, f"Reservas - {classroom.name} ({classroom.code})", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 8, f"{month_name} de {year}", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(5)
    
    # Table Header
    pdf.set_font("Helvetica", 'B', 10)
    pdf.set_fill_color(37, 99, 235) # Bootstrap Primary Blue
    pdf.set_text_color(255, 255, 255)
    
    headers = ['Data', 'Início', 'Fim', 'Título', 'Curso', 'Disciplina', 'Professor']
    col_widths = [35, 15, 15, 45, 50, 50, 50]
    
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, align='C', fill=True)
    pdf.ln()
    
    # Table Rows
    pdf.set_font("Helvetica", '', 9)
    
    # CORREÇÃO: Definir as variáveis de data e hora atuais
    today = date.today()
    now = datetime.now()
    
    for index, r in enumerate(reservations):
        # Check if reservation has already passed
        is_past = False
        if r.date < today:
            is_past = True
        elif r.date == today and r.end_time < now.time():
            is_past = True

        # Set alternating row background colors
        if index % 2 == 0:
            pdf.set_fill_color(248, 250, 252)
        else:
            pdf.set_fill_color(255, 255, 255)
            
        # Set text color (gray if past, black if upcoming)
        if is_past:
            pdf.set_text_color(150, 150, 150)
        else:
            pdf.set_text_color(0, 0, 0)
            
        row_data = [
            r.date.strftime('%d/%m/%Y'),
            r.start_time.strftime('%H:%M'),
            r.end_time.strftime('%H:%M'),
            r.title[:40],
            (r.course.name if r.course else 'N/A')[:30],
            (r.subject.name if r.subject else 'N/A')[:30],
            (r.teacher.full_name if r.teacher else 'N/A')[:30]
        ]
        
        # Record start position to draw strikethrough line later if needed
        start_x = pdf.get_x()
        start_y = pdf.get_y()
        
        for i, data in enumerate(row_data):
            pdf.cell(col_widths[i], 7, data, border=1, align='C', fill=True)
        
        # Draw strikethrough line if the reservation has passed
        if is_past:
            pdf.set_draw_color(150, 150, 150)
            # Draw a line in the middle of the row height (7mm / 2 = 3.5mm)
            pdf.line(start_x, start_y + 3.5, start_x + sum(col_widths), start_y + 3.5)
            
        pdf.ln()
        
    # Output PDF
    pdf_output = pdf.output()
    # CORREÇÃO: Converter para bytes explicitamente (resolve o erro do bytearray)
    response = make_response(bytes(pdf_output))
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=reservas_{classroom.code}_{month}-{year}.pdf'
    return response