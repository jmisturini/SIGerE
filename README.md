# SIGERE 🏫

A comprehensive, web-based reservation system designed for educational institutions to manage classrooms, auditoriums, laboratories, and teacher schedules efficiently. Built with Flask, it features a role-based access control system, a public kiosk/totem display for hallway TVs, a full calendar view, and automated schedule restriction enforcement.

---

## ✨ Key Features & Capabilities

### 📅 Reservation Management

- **Smart Conflict Detection:** Automatically blocks double-booking of rooms.
- **Teacher Overlap Handling:** If a teacher is already booked in another room, the reservation is created as Pending and requires Admin approval.
- **Schedule Restrictions:** Hard-blocks reservations on Sundays and Holidays. On Saturdays, bookings are restricted to Morning and Afternoon only.
- **Auto-Approval:** Reservations are approved instantly if there are no teacher conflicts.
- **Admin Tools:** Admins can edit, cancel, or permanently delete any reservation.

### 🏛️ Room & Category Management

- **Room Categories:** Standard Classrooms, Auditoriums, Computer Laboratories, Health Laboratories, and Kitchens.
- **Dynamic Attributes:** Computer labs prompt for a "Number of Computers" field.
- **Availability Filters:** Users can filter rooms by a specific date/period or check a box to "Show only rooms available RIGHT NOW".

### 👥 User & Role Management (Admin Panel)

- **Profile Types:** Separate registration forms for Teachers and Employees.
- **Dual-Role Support:** Employees can be flagged as "Also a Teacher," allowing them to be assigned to reservations while retaining employee attributes (sector, function).
- **Access Groups:**
  - **Admin:** Full system access, user/room/course/holiday management.
  - **Room Booker:** Can create and manage their own reservations.
  - **Viewer:** Read-only access to schedules and rooms.
- **Security:** Forced password change on first login or after an admin resets a password.
- **User Search & Filters:** Filter users by name or profile type.

### 📆 Academic Structure

- Link reservations to specific Courses and Subjects.
- Admin CRUD interfaces for managing the academic curriculum.

### 🖥️ Public Kiosk / Totem Display (`/totem`)

- **TV-Friendly UI:** Clean, large-text interface designed for hallway displays.
- **Dynamic Theming:** Automatically switches to a dark theme at night and a light theme during the day.
- **Live Data:** Displays current time, date, and local weather (via Open-Meteo API).
- **Floor Grouping:** Groups occupied rooms by floor for the current time period (Morning, Afternoon, Night).
- **Occupied Only:** Only displays rooms that are actively in use, hiding empty rooms to reduce clutter.

### 🗓️ Interactive Calendar (`/calendar`)

- FullCalendar integration with Day, Week, and Month views.
- Color-coded events that adapt to the system's Light/Dark mode toggle.
- Click-and-view event details.

### 🌐 Public Portal

- **Landing Page:** Public home page with links to Login, View Calendar, and Search.
- **Search Page:** Public search tool to find active classrooms or teachers by name/code.

### 🎨 UI/UX

- **Dark/Light Mode:** System-wide theme toggle with localStorage persistence (no flashing on reload).
- **Responsive Design:** Built with Bootstrap 5, fully functional on mobile, tablet, and desktop.
- **Modern Styling:** Clean, card-based layout using custom CSS variables.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.8+
- pip

### Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/your-username/classroom-reservation.git
   cd classroom-reservation
   ```

2. **Create and activate a virtual environment**

   ```bash
   python -m venv venv
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

   *(Note: Ensure `requests` is in your `requirements.txt` for the Weather and Holiday APIs).*

4. **Run the application**

   ```bash
   python app.py
   ```

5. **Access the app**

   Open your browser and navigate to `http://localhost:5000`

---

## 👤 Demo Accounts (Auto-Seeded)

On the first run, the database will automatically populate with 10 rooms, 30 users (teachers/employees), and 20 random reservations so you can see the system in action immediately.

| Role / Profile | Username | Password | Capabilities |
|---|---|---|---|
| Administrator | `admin` | `admin123` | Full access, Admin Panel, manage all reservations |
| Teacher | `teacher1` | `teacher123` | Create/manage own reservations |
| Employee | `employee1` | `employee123` | View-only access (unless promoted to Room Booker) |

> **Note:** Due to the "Force Password Change" feature, you may be prompted to change these passwords on your first login. To disable this for testing, set `force_password_change=False` in the `seed_data()` function in `app.py`.

---

## 🛠️ Tech Stack

- **Backend:** Python, Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF
- **Database:** SQLite (Default, easily swappable to PostgreSQL/MySQL)
- **Frontend:** Bootstrap 5, Bootstrap Icons, Jinja2 Templates
- **JavaScript Libraries:** FullCalendar (Calendar UI)
- **External APIs:**
  - [Open-Meteo](https://open-meteo.com/) (Weather widget for Totem)
  - [Nager.Date](https://date.nager.at/) (Public Holiday API import)

---

## 📁 Project Structure

```text
classroom_reservation/
├── app.py                 # App factory, DB seeding, before_request hooks
├── config.py              # Flask configuration
├── extensions.py          # SQLAlchemy & LoginManager instances
├── models.py              # Database models (User, Classroom, Reservation, etc.)
├── forms.py               # WTForms definitions
├── requirements.txt
├── admin.py               # Admin blueprint (Users, Rooms, Courses, Holidays)
├── auth.py                # Auth blueprint (Login, Logout, Change Password)
├── classrooms.py          # Classrooms blueprint (List, Details, Availability)
├── reservations.py        # Reservations blueprint (Create, Edit, Approve)
├── schedule.py            # Calendar blueprint (JSON API for FullCalendar)
├── public.py              # Public blueprint (Home, Search)
├── totem.py               # Totem blueprint (Kiosk display)
├── static/
│   └── css/style.css      # Global styles, Dark/Light theme variables
└── templates/             # Jinja2 HTML templates
    ├── base.html          # Main layout, Navbar, Theme Toggle
    ├── admin/             # Admin panel templates
    ├── auth/              # Login & Password templates
    ├── classrooms/        # Room list & monthly calendar grid
    ├── reservations/      # Create, Edit, Detail, Pending Conflict warning
    ├── errors/            # 403, 404, 500 pages
    ├── calendar.html      # FullCalendar integration
    ├── home.html          # Public landing page
    ├── totem.html         # TV Kiosk display
    └── search.html        # Public search tool
```

---

## 🌍 API Integrations Setup

- **Weather (Totem):** The Totem page fetches weather based on latitude/longitude. To set your school's location, edit the `const lat` and `const lon` variables in `templates/totem.html`.
- **Holidays:** Go to Admin Panel → Manage Holidays → Import from API. Enter your Country Code (e.g., US, BR, DE) and Year, and the system will automatically fetch and block public holidays.

---

## 📝 License

This project is open-source and available for educational and internal use.
