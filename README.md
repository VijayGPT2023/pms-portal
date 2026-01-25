# PMS Portal - Officer Performance & Revenue Sharing System

A full-stack web portal for officer-wise performance data entry and revenue sharing management.

## Technology Stack

- **Backend**: Python FastAPI
- **Database**: SQLite
- **Frontend**: Jinja2 templates with vanilla HTML/CSS/JavaScript
- **Authentication**: Session-based with bcrypt password hashing

## Features

### 1. Authentication
- Officer login via email and password
- Session-based authentication with secure cookies
- Passwords are stored hashed (bcrypt)
- Initial passwords generated and saved to CSV for admin distribution

### 2. Assignment Management
- Two types: **Assignment** (consultancy/projects) and **Training**
- Dashboard showing all assignments with filters
- Fill/update assignment details
- Assignment-specific forms based on type

### 3. Revenue Sharing
- Officer-wise revenue share allocation
- Percentage validation (must sum to 100%)
- Auto-calculation of share amounts
- Long-format storage (one row per officer-assignment)

### 4. MIS / Analytics
- Office-wise revenue aggregation with top/bottom highlighting
- Domain-wise revenue breakdown
- Officer-wise revenue share ranking
- Filters by financial year, date range, office, and domain
- Detailed drill-down views for offices and officers

## Project Structure

```
PMS_Starter/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Configuration settings
│   ├── database.py          # Database connection and initialization
│   ├── auth.py              # Authentication utilities
│   ├── dependencies.py      # Route dependencies
│   ├── models/
│   │   └── __init__.py
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── auth_routes.py       # Login/logout routes
│   │   ├── dashboard_routes.py  # Main dashboard
│   │   ├── assignment_routes.py # Assignment CRUD
│   │   ├── revenue_routes.py    # Revenue share management
│   │   └── mis_routes.py        # MIS analytics
│   ├── templates/               # Jinja2 HTML templates
│   │   ├── base.html
│   │   ├── login.html
│   │   ├── dashboard.html
│   │   ├── select_type.html
│   │   ├── assignment_form.html
│   │   ├── training_form.html
│   │   ├── assignment_view.html
│   │   ├── revenue_share_form.html
│   │   ├── mis_dashboard.html
│   │   ├── office_detail.html
│   │   ├── officer_detail.html
│   │   └── error.html
│   └── static/
│       └── css/
│           └── style.css
├── scripts/
│   ├── __init__.py
│   ├── import_officers.py       # Import officers from Excel
│   ├── generate_dummy_data.py   # Generate dummy assignments
│   └── setup_all.py             # Master setup script
├── Officer Data.xlsx            # Officer data file (input)
├── Revenue Sharing Detailed MIS-1.xlsx  # MIS reference (input)
├── requirements.txt
├── run.py                       # Server startup script
└── README.md
```

## Installation

### Prerequisites
- Python 3.9 or higher
- pip (Python package manager)

### Step 1: Install Dependencies

```bash
cd PMS_Starter
pip install -r requirements.txt
```

### Step 2: Initialize Database and Import Data

Run the complete setup script:

```bash
python scripts/setup_all.py
```

This will:
1. Create the SQLite database with all tables
2. Import officers from `Officer Data.xlsx`
3. Generate initial passwords (saved to `initial_passwords.csv`)
4. Generate ~200 dummy assignments (10 per office)

Alternatively, run each step individually:

```bash
# Initialize database and import officers
python scripts/import_officers.py

# Generate dummy assignments
python scripts/generate_dummy_data.py
```

### Step 3: Start the Server

```bash
python run.py
```

Or using uvicorn directly:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Step 4: Access the Portal

Open your browser and navigate to:
```
http://127.0.0.1:8000
```

## Login Credentials

After running the setup, login credentials are saved in `initial_passwords.csv`:

| Field | Description |
|-------|-------------|
| officer_id | Employee ID from Excel |
| name | Officer name |
| email | Email address (used for login) |
| office_id | Office code |
| password | Initial password (random, 12 characters) |

Example login:
- Email: `us.prasad@npcindia.gov.in`
- Password: (check initial_passwords.csv)

## Database Schema

### Tables

1. **offices**
   - `id` (PK), `office_id` (unique), `office_name`

2. **officers**
   - `id` (PK), `officer_id` (unique), `name`, `email` (unique)
   - `designation`, `discipline`, `office_id` (FK)
   - `admin_role_id`, `password_hash`, `is_active`

3. **assignments**
   - `id` (PK), `assignment_no` (unique), `type` (ASSIGNMENT/TRAINING)
   - Common: `title`, `client`, `domain`, `office_id`, `status`
   - Assignment fields: `tor_scope`, `work_order_date`, `start_date`, `target_date`, `team_leader_officer_id`
   - Training fields: `venue`, `duration_*`, `type_of_participants`, `faculty1/2_officer_id`
   - Financial: `gross_value`, `invoice_amount`, `amount_received`, `total_revenue`

4. **revenue_shares**
   - `id` (PK), `assignment_id` (FK), `officer_id` (FK)
   - `share_percent`, `share_amount`

5. **sessions**
   - For authentication session management

## Usage Guide

### Dashboard
- View all assignments for your office (or all offices with filter)
- Filter by type, status, office
- See details status and revenue share status
- Quick action buttons for filling/updating details

### Assignment Details
- Click "Fill Details" to enter assignment/training information
- Select type (Assignment or Training) if not already set
- Fill in appropriate form fields
- Save to update database

### Revenue Sharing
- Click "Fill Share" or "Update" to allocate revenue
- Select officers and enter percentage shares
- System validates that total = 100%
- Share amounts calculated automatically

### MIS Analytics
- View aggregated data by office, domain, officer
- Top 3 / Bottom 3 highlighting for offices
- Top 10 / Bottom 10 for officers
- Filter by financial year, dates, office, domain
- Click on office/officer names for detailed views

## Configuration

Edit `app/config.py` to customize:

```python
# Security (change in production!)
SECRET_KEY = "your-secret-key-here"

# Session duration
SESSION_MAX_AGE = 60 * 60 * 24  # 24 hours

# File paths
OFFICER_DATA_FILE = BASE_DIR / "Officer Data.xlsx"
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/login` | GET/POST | Login page and authentication |
| `/logout` | GET | Logout and clear session |
| `/dashboard` | GET | Main assignment list |
| `/assignment/edit/{id}` | GET/POST | Edit assignment details |
| `/assignment/view/{id}` | GET | View assignment details |
| `/revenue/edit/{id}` | GET/POST | Edit revenue shares |
| `/mis` | GET | MIS analytics dashboard |
| `/mis/office/{id}` | GET | Office detail view |
| `/mis/officer/{id}` | GET | Officer detail view |

## Future Enhancements

- [ ] Tally data import functionality
- [ ] Role-based access control (Admin vs. Officer)
- [ ] Password reset functionality
- [ ] Export reports to Excel/PDF
- [ ] Email notifications
- [ ] Audit logging
- [ ] Multi-factor authentication

## Troubleshooting

### "No module named 'app'"
Make sure you're running from the project root directory:
```bash
cd PMS_Starter
python run.py
```

### "Database locked"
Stop any other processes using the database and try again.

### "Import error for officers"
Ensure `Officer Data.xlsx` is in the project root with correct column names.

### "Login fails"
Check `initial_passwords.csv` for the correct password. Passwords are case-sensitive.

## License

Internal use only - NPC India
